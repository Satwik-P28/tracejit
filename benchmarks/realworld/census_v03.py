#!/usr/bin/env python3
"""Held-out real-world compatibility corpus (Phase U, `development/v0.3`).

These twenty workloads were written *after* the v0.2.0-beta.1 census and its blocker
analysis. They are a held-out sample in the strict sense: no optimisation in this
branch was chosen, sized or tuned by looking at them, and the same twenty are run
against the published `v0.2.0-beta.1` binary and against the v0.3 candidate.

The measurement machinery is imported from `census.py`, not copied, so eligibility
rates, refusal categorisation and output-equivalence checks are identical to the
original census and the two runs are directly comparable. Only the workload list and
its fixtures are new.

Every workload is deterministic, self-contained and uses a tool that is present on a
stock Linux x86_64 GNU developer image. A missing tool is reported as
`blocked_missing_tool` and excluded from the rate, never counted as a refusal.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import census

ROOT = Path(__file__).resolve().parents[2]


def prepare(scratch: Path) -> dict[str, Path]:
    """Materialises the held-out corpus fixtures. Called once per workload."""
    project = scratch / "project"
    project.mkdir(parents=True, exist_ok=True)

    (project / "util.h").write_text(
        "#ifndef UTIL_H\n#define UTIL_H\nunsigned long long mix(unsigned long long value);\n"
        "unsigned long long fold(const unsigned long long *values, unsigned count);\n#endif\n",
        encoding="utf-8",
    )
    (project / "util.c").write_text(
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
        "}\n",
        encoding="utf-8",
    )
    (project / "main.c").write_text(
        '#include "util.h"\n#include <stdio.h>\n\n'
        "int main(void) {\n"
        "    unsigned long long values[64];\n"
        "    for (unsigned index = 0; index < 64; index++) {\n"
        "        values[index] = index * 2654435761u;\n"
        "    }\n"
        '    printf("%llu\\n", fold(values, 64));\n'
        "    return 0;\n}\n",
        encoding="utf-8",
    )
    (project / "Makefile").write_text(
        "CFLAGS = -O1 -Wall\n"
        "all: app\n"
        "app: main.o util.o\n"
        "\t$(CC) $(CFLAGS) main.o util.o -o app\n"
        "main.o: main.c util.h\n"
        "\t$(CC) $(CFLAGS) -c main.c\n"
        "util.o: util.c util.h\n"
        "\t$(CC) $(CFLAGS) -c util.c\n"
        "clean:\n"
        "\trm -f app main.o util.o\n",
        encoding="utf-8",
    )

    words = scratch / "words.txt"
    words.write_text(
        "".join(
            f"{['alpha', 'beta', 'gamma', 'delta'][(index * 7) % 4]}-{index:03d}\n"
            for index in range(400)
        ),
        encoding="utf-8",
    )
    sales = scratch / "sales.csv"
    sales.write_text(
        "region,units,price_cents\n"
        + "".join(
            f"{['north', 'south', 'east', 'west'][index % 4]},{(index * 13) % 97},{(index * 31) % 5000}\n"
            for index in range(240)
        ),
        encoding="utf-8",
    )
    rows = scratch / "rows.json"
    rows.write_text(
        json.dumps(
            [
                {"id": index, "value": (index * 7919) % 100_003, "tag": f"t{index % 9}"}
                for index in range(300)
            ],
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    (scratch / "extract.json").write_text(
        "[\n"
        + ",\n".join(
            f'  {{"id": {index}, "value": {(index * 37) % 977}}}' for index in range(1, 200)
        )
        + "\n]\n",
        encoding="utf-8",
    )
    (scratch / "a.txt").write_text(
        "".join(f"shared-{index:03d}\n" for index in range(0, 60, 2))
        + "".join(f"only-a-{index:03d}\n" for index in range(0, 20)),
        encoding="utf-8",
    )
    (scratch / "b.txt").write_text(
        "".join(f"shared-{index:03d}\n" for index in range(0, 60, 2))
        + "".join(f"only-b-{index:03d}\n" for index in range(0, 20)),
        encoding="utf-8",
    )
    (scratch / "script.sh").write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "total=0\n"
        "for name in alpha beta gamma delta; do\n"
        "  count=$(grep -c \"^$name-\" \"$1\" || true)\n"
        "  total=$((total + count))\n"
        "done\n"
        "printf 'total=%s\\n' \"$total\"\n",
        encoding="utf-8",
    )
    return {"project": project, "words": words, "sales": sales, "rows": rows}


def workloads() -> list[census.Workload]:
    def gcc_preprocess(scratch: Path, data: dict[str, Path]) -> list[str]:
        project = data["project"]
        return ["gcc", "-E", "-I", str(project), str(project / "main.c"), "-o", str(scratch / "main.i")]

    def gcc_compile_link(scratch: Path, data: dict[str, Path]) -> list[str]:
        project = data["project"]
        return [
            "gcc",
            "-O1",
            "-Wall",
            "-I",
            str(project),
            str(project / "main.c"),
            str(project / "util.c"),
            "-o",
            str(scratch / "app"),
        ]

    def make_build(scratch: Path, data: dict[str, Path]) -> list[str]:
        project = data["project"]
        # A build directory per workload keeps the object files out of the fixture tree.
        for name in ("main.o", "util.o", "app"):
            (project / name).unlink(missing_ok=True)
        return ["make", "-C", str(project), "all"]

    def ar_ranlib(scratch: Path, data: dict[str, Path]) -> list[str]:
        project = data["project"]
        obj = scratch / "util.o"
        subprocess.run(
            ["gcc", "-O1", "-c", str(project / "util.c"), "-I", str(project), "-o", str(obj)],
            check=True,
            capture_output=True,
        )
        archive = scratch / "libheldout.a"
        archive.unlink(missing_ok=True)
        return ["sh", "-c", f"ar rcs {archive} {obj} && ranlib {archive}"]

    def strip_binary(scratch: Path, data: dict[str, Path]) -> list[str]:
        project = data["project"]
        built = scratch / "app-full"
        subprocess.run(
            ["gcc", "-O1", "-g", str(project / "main.c"), str(project / "util.c"), "-o", str(built)],
            check=True,
            capture_output=True,
        )
        return ["strip", "--strip-unneeded", "-o", str(scratch / "app-stripped"), str(built)]

    def strip_target(scratch: Path, data: dict[str, Path]) -> Path:
        project = data["project"]
        built = scratch / "app-full"
        subprocess.run(
            ["gcc", "-O1", "-g", str(project / "main.c"), str(project / "util.c"), "-o", str(built)],
            check=True,
            capture_output=True,
        )
        return built

    def objdump_disassemble(scratch: Path, data: dict[str, Path]) -> list[str]:
        return ["objdump", "-d", "--no-show-raw-insn", str(strip_target(scratch, data))]

    def readelf_header(scratch: Path, data: dict[str, Path]) -> list[str]:
        return ["readelf", "-h", str(strip_target(scratch, data))]

    def nm_symbols(scratch: Path, data: dict[str, Path]) -> list[str]:
        return ["nm", "--defined-only", str(strip_target(scratch, data))]

    def tar_gzip(scratch: Path, data: dict[str, Path]) -> list[str]:
        project = data["project"]
        archive = scratch / "bundle.tar.gz"
        archive.unlink(missing_ok=True)
        return [
            "tar",
            "-czf",
            str(archive),
            "-C",
            str(project),
            "main.c",
            "util.c",
            "util.h",
            "Makefile",
        ]

    def unzip_extract(scratch: Path, data: dict[str, Path]) -> list[str]:
        project = data["project"]
        archive = scratch / "bundle.zip"
        archive.unlink(missing_ok=True)
        target = scratch / "extracted.zip"
        target.unlink(missing_ok=True)
        shutil.copyfile(project / "util.c", scratch / "member-util.c")
        shutil.copyfile(project / "util.h", scratch / "member-util.h")
        subprocess.run(
            ["zip", "-q", "-X", str(target), "member-util.c", "member-util.h"],
            cwd=scratch,
            check=True,
            capture_output=True,
        )
        return ["unzip", "-q", "-o", str(target), "-d", str(scratch / "unzipped")]

    def iconv_transcode(scratch: Path, data: dict[str, Path]) -> list[str]:
        return ["iconv", "-f", "UTF-8", "-t", "ISO-8859-1", str(data["words"])]

    def base64_encode(scratch: Path, data: dict[str, Path]) -> list[str]:
        return ["base64", "-w", "76", str(data["words"])]

    def md5sum_file(scratch: Path, data: dict[str, Path]) -> list[str]:
        return ["md5sum", str(data["words"])]

    def cut_columns(scratch: Path, data: dict[str, Path]) -> list[str]:
        return ["cut", "-d", ",", "-f", "1,3", str(data["sales"])]

    def grep_count(scratch: Path, data: dict[str, Path]) -> list[str]:
        return ["grep", "-c", "^gamma-", str(data["words"])]

    def sort_unique(scratch: Path, data: dict[str, Path]) -> list[str]:
        output = scratch / "frequencies.txt"
        return [
            "sh",
            "-c",
            f"sort {data['words']} | uniq -c | sort -k1,1nr -k2,2 > {output}",
        ]

    def comm_sorted(scratch: Path, data: dict[str, Path]) -> list[str]:
        return ["comm", "-12", str(scratch / "a.txt"), str(scratch / "b.txt")]

    def find_xargs(scratch: Path, data: dict[str, Path]) -> list[str]:
        project = data["project"]
        return ["sh", "-c", f"find {project} -name '*.c' -print0 | sort -z | xargs -0 wc -l"]

    def python_json(scratch: Path, data: dict[str, Path]) -> list[str]:
        script = (
            "import json,sys\n"
            "rows = json.load(open(sys.argv[1]))\n"
            "out = [{'id': r['id'], 'value': r['value'], 'tag': r['tag']} for r in rows if r['value'] % 7 == 0]\n"
            "open(sys.argv[2], 'w').write(json.dumps(out, indent=2, sort_keys=True))\n"
        )
        return [
            sys.executable,
            "-c",
            script,
            str(data["rows"]),
            str(scratch / "filtered.json"),
        ]

    def shell_script(scratch: Path, data: dict[str, Path]) -> list[str]:
        return ["sh", str(scratch / "script.sh"), str(data["words"])]

    return [
        census.Workload(
            "heldout-gcc-preprocess",
            "compiler",
            ["gcc"],
            "Preprocesses a two-file C project with a project include directory (gcc -E).",
            gcc_preprocess,
            cwd="scratch",
            outputs=["main.i"],
        ),
        census.Workload(
            "heldout-gcc-compile-link",
            "compiler",
            ["gcc"],
            "Compiles and links a two-translation-unit C project in one gcc invocation.",
            gcc_compile_link,
            cwd="scratch",
            outputs=["app"],
        ),
        census.Workload(
            "heldout-make-build",
            "build",
            ["make", "gcc"],
            "Real Makefile with declared object rules and a link step (incremental-build unit).",
            make_build,
            cwd="scratch",
            outputs=["project/app", "project/main.o", "project/util.o"],
        ),
        census.Workload(
            "heldout-ar-ranlib",
            "archiver",
            ["sh", "gcc", "ar", "ranlib"],
            "Static archive creation followed by ranlib symbol-index generation.",
            ar_ranlib,
            cwd="scratch",
            outputs=["libheldout.a"],
        ),
        census.Workload(
            "heldout-strip-binary",
            "toolchain",
            ["strip", "gcc"],
            "strip --strip-unneeded of a debug build (binary rewriting).",
            strip_binary,
            cwd="scratch",
            outputs=["app-stripped"],
        ),
        census.Workload(
            "heldout-objdump-disassemble",
            "toolchain",
            ["objdump", "gcc"],
            "objdump -d disassembly of a compiled binary to stdout.",
            objdump_disassemble,
            cwd="scratch",
        ),
        census.Workload(
            "heldout-readelf-header",
            "toolchain",
            ["readelf", "gcc"],
            "readelf -h ELF header report (Rust/C toolchain inspection shape).",
            readelf_header,
            cwd="scratch",
        ),
        census.Workload(
            "heldout-nm-symbols",
            "toolchain",
            ["nm", "gcc"],
            "nm --defined-only symbol listing of a compiled binary.",
            nm_symbols,
            cwd="scratch",
        ),
        census.Workload(
            "heldout-tar-gzip",
            "archive",
            ["tar"],
            "tar -czf of a four-file project directory (archive creation with internal zlib).",
            tar_gzip,
            cwd="scratch",
            outputs=["bundle.tar.gz"],
        ),
        census.Workload(
            "heldout-unzip-extract",
            "archive",
            ["unzip", "zip"],
            "unzip extraction of a two-member archive into a new directory.",
            unzip_extract,
            cwd="scratch",
            outputs=["unzipped/member-util.c", "unzipped/member-util.h"],
        ),
        census.Workload(
            "heldout-iconv-transcode",
            "text",
            ["iconv"],
            "iconv UTF-8 → ISO-8859-1 transcoding of a generated word list to stdout.",
            iconv_transcode,
            cwd="scratch",
        ),
        census.Workload(
            "heldout-base64-encode",
            "text",
            ["base64"],
            "base64 -w 76 of a generated word list to stdout.",
            base64_encode,
            cwd="scratch",
        ),
        census.Workload(
            "heldout-md5sum",
            "digest",
            ["md5sum"],
            "md5sum of a generated word list (second digest implementation family).",
            md5sum_file,
            cwd="scratch",
        ),
        census.Workload(
            "heldout-cut-columns",
            "data",
            ["cut"],
            "cut field selection from a generated CSV.",
            cut_columns,
            cwd="scratch",
        ),
        census.Workload(
            "heldout-grep-count",
            "text",
            ["grep"],
            "grep -c fixed-prefix match count over a generated word list.",
            grep_count,
            cwd="scratch",
        ),
        census.Workload(
            "heldout-sort-unique-pipeline",
            "shell",
            ["sh", "sort", "uniq"],
            "sort | uniq -c | sort kernel pipeline writing a frequency table.",
            sort_unique,
            cwd="scratch",
            outputs=["frequencies.txt"],
        ),
        census.Workload(
            "heldout-comm-sorted",
            "text",
            ["comm"],
            "comm -12 intersection of two sorted generated files to stdout.",
            comm_sorted,
            cwd="scratch",
        ),
        census.Workload(
            "heldout-find-xargs",
            "shell",
            ["sh", "find", "sort", "xargs", "wc"],
            "find -print0 | sort -z | xargs -0 wc -l: a subprocess tree over a scratch project.",
            find_xargs,
            cwd="scratch",
        ),
        census.Workload(
            "heldout-python-json",
            "python",
            [sys.executable],
            "CPython JSON load/filter/dump producing a file (runtime-driven data workload).",
            python_json,
            cwd="scratch",
            env={"PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"},
            outputs=["filtered.json"],
        ),
        census.Workload(
            "heldout-shell-script",
            "shell",
            ["sh", "grep"],
            "A POSIX shell script with a loop, command substitution and arithmetic (script tree).",
            shell_script,
            cwd="scratch",
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracejit", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--contract", default=None)
    parser.add_argument("--admission", default="always", choices=["always", "auto", "never"])
    parser.add_argument("--scratch", default=None)
    args = parser.parse_args()

    tracejit = Path(args.tracejit).resolve()
    if not tracejit.is_file():
        parser.error(f"TraceJIT binary not found: {tracejit}")
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    table = census.syscall_table()

    if args.scratch:
        scratch = Path(args.scratch).resolve()
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = None
    else:
        temporary = tempfile.TemporaryDirectory(prefix="tracejit-heldout-")
        scratch = Path(temporary.name)

    # Fixtures are per workload; `census_workload` calls `census.setup_scratch` itself, so the
    # held-out fixtures are materialised here for each workload directory after it is created.
    original_setup = census.setup_scratch

    def setup_with_heldout(path: Path) -> dict[str, Path]:
        data = original_setup(path)
        data.update(prepare(path))
        return data

    census.setup_scratch = setup_with_heldout  # type: ignore[assignment]

    records = []
    try:
        for workload in workloads():
            try:
                record = census.census_workload(
                    workload,
                    tracejit,
                    scratch,
                    args.runs,
                    args.warmups,
                    table,
                    args.contract,
                    args.admission,
                )
            except Exception as error:  # noqa: BLE001 - recorded as a harness failure
                record = {
                    "name": workload.name,
                    "category": workload.category,
                    "status": "harness_error",
                    "error": str(error),
                }
            records.append(record)
            print(
                f"{record['name']:34} {record['status']:22} {record.get('classification', '-'):18} "
                f"eligible={record.get('eligible_for_reuse', '-')}",
                flush=True,
            )
    finally:
        census.setup_scratch = original_setup  # type: ignore[assignment]
        if temporary is not None:
            temporary.cleanup()

    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False
    ).stdout.strip()
    result = {
        "suite": "heldout-v03",
        "commit": commit,
        "generated_unix_ms": int(time.time() * 1000),
        "syscall_name_source": "host kernel headers" if table else "unavailable; numbers only",
        "environment": census.environment(),
        "runs": {"warmups": args.warmups, "measured": args.runs},
        "contract": args.contract,
        "admission": args.admission,
        "workloads": records,
        "aggregate": census.aggregate(records),
    }
    (output_dir / "census.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (output_dir / "census.md").write_text(census.markdown(result), encoding="utf-8")
    print(json.dumps(result["aggregate"], indent=2, sort_keys=True))
    failures = [
        record["name"]
        for record in records
        if record["status"] in ("harness_error", "unexpected_prime_result", "reuse_was_not_obtained")
        or record.get("output_equivalence") == "FAIL"
    ]
    if failures:
        print(f"HELDOUT FAILURES: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
