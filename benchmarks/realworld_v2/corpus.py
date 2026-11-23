#!/usr/bin/env python3
"""Phase AA real-world workload corpus (version 2).

Design rules, enforced by review rather than by the type system:

1. Every workload is deterministic and self-contained. No network at run time.
2. Fixtures are *generated* per workspace or copied from one shared, pinned
   upstream tree, so the native twin and the traced twin start byte-identical.
3. A command uses workspace-relative paths for everything it reads or writes.
   Shared upstream sources are referenced by an absolute path that is identical
   in both twins, so the argv strings differ only where the cwd differs.
4. Nothing here is tuned to make TraceJIT pass. An ineligible workload is a
   result, not a defect to work around.

Tiers (see docs/REAL_WORLD_BENCHMARK_PROTOCOL.md):

* ``A`` strict native: the command runs with the ambient environment and no
  execution contract. Nothing about the program, its inputs or its invocation
  is adapted.
* ``C`` adapted workload: an environment, input-shape or invocation adaptation
  is applied and listed in ``adaptations``. These rows are never mixed with A.
* ``B`` is not a workload property: it is the *execution contract* axis
  (``--contract allocator-entropy-v1``). It is measured separately for every
  workload and is never aggregated with native results.
* ``D`` is the refusal class: a workload TraceJIT cannot reuse, kept as a
  negative result. Every refused row is reported, never dropped.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ZLIB_URL = "https://zlib.net/fossils/zlib-1.3.1.tar.gz"
ZLIB_SHA256 = "9a93b2b7dfdac77ceba5a558a580e74667dd6fede4585b91eefb60f03b72df23"

COST_REPS = {"light": 20, "medium": 10, "heavy": 5}

#: Environment adaptations for tier C, always declared in ``adaptations``.
ADAPTED_ENV = {
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
}
THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
}

Mutation = Callable[[Path], str]


@dataclass(frozen=True)
class Workload:
    id: str
    family: str
    tier: str
    split: str
    cost: str
    requires: tuple[str, ...]
    note: str
    command: Callable[[Path, dict], list[str]]
    outputs: tuple[str, ...] = ()
    reset: str = "delete_outputs"
    env: dict[str, str] = field(default_factory=dict)
    adaptations: tuple[str, ...] = ()
    mutation_path: str | None = None
    unsupported_tool: str | None = None
    provenance: str = "generated"

    @property
    def reps(self) -> int:
        return COST_REPS[self.cost]


# --------------------------------------------------------------------------- #
# fixture helpers
# --------------------------------------------------------------------------- #


def _write(root: Path, relative: str, payload: str | bytes) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, bytes):
        path.write_bytes(payload)
    else:
        path.write_text(payload, encoding="utf-8")
    return path


def _blob(size: int, seed: int = 0x2545F4914F6CDD1D) -> bytes:
    """Deterministic xorshift64 stream; incompressible and checksum-stable."""

    state = seed & 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while len(out) < size:
        state ^= (state << 13) & 0xFFFFFFFFFFFFFFFF
        state ^= state >> 7
        state ^= (state << 17) & 0xFFFFFFFFFFFFFFFF
        out.extend(state.to_bytes(8, "little"))
    return bytes(out[:size])


def _text_lines(count: int, width: int = 8) -> str:
    return "".join(f"line-{index:0{width}d} value={(index * 7919) % 100003}\n" for index in range(1, count + 1))


def _json_rows(count: int) -> str:
    rows = [{"id": index, "value": (index * 7919) % 100003, "tag": f"t{index % 9}"} for index in range(count)]
    return "[\n" + ",\n".join("  " + __import__("json").dumps(row) for row in rows) + "\n]\n"


def _csv_rows(count: int) -> str:
    regions = ["north", "south", "east", "west"]
    body = "".join(
        f"{regions[index % 4]},{(index * 13) % 97},{(index * 31) % 5000}\n" for index in range(count)
    )
    return "region,units,price_cents\n" + body


C_PROJECT = {
    "util.h": (
        "#ifndef UTIL_H\n#define UTIL_H\n"
        "unsigned long long mix(unsigned long long value);\n"
        "unsigned long long fold(const unsigned long long *values, unsigned count);\n#endif\n"
    ),
    "util.c": (
        '#include "util.h"\n\n'
        "unsigned long long mix(unsigned long long value) {\n"
        "    return value * 6364136223846793005ull + 1442695040888963407ull;\n"
        "}\n\n"
        "unsigned long long fold(const unsigned long long *values, unsigned count) {\n"
        "    unsigned long long total = 0;\n"
        "    for (unsigned index = 0; index < count; index++) {\n"
        "        total ^= mix(values[index] + total);\n"
        "    }\n"
        "    return total;\n"
        "}\n"
    ),
    "main.c": (
        '#include "util.h"\n#include <stdio.h>\n\n'
        "int main(void) {\n"
        "    unsigned long long values[64];\n"
        "    for (unsigned index = 0; index < 64; index++) {\n"
        "        values[index] = index * 2654435761u;\n"
        "    }\n"
        '    printf("%llu\\n", fold(values, 64));\n'
        "    return 0;\n}\n"
    ),
    "Makefile": (
        "CFLAGS ?= -O1 -Wall\n"
        "all: app\n"
        "app: main.o util.o\n"
        "\t$(CC) $(CFLAGS) main.o util.o -o app\n"
        "main.o: main.c util.h\n"
        "\t$(CC) $(CFLAGS) -c main.c -o main.o\n"
        "util.o: util.c util.h\n"
        "\t$(CC) $(CFLAGS) -c util.c -o util.o\n"
        "clean:\n"
        "\trm -f app main.o util.o\n"
    ),
}

NUMERIC_C = r"""
#include <stdio.h>

/* Deterministic CPU-bound reduction: a fixed number of polynomial steps whose
 * printed result is a few bytes. No clock, no randomness, no allocation. */
static double step(double x) {
    /* A degree-9 odd polynomial standing in for sin(x) on [-1, 1]. */
    double x2 = x * x;
    double term = x;
    double total = 0.0;
    for (int index = 0; index < 5; index++) {
        total += term / (double)(2 * index + 1);
        term *= -x2;
    }
    return total;
}

int main(void) {
    double accumulator = 0.0;
    const int outer = 120000;
    const int inner = 500;
    for (int i = 0; i < outer; i++) {
        double base = ((double)(i % 1000) / 1000.0) - 0.5;
        for (int j = 0; j < inner; j++) {
            accumulator += step(base + (double)j * 1e-9);
        }
    }
    printf("%.12f\n", accumulator);
    return 0;
}
"""

REWRITE_SAME_C = r"""
#include <fcntl.h>
#include <unistd.h>
#include <string.h>

/* Rewrites `in.txt` with exactly the bytes it already contains (new mtime and
 * ctime, same size, same content) and then copies it to `out.txt`. This is the
 * Phase X same-size-inside-one-timestamp-tick shape, in a real command. */
int main(void) {
    char buffer[4096];
    int in = open("in.txt", O_RDONLY);
    if (in < 0) return 1;
    ssize_t got = read(in, buffer, sizeof buffer);
    close(in);
    if (got <= 0) return 1;
    int out = open("in.txt", O_WRONLY | O_TRUNC);
    if (out < 0) return 1;
    if (write(out, buffer, (size_t)got) != got) return 1;
    close(out);
    out = open("out.txt", O_WRONLY | O_CREAT | O_TRUNC, 0644);
    if (out < 0) return 1;
    if (write(out, buffer, (size_t)got) != got) return 1;
    return close(out);
}
"""

NODE_COMPUTE = r"""
// Deterministic integer mixing loop. Printing a single line keeps the output
// tiny relative to the compute cost.
let state = 0x2545F491n;
let acc = 0n;
// 3 million BigInt rounds: still hundreds of milliseconds, small output.
const rounds = 3000000n;
for (let i = 0n; i < rounds; i++) {
  state ^= (state << 13n) & 0xFFFFFFFFFFFFFFFFn;
  state ^= state >> 7n;
  state ^= (state << 17n) & 0xFFFFFFFFFFFFFFFFn;
  acc = (acc + state) & 0xFFFFFFFFFFFFFFFFn;
}
console.log(acc.toString(16));
"""

PY_COMPILE_SOURCE = '''
"""Module compiled by the py-compile workload."""


def fold(values):
    total = 0
    for value in values:
        total = (total * 1315423911 + value) & 0xFFFFFFFF
    return total
'''


def _shell(script: str) -> list[str]:
    return ["sh", "-c", script]


# --------------------------------------------------------------------------- #
# shared, pinned material
# --------------------------------------------------------------------------- #


class CorpusError(RuntimeError):
    pass


def materialize_shared(shared: Path, vendor: Path) -> dict:
    """Builds everything that must be byte-identical across both twins.

    Returns a context dict handed to every ``command`` callable. Running this
    once (instead of once per twin) is what keeps debug information, embedded
    paths and mtimes out of the comparison.
    """

    shared.mkdir(parents=True, exist_ok=True)
    zlib = vendor / "zlib-1.3.1"
    if not zlib.is_dir():
        archive = vendor / "zlib-1.3.1.tar.gz"
        if not archive.is_file():
            raise CorpusError(
                f"missing pinned upstream source {archive}; run "
                "python3 benchmarks/realworld_v2/fetch_inputs.py"
            )
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != ZLIB_SHA256:
            raise CorpusError(f"zlib archive digest {digest} != pinned {ZLIB_SHA256}")
        subprocess.run(["tar", "-xzf", str(archive), "-C", str(vendor)], check=True)

    build = shared / "build"
    build.mkdir(exist_ok=True)

    fixture = build / "fixture-driver"
    if not fixture.is_file():
        repo = Path(__file__).resolve().parents[2]
        subprocess.run(
            [
                "cc", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
                str(repo / "tests/fixtures/fixture_driver.c"), "-o", str(fixture),
            ],
            check=True,
        )

    rewrite = build / "rewrite-same"
    if not rewrite.is_file():
        source = build / "rewrite-same.c"
        source.write_text(REWRITE_SAME_C, encoding="utf-8")
        subprocess.run(["cc", "-O2", "-o", str(rewrite), str(source)], check=True)

    numeric = build / "numeric"
    if not numeric.is_file():
        source = build / "numeric.c"
        source.write_text(NUMERIC_C, encoding="utf-8")
        subprocess.run(["cc", "-O2", "-o", str(numeric), str(source)], check=True)

    # Object files and a debug binary for the toolchain workloads.
    objects = build / "objects"
    objects.mkdir(exist_ok=True)
    project = objects / "project"
    project.mkdir(exist_ok=True)
    for name, payload in C_PROJECT.items():
        _write(project, name, payload)
    for name in ("main.o", "util.o"):
        target = project / name
        if not target.is_file():
            subprocess.run(
                ["cc", "-O1", "-Wall", "-I", str(project), "-c",
                 str(project / (name[:-2] + ".c")), "-o", str(target)],
                check=True,
            )
    debug_binary = objects / "app-debug"
    if not debug_binary.is_file():
        subprocess.run(
            ["cc", "-O1", "-g", str(project / "main.c"), str(project / "util.c"),
             "-o", str(debug_binary)],
            check=True,
        )
    if not (objects / "crc32.o").is_file():
        subprocess.run(
            ["cc", "-O2", "-I", str(zlib), "-c", str(zlib / "crc32.c"),
             "-o", str(objects / "crc32.o")],
            check=True,
        )
    if not (objects / "deflate.o").is_file():
        subprocess.run(
            ["cc", "-O2", "-I", str(zlib), "-c", str(zlib / "deflate.c"),
             "-o", str(objects / "deflate.o")],
            check=True,
        )

    return {
        "shared": str(shared),
        "zlib": str(zlib),
        "build": str(build),
        "objects": str(objects),
        "project": str(project),
        "fixture": str(fixture),
        "rewrite": str(rewrite),
        "numeric": str(numeric),
        "debug_binary": str(debug_binary),
    }


def prepare(ws: Path, ctx: dict, workload: Workload) -> None:
    """Materialises the per-workspace inputs. Must be deterministic and identical."""

    ws.mkdir(parents=True, exist_ok=True)
    zlib = ctx["zlib"]

    if workload.id in {"gcc-cc-small-tu"}:
        body = "".join(
            f"static unsigned long long step_{i}(unsigned long long v) {{ return v * 1315423911ull + {i}; }}\n"
            for i in range(400)
        )
        main = "int main(void) { unsigned long long v = 1;\n" + "".join(
            f"    v = step_{i}(v);\n" for i in range(400)
        ) + "    return (int)(v >> 60); }\n"
        _write(ws, "small.c", "typedef unsigned long long u64;\n" + body + main)
        # Generated header set, so the translation unit has a real include graph.
        for index in range(6):
            _write(ws, f"gen/part{index}.h", "".join(
                f"static int part{index}_{k}(void) {{ return {index * 100 + k}; }}\n" for k in range(20)
            ))
        source = (ws / "small.c").read_text(encoding="utf-8")
        _write(ws, "small.c", "\n".join(f'#include "gen/part{i}.h"' for i in range(6)) + "\n" + source)

    if workload.id in {"gcc-multi-tu-link", "make-build", "make-incremental-noop", "gcc-link-only"}:
        for name, payload in C_PROJECT.items():
            _write(ws, name, payload)

    if workload.id in {"gcc-cpp-preprocess", "gcc-syntax-only", "gcc-fanalyzer"}:
        for name, payload in C_PROJECT.items():
            _write(ws, name, payload)

    if workload.id in {"gzip-6-stdout", "gzip-9-file", "bzip2-9-file", "xz-6-file", "xz-0-file",
                       "tar-create", "tar-gzip", "zip-create", "unzip-extract", "gzip-roundtrip"}:
        _write(ws, "corpus.txt", (Path(zlib) / "ChangeLog").read_text(encoding="utf-8", errors="replace")[:1 << 18])
        # 512 KiB, not 1 MiB: xz and bzip2 on incompressible data are slow enough
        # that a larger input would push the suite past a sane CI budget.
        _write(ws, "corpus.bin", _blob(1 << 19))

    if workload.id == "unzip-extract":
        subprocess.run(["zip", "-q", "-X", "members.zip", "corpus.txt", "corpus.bin"], cwd=ws, check=True)

    if workload.id in {"jq-sum", "jq-transform-file"}:
        _write(ws, "rows.json", _json_rows(3000))

    if workload.id in {"awk-reduce", "sed-substitute-file", "awk-float-reduce", "sort-lines",
                       "sort-uniq-counts", "cut-columns", "perl-reduce"}:
        _write(ws, "lines.txt", _text_lines(20000))

    if workload.id == "cut-columns":
        _write(ws, "sales.csv", _csv_rows(5000))

    if workload.id == "python-csv-json":
        _write(ws, "sales.csv", _csv_rows(5000))
        _write(ws, "customers.csv", "customer_id,region\n" + "".join(
            f"c{index:03d},{['north', 'south', 'east', 'west'][index % 4]}\n" for index in range(12)
        ))
        _write(ws, "etl.py", (
            "import csv, json, sys\n"
            "sales = list(csv.DictReader(open('sales.csv')))\n"
            "regions = {row['customer_id']: row['region'] for row in csv.DictReader(open('customers.csv'))}\n"
            "totals = {}\n"
            "for row in sales:\n"
            "    key = row['region']\n"
            "    totals[key] = totals.get(key, 0) + int(row['units']) * int(row['price_cents'])\n"
            "open('report.json', 'w').write(json.dumps(totals, sort_keys=True))\n"
        ))

    if workload.id == "py-compile":
        _write(ws, "module.py", PY_COMPILE_SOURCE)

    if workload.id == "py-compileall":
        for index in range(24):
            _write(ws, f"pkg/mod{index:02d}.py", PY_COMPILE_SOURCE + f"\nCONST = {index}\n")

    if workload.id == "numpy-matmul":
        _write(ws, "matmul.py", (
            "import numpy as np\n"
            "rng = np.random.default_rng(20261123)\n"
            "a = rng.random((420, 420))\n"
            "b = rng.random((420, 420))\n"
            "total = 0.0\n"
            "for _ in range(6):\n"
            "    total += float((a @ b).sum()) % 1000.0\n"
            "print(f'{total:.6f}')\n"
        ))

    if workload.id == "pil-image-transform":
        from PIL import Image  # type: ignore

        image = Image.new("RGB", (640, 480))
        pixels = image.load()
        for x in range(640):
            for y in range(480):
                pixels[x, y] = ((x * 3) % 256, (y * 5) % 256, ((x + y) * 7) % 256)
        image.save(ws / "source.png", format="PNG", optimize=False)
        _write(ws, "transform.py", (
            "from PIL import Image\n"
            "image = Image.open('source.png')\n"
            "image = image.convert('L').point(lambda p: (p // 32) * 32).resize((320, 240))\n"
            "image.save('transformed.png', format='PNG')\n"
        ))

    if workload.id == "node-compute":
        _write(ws, "compute.js", NODE_COMPUTE)

    if workload.id == "node-script-file":
        _write(ws, "records.json", _json_rows(1500))
        _write(ws, "aggregate.js", (
            "const fs = require('fs');\n"
            "const rows = JSON.parse(fs.readFileSync('records.json', 'utf8'));\n"
            "const totals = {};\n"
            "for (const row of rows) totals[row.tag] = (totals[row.tag] || 0) + row.value;\n"
            "console.log(JSON.stringify(totals));\n"
        ))

    if workload.id == "c-numeric-integration":
        _write(ws, "numeric.c", NUMERIC_C)

    if workload.id == "fs-delete-recreate":
        _write(ws, "seed.txt", _text_lines(200))

    if workload.id == "fs-symlink-input":
        _write(ws, "real.txt", _text_lines(2000))
        target = ws / "link.txt"
        target.unlink(missing_ok=True)
        os.symlink("real.txt", target)

    if workload.id == "fs-hardlink-alias":
        _write(ws, "real.txt", _text_lines(2000))

    if workload.id == "fs-identical-rewrite":
        _write(ws, "in.txt", _text_lines(500))

    if workload.id == "fs-chmod-output":
        _write(ws, "seed.txt", _text_lines(100))

    if workload.id == "make-header-change":
        for name, payload in C_PROJECT.items():
            _write(ws, name, payload)
        subprocess.run(["make", "-s", "all"], cwd=ws, check=True, capture_output=True)


# --------------------------------------------------------------------------- #
# mutations
# --------------------------------------------------------------------------- #


def _append_marker(ws: Path, relative: str) -> str:
    path = ws / relative
    original = path.read_bytes() if path.exists() else b""
    if path.is_symlink():
        path.unlink()
        path.write_bytes(original + b"\n# mutation\n")
    else:
        path.write_bytes(original + b"\n# mutation\n")
    return f"appended 12 bytes to {relative}"


def _replace_symlink_target(ws: Path) -> str:
    link = ws / "link.txt"
    link.unlink(missing_ok=True)
    _write(ws, "other.txt", _text_lines(2000) + "changed\n")
    os.symlink("other.txt", link)
    return "pointed link.txt at other.txt"


# --------------------------------------------------------------------------- #
# the corpus
# --------------------------------------------------------------------------- #


def workloads() -> list[Workload]:
    """Returns the frozen corpus in a stable order."""

    here = Path(__file__)

    corpus_digest = hashlib.sha256(here.read_bytes()).hexdigest()[:12]

    def w(*args, **kwargs) -> Workload:
        kwargs.setdefault("provenance", f"corpus.py@{corpus_digest}")
        return Workload(*args, **kwargs)

    zlib_provenance = f"zlib-1.3.1@{ZLIB_SHA256[:12]}"

    return [
        # ------------------------------------------------------------------
        # A. compilers, linkers, archivers, build systems
        # ------------------------------------------------------------------
        w("gcc-cc-small-tu", "compiler", "A", "dev", "light", ("gcc",),
          "Compiles a generated 400-function translation unit with six generated headers (gcc -O2 -c).",
          lambda ws, ctx: ["gcc", "-O2", "-Wall", "-I", "gen", "-c", "small.c", "-o", "small.o"],
          outputs=("small.o",), mutation_path="small.c"),
        w("gcc-cc-heavy-tu", "compiler", "A", "dev", "heavy", ("gcc",),
          "Compiles zlib's deflate.c at -O2: a real, compute-heavy upstream translation unit.",
          lambda ws, ctx: ["gcc", "-O2", "-I", ctx["zlib"], "-c", os.path.join(ctx["zlib"], "deflate.c"), "-o", "deflate.o"],
          outputs=("deflate.o",), provenance=zlib_provenance),
        w("gcc-multi-tu-link", "compiler", "A", "dev", "medium", ("gcc",),
          "Compiles two translation units and links them in one gcc invocation.",
          lambda ws, ctx: ["gcc", "-O1", "-Wall", "main.c", "util.c", "-o", "app"],
          outputs=("app",), mutation_path="util.c"),
        w("gcc-cpp-preprocess", "compiler", "A", "validation", "light", ("gcc",),
          "gcc -E over a three-file project with a private include directory.",
          lambda ws, ctx: ["gcc", "-E", "-I", ".", "main.c", "-o", "main.i"],
          outputs=("main.i",), mutation_path="util.h"),
        w("gcc-syntax-only", "compiler", "A", "validation", "light", ("gcc",),
          "Front-end-only lint pass with -Wall -Wextra -Werror -fsyntax-only.",
          lambda ws, ctx: ["gcc", "-fsyntax-only", "-Wall", "-Wextra", "-Werror", "-I", ".", "main.c", "util.c"],
          mutation_path="util.h"),
        w("gcc-static-archive", "archiver", "A", "validation", "light", ("ar",),
          "ar rcs of a prebuilt object, creating a static library.",
          lambda ws, ctx: ["ar", "rcs", "libutil.a", os.path.join(ctx["objects"], "project", "util.o")],
          outputs=("libutil.a",)),
        w("gcc-link-only", "linker", "A", "validation", "light", ("gcc",),
          "Links prebuilt objects into an executable with no compilation.",
          lambda ws, ctx: ["gcc", os.path.join(ctx["project"], "main.o"), os.path.join(ctx["project"], "util.o"), "-o", "app"],
          outputs=("app",)),
        w("gcc-noopt-compile", "compiler", "A", "heldout", "medium", ("gcc",),
          "Compiles zlib's crc32.c at -O0, the debugging build a developer repeats most often.",
          lambda ws, ctx: ["gcc", "-O0", "-I", ctx["zlib"], "-c", os.path.join(ctx["zlib"], "crc32.c"), "-o", "crc32.o"],
          outputs=("crc32.o",), provenance=zlib_provenance),
        w("make-build", "build", "A", "dev", "medium", ("make", "gcc"),
          "A real Makefile with declared object rules and a link step, run from a clean tree.",
          lambda ws, ctx: ["make", "-f", "Makefile", "all"],
          outputs=("app", "main.o", "util.o"), mutation_path="util.h"),
        w("make-clean", "build", "A", "dev", "light", ("make",),
          "make clean: removes build products. A command whose observable effect is deletion.",
          lambda ws, ctx: ["make", "-f", "Makefile", "clean"],
          reset="none"),
        w("make-incremental-noop", "build", "A", "validation", "light", ("make", "gcc"),
          "Repeats an already-satisfied make target with outputs present (the true incremental no-op).",
          lambda ws, ctx: ["make", "-f", "Makefile", "all"],
          outputs=("app", "main.o", "util.o"), reset="keep_outputs"),
        w("make-header-change", "build", "A", "heldout", "medium", ("make", "gcc"),
          "Rebuilds after util.h changes; outputs are prebuilt in prepare, so the run recompiles both objects.",
          lambda ws, ctx: ["make", "-f", "Makefile", "all"],
          outputs=("app", "main.o", "util.o"), reset="keep_outputs", mutation_path="util.h"),

        # ------------------------------------------------------------------
        # B. static analysis
        # ------------------------------------------------------------------
        w("gcc-fanalyzer", "analysis", "A", "dev", "heavy", ("gcc",),
          "gcc -fanalyzer over a small project: a real static analyser pass.",
          lambda ws, ctx: ["gcc", "-fanalyzer", "-c", "-I", ".", "util.c", "-o", "util.o"],
          outputs=("util.o",), mutation_path="util.c"),
        w("cppcheck-project", "analysis", "C", "dev", "medium", ("cppcheck",),
          "cppcheck over the C project. Not installed on every image; a missing tool is not a refusal.",
          lambda ws, ctx: ["cppcheck", "--quiet", "util.c"],
          unsupported_tool="cppcheck"),
        w("shellcheck-script", "analysis", "C", "validation", "light", ("shellcheck",),
          "shellcheck over a shell script (deterministic static analysis).",
          lambda ws, ctx: ["shellcheck", "-s", "sh", "run.sh"],
          unsupported_tool="shellcheck"),
        w("ruff-check", "analysis", "C", "validation", "light", ("ruff",),
          "ruff check over a Python package (fast deterministic linter).",
          lambda ws, ctx: ["ruff", "check", "pkg"],
          unsupported_tool="ruff"),
        w("py-compile", "analysis", "C", "dev", "light", ("python3",),
          "CPython bytecode compilation of one module.",
          lambda ws, ctx: [sys.executable, "-m", "py_compile", "module.py"],
          env=dict(ADAPTED_ENV), adaptations=("PYTHONHASHSEED=0", "PYTHONDONTWRITEBYTECODE=1"),
          outputs=("__pycache__",), mutation_path="module.py"),
        w("py-compileall", "analysis", "C", "heldout", "light", ("python3",),
          "python -m compileall over a 24-module package.",
          lambda ws, ctx: [sys.executable, "-m", "compileall", "-q", "pkg"],
          env=dict(ADAPTED_ENV), adaptations=("PYTHONHASHSEED=0", "PYTHONDONTWRITEBYTECODE=1"),
          outputs=("pkg/__pycache__",)),

        # ------------------------------------------------------------------
        # C. compression and packaging
        # ------------------------------------------------------------------
        w("gzip-6-stdout", "compression", "A", "dev", "medium", ("gzip",),
          "gzip -6 -n of 256 KiB of real upstream text to stdout.",
          lambda ws, ctx: ["gzip", "-6", "-n", "-c", "corpus.txt"],
          mutation_path="corpus.txt"),
        w("gzip-9-file", "compression", "A", "dev", "medium", ("gzip",),
          "gzip -9 -n -k -f of a 1 MiB incompressible blob, producing a file.",
          lambda ws, ctx: ["gzip", "-9", "-n", "-k", "-f", "corpus.bin"],
          outputs=("corpus.bin.gz",), mutation_path="corpus.bin"),
        w("bzip2-9-file", "compression", "A", "validation", "heavy", ("bzip2",),
          "bzip2 -9 of a 1 MiB incompressible blob.",
          lambda ws, ctx: ["bzip2", "-9", "-k", "-f", "corpus.bin"],
          outputs=("corpus.bin.bz2",), mutation_path="corpus.bin"),
        w("xz-6-file", "compression", "A", "validation", "heavy", ("xz",),
          "xz -6 of a 1 MiB incompressible blob (the slow, high-ratio preset).",
          lambda ws, ctx: ["xz", "-6", "-k", "-f", "corpus.bin"],
          outputs=("corpus.bin.xz",), mutation_path="corpus.bin"),
        w("xz-0-file", "compression", "A", "dev", "medium", ("xz",),
          "xz -0 of the same blob (fast preset), so the ratio/cost trade-off is visible.",
          lambda ws, ctx: ["xz", "-0", "-k", "-f", "corpus.bin"],
          outputs=("corpus.bin.xz",), mutation_path="corpus.bin"),
        w("zstd-19-file", "compression", "A", "validation", "heavy", ("zstd",),
          "zstd -19 of the blob, the modern default a build actually uses.",
          lambda ws, ctx: ["zstd", "-19", "-q", "-f", "corpus.bin", "-o", "corpus.bin.zst"],
          unsupported_tool="zstd"),
        w("tar-create", "packaging", "A", "dev", "light", ("tar",),
          "tar -cf of two files into an uncompressed archive.",
          lambda ws, ctx: ["tar", "-cf", "bundle.tar", "corpus.txt", "corpus.bin"],
          outputs=("bundle.tar",), mutation_path="corpus.bin"),
        w("tar-gzip", "packaging", "A", "validation", "medium", ("tar",),
          "tar -czf of a real upstream source subset (archive creation with internal zlib).",
          lambda ws, ctx: ["tar", "-czf", "zlib-src.tar.gz", "-C", ctx["zlib"],
                           "adler32.c", "crc32.c", "deflate.c", "trees.c", "zlib.h", "zconf.h"],
          outputs=("zlib-src.tar.gz",), provenance=zlib_provenance),
        w("zip-create", "packaging", "A", "validation", "light", ("zip",),
          "zip -X of two files (timestamps suppressed for reproducibility).",
          lambda ws, ctx: ["zip", "-q", "-X", "bundle.zip", "corpus.txt", "corpus.bin"],
          outputs=("bundle.zip",), mutation_path="corpus.bin"),
        w("unzip-extract", "packaging", "A", "heldout", "light", ("unzip", "zip"),
          "unzip -o extraction of a two-member archive into a new directory.",
          lambda ws, ctx: ["unzip", "-q", "-o", "members.zip", "-d", "extracted"],
          outputs=("extracted",)),
        w("gzip-roundtrip", "compression", "A", "heldout", "medium", ("gzip", "sh"),
          "gzip -c | gzip -dc round-trip into a file: a two-process pipe.",
          lambda ws, ctx: _shell("gzip -c -n corpus.bin | gzip -dc > roundtrip.bin"),
          outputs=("roundtrip.bin",), mutation_path="corpus.bin"),

        # ------------------------------------------------------------------
        # D. data processing
        # ------------------------------------------------------------------
        w("jq-sum", "data", "A", "dev", "light", ("jq",),
          "jq reduction over 3000 JSON records to stdout.",
          lambda ws, ctx: ["jq", "[.[].value] | add", "rows.json"],
          mutation_path="rows.json"),
        w("jq-transform-file", "data", "A", "validation", "light", ("jq", "sh"),
          "jq projection of JSON records into a file (data normalisation shape).",
          lambda ws, ctx: _shell("jq '[.[] | select(.value % 7 == 0) | {id, tag}]' rows.json > filtered.json"),
          outputs=("filtered.json",), mutation_path="rows.json"),
        w("awk-reduce", "data", "A", "dev", "light", ("awk",),
          "awk numeric reduction over 20000 lines.",
          lambda ws, ctx: ["awk", "{ s += $2 } END { printf \"%d\\n\", s }", "lines.txt"],
          mutation_path="lines.txt"),
        w("sed-substitute-file", "data", "A", "dev", "light", ("sed",),
          "sed substitution over 20000 lines to stdout.",
          lambda ws, ctx: ["sed", "s/value=/v=/g", "lines.txt"],
          mutation_path="lines.txt"),
        w("sort-lines", "data", "A", "dev", "medium", ("sort",),
          "sort of 20000 lines to stdout.",
          lambda ws, ctx: ["sort", "lines.txt"],
          mutation_path="lines.txt"),
        w("sort-uniq-counts", "data", "A", "validation", "medium", ("sh", "sort", "uniq"),
          "sort | uniq -c | sort -k1,1nr frequency table into a file.",
          lambda ws, ctx: _shell("sort lines.txt | uniq -c | sort -k1,1nr -k2,2 > frequencies.txt"),
          outputs=("frequencies.txt",), mutation_path="lines.txt"),
        w("cut-columns", "data", "A", "heldout", "light", ("cut",),
          "cut two columns out of a 5000-row CSV.",
          lambda ws, ctx: ["cut", "-d", ",", "-f", "1,3", "sales.csv"],
          mutation_path="sales.csv"),
        w("python-csv-json", "data", "C", "heldout", "medium", ("python3",),
          "CPython CSV-to-JSON aggregation over 5000 rows.",
          lambda ws, ctx: [sys.executable, "etl.py"],
          env=dict(ADAPTED_ENV), adaptations=("PYTHONHASHSEED=0", "PYTHONDONTWRITEBYTECODE=1"),
          outputs=("report.json",), mutation_path="sales.csv"),
        w("numpy-matmul", "scientific", "C", "validation", "heavy", ("python3",),
          "NumPy matrix products on 420x420 deterministic matrices, single-threaded.",
          lambda ws, ctx: [sys.executable, "matmul.py"],
          env={**ADAPTED_ENV, **THREAD_ENV},
          adaptations=("PYTHONHASHSEED=0", "PYTHONDONTWRITEBYTECODE=1", "BLAS/OMP threads pinned to 1"),
          mutation_path="matmul.py"),
        w("parquet-convert", "data", "C", "heldout", "medium", ("python3",),
          "CSV to Parquet conversion. Requires pyarrow, which is not on every image.",
          lambda ws, ctx: [sys.executable, "-c",
                           "import pandas as pd; pd.read_csv('sales.csv').to_parquet('sales.parquet')"],
          unsupported_tool="pyarrow"),

        # ------------------------------------------------------------------
        # E. scientific / compute-bound
        # ------------------------------------------------------------------
        w("c-numeric-integration", "scientific", "A", "dev", "heavy", ("gcc",),
          "A 60-million-step numeric reduction compiled and run: small output, large compute.",
          lambda ws, ctx: [ctx["numeric"]]),
          # No mutation: the binary reads no workspace input, so an input edit
          # could not legitimately change its decision.
        w("awk-float-reduce", "scientific", "A", "validation", "light", ("awk",),
          "Iterative floating-point reduction in awk over 20000 numbers.",
          lambda ws, ctx: ["awk", "BEGIN { x=1.0 } { x = x * 1.0000007 + ($1 % 97) } END { printf \"%.10f\\n\", x }", "lines.txt"],
          mutation_path="lines.txt"),
        w("pil-image-transform", "scientific", "C", "heldout", "medium", ("python3",),
          "Deterministic Pillow grayscale/posterize/resize of a generated PNG.",
          lambda ws, ctx: [sys.executable, "transform.py"],
          env=dict(ADAPTED_ENV), adaptations=("PYTHONHASHSEED=0", "PYTHONDONTWRITEBYTECODE=1"),
          outputs=("transformed.png",), mutation_path="source.png"),

        # ------------------------------------------------------------------
        # F. interpreters and developer tooling
        # ------------------------------------------------------------------
        w("node-compute", "tooling", "A", "dev", "heavy", ("node",),
          "Node.js 3-million-round BigInt mixing loop; one line of output.",
          lambda ws, ctx: ["node", "compute.js"],
          mutation_path="compute.js"),
        w("node-script-file", "tooling", "A", "validation", "medium", ("node",),
          "Node.js JSON aggregation over 1500 records.",
          lambda ws, ctx: ["node", "aggregate.js"],
          mutation_path="records.json"),
        w("perl-reduce", "tooling", "A", "validation", "light", ("perl",),
          "perl -lne numeric reduction over 20000 lines.",
          lambda ws, ctx: ["perl", "-lne", "$s += $1 if /value=(\\d+)/; END { print $s+0 }", "lines.txt"],
          mutation_path="lines.txt"),
        w("objcopy-strip", "tooling", "A", "dev", "light", ("objcopy",),
          "objcopy --strip-unneeded on a prebuilt object.",
          lambda ws, ctx: ["objcopy", "--strip-unneeded", os.path.join(ctx["objects"], "crc32.o"), "stripped.o"],
          outputs=("stripped.o",)),
        w("strip-binary", "tooling", "A", "heldout", "light", ("strip",),
          "strip --strip-unneeded of a debug binary (binary rewriting).",
          lambda ws, ctx: ["strip", "--strip-unneeded", "-o", "app-stripped", ctx["debug_binary"]],
          outputs=("app-stripped",)),
        w("objdump-disassemble", "tooling", "A", "heldout", "light", ("objdump",),
          "objdump -d disassembly of a compiled binary to stdout.",
          lambda ws, ctx: ["objdump", "-d", "--no-show-raw-insn", ctx["debug_binary"]]),
        w("readelf-header", "tooling", "A", "heldout", "light", ("readelf",),
          "readelf -h ELF header report to stdout.",
          lambda ws, ctx: ["readelf", "-h", ctx["debug_binary"]]),
        w("nm-symbols", "tooling", "A", "heldout", "light", ("nm",),
          "nm --defined-only symbol listing to stdout.",
          lambda ws, ctx: ["nm", "--defined-only", ctx["debug_binary"]]),

        # ------------------------------------------------------------------
        # G. filesystem-sensitive workflows
        # ------------------------------------------------------------------
        w("fs-delete-recreate", "filesystem", "A", "dev", "light", ("sh",),
          "Deletes and recreates an output file in one shell command.",
          lambda ws, ctx: _shell("rm -f out.dat && cat seed.txt > out.dat"),
          outputs=("out.dat",), reset="none", mutation_path="seed.txt"),
        w("fs-symlink-input", "filesystem", "A", "validation", "light", ("sh",),
          "Reads its input through a symlink and writes a regular output.",
          lambda ws, ctx: _shell("sed 's/line/LINE/' link.txt > out.txt"),
          outputs=("out.txt",), mutation_path="link.txt"),
        w("fs-hardlink-alias", "filesystem", "A", "validation", "light", ("sh",),
          "Creates a hard-link alias of its input and reads through it.",
          lambda ws, ctx: _shell("ln -f real.txt alias.txt && cat alias.txt > out.txt"),
          outputs=("out.txt", "alias.txt"), reset="none", mutation_path="real.txt"),
        w("fs-identical-rewrite", "filesystem", "A", "heldout", "light", ("cc",),
          "Rewrites its input with identical bytes (same size, new timestamps) and copies it.",
          lambda ws, ctx: [ctx["rewrite"]],
          outputs=("in.txt", "out.txt"), reset="none", mutation_path="in.txt"),
        w("fs-chmod-output", "filesystem", "A", "heldout", "light", ("sh",),
          "Writes an output and changes its permission bits.",
          lambda ws, ctx: _shell("cat seed.txt > out.txt && chmod 640 out.txt"),
          outputs=("out.txt",), reset="none", mutation_path="seed.txt"),

        # ------------------------------------------------------------------
        # H. real upstream projects
        # ------------------------------------------------------------------
        w("zlib-compile-adler32", "real-project", "A", "dev", "light", ("gcc",),
          "Compiles zlib 1.3.1 adler32.c -O2 (a small real upstream unit).",
          lambda ws, ctx: ["gcc", "-O2", "-I", ctx["zlib"], "-c", os.path.join(ctx["zlib"], "adler32.c"), "-o", "adler32.o"],
          outputs=("adler32.o",), provenance=zlib_provenance),
        w("zlib-compile-deflate", "real-project", "A", "validation", "heavy", ("gcc",),
          "Compiles zlib 1.3.1 deflate.c -O2, the heaviest real translation unit in the suite.",
          lambda ws, ctx: ["gcc", "-O2", "-I", ctx["zlib"], "-c", os.path.join(ctx["zlib"], "deflate.c"), "-o", "deflate.o"],
          outputs=("deflate.o",), provenance=zlib_provenance),
        w("zlib-archive", "real-project", "A", "validation", "light", ("ar",),
          "ar rcs of a real zlib object into a static library.",
          lambda ws, ctx: ["ar", "rcs", "libz-part.a", os.path.join(ctx["objects"], "crc32.o")],
          outputs=("libz-part.a",), provenance=zlib_provenance),
        w("zlib-gzip-tarball", "real-project", "A", "heldout", "heavy", ("tar",),
          "tar -czf of six real zlib sources (upstream input distribution).",
          lambda ws, ctx: ["tar", "-czf", "zlib-src.tar.gz", "-C", ctx["zlib"],
                           "adler32.c", "crc32.c", "deflate.c", "trees.c", "zlib.h", "zconf.h"],
          outputs=("zlib-src.tar.gz",), provenance=zlib_provenance),
    ]


def by_id() -> dict[str, Workload]:
    return {workload.id: workload for workload in workloads()}


def manifest_entries(vendor: Path | None = None) -> list[dict]:
    """Machine-readable, version-pinned description of the corpus."""

    entries = []
    for workload in workloads():
        entries.append(
            {
                "workload_id": workload.id,
                "family": workload.family,
                "split": workload.split,
                "environment_tier": workload.tier,
                "cost_class": workload.cost,
                "planned_repetitions": workload.reps,
                "required_tools": list(workload.requires),
                "outputs": list(workload.outputs),
                "reset_policy": workload.reset,
                "environment_adaptations": dict(workload.env),
                "adaptations": list(workload.adaptations),
                "mutation_input": workload.mutation_path,
                "unsupported_tool": workload.unsupported_tool,
                "provenance": workload.provenance,
                "note": workload.note,
                "mutator": (
                    "replace_symlink_target" if workload.id == "fs-symlink-input" else
                    ("append_marker" if workload.mutation_path else None)
                ),
            }
        )
    # The pinned source metadata is a constant, so it is emitted whether or not
    # the archive happens to be present locally. Gating it on a local file made
    # `runner.py --mode manifest` produce two different manifests depending on
    # cache state, which is precisely the kind of hidden state a fresh checkout
    # must not depend on.
    for entry in entries:
        if entry["provenance"].startswith("zlib-1.3.1"):
            entry["source"] = {
                "kind": "upstream-archive",
                "name": "zlib",
                "version": "1.3.1",
                "url": ZLIB_URL,
                "sha256": ZLIB_SHA256,
            }
    return entries


def apply_mutation(workload: Workload, ws: Path) -> str | None:
    if workload.id == "fs-symlink-input":
        return _replace_symlink_target(ws)
    if workload.mutation_path is None:
        return None
    return _append_marker(ws, workload.mutation_path)


def restore_mutation(workload: Workload, ws: Path, ctx: dict) -> None:
    """Undoes ``apply_mutation`` by re-running the deterministic preparation.

    Preparation rewrites every fixture from its definition, so re-running it is
    exactly "return this input to the state it had before the mutation".
    """

    prepare(ws, ctx, workload)
