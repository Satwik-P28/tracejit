#!/usr/bin/env python3
"""Phase AC: eligibility and economics for non-compiler workloads.

TraceJIT's frozen corpus is compiler-heavy.  This harness asks a narrower and
more useful question: are there *authentic* non-compiler commands, with real
third-party programs and pinned inputs, that TraceJIT can reuse correctly, and
if so, what does a session of repeated invocations actually cost?

Two modes:

``probe``
    Runs every configuration twice per policy (native, compiler-runtime-v1) in a
    fresh workspace with a fresh cache, and records the classification, the
    refusal reasons, whether a warm run reuses, and whether the independent
    oracle accepts the reuse.  A refusal is a result and is reported.

``session``
    For configurations that reuse, measures a real repeated-invocation session:
    one cold traced run followed by N-1 warm runs, against N native runs.  Both
    the model (cold + (n-1)*hit) and the measured wall clock are reported, plus
    the cache's storage cost and the break-even repetition count.

Design rules (same as the frozen corpus):

* pinned, deterministically generated inputs; no network at run time
* every command is a real third-party program, not a bespoke CPU loop
* outputs are deleted before each invocation, so a reuse must restore them
* a native twin directory is used for the oracle comparison
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
BENCH = HERE.parent
sys.path.insert(0, str(BENCH / "realworld_v2"))

import oracle  # noqa: E402
import runner  # noqa: E402

ZLIB_URL = "https://zlib.net/fossils/zlib-1.3.1.tar.gz"


def blob(size: int, seed: int = 0x2545F4914F6CDD1D) -> bytes:
    state = seed & 0xFFFFFFFFFFFFFFFF
    out = bytearray()
    while len(out) < size:
        state ^= (state << 13) & 0xFFFFFFFFFFFFFFFF
        state ^= state >> 7
        state ^= (state << 17) & 0xFFFFFFFFFFFFFFFF
        out.extend(state.to_bytes(8, "little"))
    return bytes(out[:size])


def text_lines(count: int) -> str:
    return "".join(f"row-{i:07d} key={(i * 7919) % 100003} tag=t{i % 11}\n" for i in range(1, count + 1))


class Config:
    def __init__(self, identifier, family, note, argv, outputs=(), inputs=None, tools=()):
        self.id = identifier
        self.family = family
        self.note = note
        self.argv = argv          # callable(ws, shared) -> list[str]
        self.outputs = tuple(outputs)
        self.inputs = inputs      # callable(ws, shared) -> None
        self.tools = tuple(tools)


def _shared_inputs(shared: Path, vendor: Path) -> dict:
    shared.mkdir(parents=True, exist_ok=True)
    text = shared / "corpus.txt"
    if not text.is_file():
        changelog = vendor / "zlib-1.3.1" / "ChangeLog"
        if not changelog.is_file():
            archive = vendor / "zlib-1.3.1.tar.gz"
            if not archive.is_file():
                raise SystemExit(f"missing {archive}; run benchmarks/realworld_v2/fetch_inputs.py")
            subprocess.run(["tar", "xzf", str(archive), "-C", str(vendor)], check=True)
        text.write_text(changelog.read_text(errors="replace")[:1 << 18])
    binary_blob = shared / "blob.bin"
    if not binary_blob.is_file():
        binary_blob.write_bytes(blob(1 << 21))
    lines = shared / "lines.txt"
    if not lines.is_file():
        lines.write_text(text_lines(200_000))
    # A real system binary is the input for the binutils workloads: authentic,
    # already present on the image, and large enough for stripping/disassembly to
    # cost real time.
    real_binary = shared / "real-binary"
    if not real_binary.is_file():
        candidate = Path("/usr/bin/x86_64-linux-gnu-gcc-13")
        if not candidate.is_file():
            candidate = Path("/usr/bin/gcc")
        shutil.copyfile(candidate, real_binary)
    return {
        "text": str(text),
        "blob": str(binary_blob),
        "lines": str(lines),
        "binary": str(real_binary),
    }


def _copy(shared_path: str, relative: str):
    def prepare(ws: Path, shared: dict) -> None:
        shutil.copyfile(shared_path, ws / relative)
    return prepare


def configs(shared: dict) -> list[Config]:
    text, blob_path, lines, binary = shared["text"], shared["blob"], shared["lines"], shared["binary"]
    return [
        # --- compression -----------------------------------------------------
        Config("gzip-9-text-stdout", "compression",
               "gzip -9 -n -c of 256 KiB of real upstream text to stdout",
               lambda ws, sh: ["gzip", "-9", "-n", "-c", "corpus.txt"],
               inputs=_copy(text, "corpus.txt")),
        Config("gzip-9-blob-file", "compression",
               "gzip -9 -n -k -f of a 2 MiB incompressible blob, producing a file",
               lambda ws, sh: ["gzip", "-9", "-n", "-k", "-f", "blob.bin"],
               outputs=("blob.bin.gz",), inputs=_copy(blob_path, "blob.bin")),
        Config("bzip2-9-blob-file", "compression",
               "bzip2 -9 -k -f of a 2 MiB incompressible blob",
               lambda ws, sh: ["bzip2", "-9", "-k", "-f", "blob.bin"],
               outputs=("blob.bin.bz2",), inputs=_copy(blob_path, "blob.bin")),
        Config("xz-6-blob-file", "compression",
               "xz -6 -k -f of a 2 MiB incompressible blob",
               lambda ws, sh: ["xz", "-6", "-k", "-f", "blob.bin"],
               outputs=("blob.bin.xz",), inputs=_copy(blob_path, "blob.bin")),
        # --- binary inspection / rewriting ----------------------------------
        Config("objcopy-strip-real-binary", "binutils",
               "objcopy --strip-unneeded of a real system binary",
               lambda ws, sh: ["objcopy", "--strip-unneeded", "real-binary", "stripped"],
               outputs=("stripped",), inputs=_copy(binary, "real-binary")),
        Config("strip-real-binary", "binutils",
               "strip --strip-unneeded -o of a real system binary",
               lambda ws, sh: ["strip", "--strip-unneeded", "-o", "stripped", "real-binary"],
               outputs=("stripped",), inputs=_copy(binary, "real-binary")),
        Config("objdump-disassemble-real-binary", "binutils",
               "objdump -d of a real system binary to stdout (heavy, streaming output)",
               lambda ws, sh: ["objdump", "-d", "--no-show-raw-insn", "real-binary"],
               inputs=_copy(binary, "real-binary")),
        Config("readelf-header-real-binary", "binutils",
               "readelf -h of a real system binary to stdout (tiny compute)",
               lambda ws, sh: ["readelf", "-h", "real-binary"],
               inputs=_copy(binary, "real-binary")),
        Config("nm-symbols-real-binary", "binutils",
               "nm --defined-only of a real system binary to stdout",
               lambda ws, sh: ["nm", "--defined-only", "real-binary"],
               inputs=_copy(binary, "real-binary")),
        # --- text / data processing -----------------------------------------
        Config("sed-substitute-large-file", "data",
               "sed substitution with 200k lines to stdout",
               lambda ws, sh: ["sed", "s/key=/k=/g", "lines.txt"],
               inputs=_copy(lines, "lines.txt")),
        Config("sort-large-file", "data",
               "sort of 200k lines to stdout",
               lambda ws, sh: ["sort", "lines.txt"],
               inputs=_copy(lines, "lines.txt")),
        Config("awk-reduce-large-file", "data",
               "awk numeric reduction over 200k lines",
               lambda ws, sh: ["awk", "{ s += $2 } END { printf \"%d\\n\", s }", "lines.txt"],
               inputs=_copy(lines, "lines.txt")),
        Config("perl-reduce-large-file", "data",
               "perl numeric reduction over 200k lines",
               lambda ws, sh: ["perl", "-lne", "$s += $1 if /key=(\\d+)/; END { print $s+0 }", "lines.txt"],
               inputs=_copy(lines, "lines.txt")),
        Config("sha256sum-real-binary", "tooling",
               "sha256sum of a real system binary (pure compute, tiny output)",
               lambda ws, sh: ["sha256sum", "real-binary"],
               inputs=_copy(binary, "real-binary")),
        Config("base64-real-binary", "tooling",
               "base64 encode of a real system binary to stdout",
               lambda ws, sh: ["base64", "real-binary"],
               inputs=_copy(binary, "real-binary")),
        Config("tar-create", "packaging",
               "tar -cf of two files into an uncompressed archive",
               lambda ws, sh: ["tar", "-cf", "bundle.tar", "corpus.txt", "blob.bin"],
               outputs=("bundle.tar",),
               inputs=lambda ws, sh: (_copy(text, "corpus.txt")(ws, sh), _copy(blob_path, "blob.bin")(ws, sh))),
    ]


def cache_size(path: Path) -> int:
    total = 0
    for dirpath, _, filenames in os.walk(path):
        for name in filenames:
            try:
                total += (Path(dirpath) / name).lstat().st_size
            except OSError:
                pass
    return total


def prepare_pair(cfg: Config, root: Path, shared: dict) -> tuple[Path, Path]:
    native_ws = root / "native"
    traced_ws = root / "traced"
    for ws in (native_ws, traced_ws):
        ws.mkdir(parents=True)
        if cfg.inputs:
            cfg.inputs(ws, shared)
    # Identical metadata on both sides: see docs/PHASE_AC_COLD_MISMATCH_AUDIT.md.
    for item in native_ws.iterdir():
        if item.is_file():
            os.utime(traced_ws / item.name, ns=(item.stat().st_atime_ns, item.stat().st_mtime_ns))
    return native_ws, traced_ws


def run_probe(args: argparse.Namespace) -> dict:
    shared = _shared_inputs(args.scratch / "shared", args.vendor)
    base_env = dict(os.environ)
    rows = []
    for cfg in configs(shared):
        missing = [tool for tool in cfg.tools if shutil.which(tool) is None]
        if missing:
            rows.append({"config": cfg.id, "family": cfg.family, "status": "tool_unavailable",
                         "missing": missing})
            continue
        root = args.scratch / "probe" / cfg.id
        shutil.rmtree(root, ignore_errors=True)
        native_ws, traced_ws = prepare_pair(cfg, root, shared)
        argv = cfg.argv(traced_ws, shared)
        native = subprocess.run(cfg.argv(native_ws, shared), cwd=native_ws, capture_output=True)
        native_obs = oracle.process_observation(
            native.returncode, native.stdout, native.stderr, oracle.observe_workspace(native_ws)
        )
        row = {"config": cfg.id, "family": cfg.family, "note": cfg.note,
               "argv": [Path(a).name if a.startswith(str(args.scratch)) else a for a in argv],
               "native_exit": native.returncode, "policies": {}}
        for policy in ("native", "allocator-entropy-v1", "compiler-runtime-v1"):
            cache = root / f"cache-{policy}"
            env = runner.cache_env(base_env, cache)
            for ws in (traced_ws,):
                for name in cfg.outputs:
                    target = ws / name
                    if target.is_dir():
                        shutil.rmtree(target)
                    elif target.exists():
                        target.unlink()
            cold_started = time.perf_counter_ns()
            _, cold_decision, cold_report, cold_stdout, cold_stderr = runner.run_traced(
                args.tracejit, argv, traced_ws, env, policy
            )
            cold_ns = time.perf_counter_ns() - cold_started
            cold_obs = oracle.process_observation(
                int((cold_report or {}).get("exit_code", -1)), cold_stdout, cold_stderr,
                oracle.observe_workspace(traced_ws),
            )
            cold_compare = oracle.compare(native_obs, cold_obs)
            entry = {
                "cold_ns": cold_ns,
                "classification": (cold_report or {}).get("classification"),
                "eligible": (cold_report or {}).get("eligible_for_reuse"),
                "reasons": (cold_report or {}).get("reasons"),
                "output_count": (cold_report or {}).get("output_count"),
                "cold_match": cold_compare["match"],
            }
            for name in cfg.outputs:
                target = traced_ws / name
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.exists():
                    target.unlink()
            warm_started = time.perf_counter_ns()
            _, warm_decision, warm_report, warm_stdout, warm_stderr = runner.run_traced(
                args.tracejit, argv, traced_ws, env, policy
            )
            entry["warm_ns"] = time.perf_counter_ns() - warm_started
            warm_obs = oracle.process_observation(
                int((warm_report or {}).get("exit_code", -1)), warm_stdout, warm_stderr,
                oracle.observe_workspace(traced_ws),
            )
            warm_compare = oracle.compare(native_obs, warm_obs)
            entry["reused"] = runner.is_hit(warm_decision)
            entry["warm_match"] = warm_compare["match"]
            entry["warm_covered_differences"] = warm_compare["covered_differences"]
            entry["cache_bytes"] = cache_size(cache)
            row["policies"][policy] = entry
        rows.append(row)
        shutil.rmtree(root, ignore_errors=True)
    return {"mode": "probe", "rows": rows}


def run_session(args: argparse.Namespace, probe: dict) -> dict:
    shared = _shared_inputs(args.scratch / "shared", args.vendor)
    base_env = dict(os.environ)
    sessions = [int(item) for item in args.sessions.split(",")]
    results = []
    only = {item.strip() for item in args.only.split(",") if item.strip()} if args.only else None
    reusable = [
        row for row in probe["rows"]
        if any(entry.get("reused") and entry.get("warm_match") for entry in row["policies"].values())
        and (only is None or row["config"] in only)
    ]
    for row in reusable:
        cfg = next(c for c in configs(shared) if c.id == row["config"])
        # Prefer the weakest policy that reuses: native needs no contract at all,
        # and allocator-entropy-v1 names the glibc allocator, which is the actual
        # source of the getrandom refusal for these programs.  compiler-runtime-v1
        # is the broadest profile and is used only when nothing weaker reuses.
        policy = next(
            candidate for candidate in ("native", "allocator-entropy-v1", "compiler-runtime-v1")
            if row["policies"].get(candidate, {}).get("reused")
            and row["policies"][candidate].get("warm_match")
        )
        root = args.scratch / "session" / cfg.id
        shutil.rmtree(root, ignore_errors=True)
        native_ws, traced_ws = prepare_pair(cfg, root, shared)
        cache = root / "cache"
        env = runner.cache_env(base_env, cache)
        argv = cfg.argv(traced_ws, shared)
        native_argv = cfg.argv(native_ws, shared)

        def clean(ws: Path) -> None:
            for name in cfg.outputs:
                target = ws / name
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.exists():
                    target.unlink()

        # Native per-invocation cost: median of repeated clean runs.
        direct_samples = []
        for _ in range(max(3, args.reps)):
            clean(native_ws)
            started = time.perf_counter_ns()
            completed = subprocess.run(native_argv, cwd=native_ws, capture_output=True)
            direct_samples.append(time.perf_counter_ns() - started)
            if completed.returncode != 0:
                break
        direct_ns = int(statistics.median(direct_samples))

        # Traced session: one cold run, then warm runs, with outputs removed each time.
        # Plain mode is what a user runs. `--json` serialises the whole cached
        # stdout as a byte array inside TraceJIT and again in this process, which
        # Phase AB measured at up to 60 ms on a 70 ms hit; timing that channel
        # would be timing the harness.
        clean(traced_ws)
        cold_started = time.perf_counter_ns()
        _, decision = runner.run_plain(args.tracejit, argv, traced_ws, env, policy)
        cold_ns = time.perf_counter_ns() - cold_started
        hit_samples = []
        for _ in range(max(3, args.reps)):
            clean(traced_ws)
            started = time.perf_counter_ns()
            _, warm_decision = runner.run_plain(args.tracejit, argv, traced_ws, env, policy)
            hit_samples.append(time.perf_counter_ns() - started)
            if not runner.is_hit(warm_decision):
                break
        hit_ns = int(statistics.median(hit_samples)) if hit_samples else None

        measured_sessions = []
        if hit_ns:
            for count in sessions:
                # Native total for `count` clean invocations.
                clean(native_ws)
                native_started = time.perf_counter_ns()
                for index in range(count):
                    if index:
                        clean(native_ws)
                    subprocess.run(native_argv, cwd=native_ws, capture_output=True)
                native_total = time.perf_counter_ns() - native_started

                # Fresh cache so the session really pays one cold run.
                session_cache = root / f"cache-session-{count}"
                shutil.rmtree(session_cache, ignore_errors=True)
                session_env = runner.cache_env(base_env, session_cache)
                clean(traced_ws)
                traced_started = time.perf_counter_ns()
                hits = 0
                for index in range(count):
                    if index:
                        clean(traced_ws)
                    _, sess_decision = runner.run_plain(
                        args.tracejit, argv, traced_ws, session_env, policy
                    )
                    if runner.is_hit(sess_decision):
                        hits += 1
                traced_total = time.perf_counter_ns() - traced_started
                measured_sessions.append({
                    "invocations": count,
                    "native_total_ns": native_total,
                    "tracejit_total_ns": traced_total,
                    "hits": hits,
                    "saving_ns": native_total - traced_total,
                    "saving_fraction": (native_total - traced_total) / native_total if native_total else None,
                })

        model = None
        if hit_ns:
            break_even = None
            if direct_ns > hit_ns:
                # n*direct > cold + (n-1)*hit  =>  n > (cold-hit)/(direct-hit)
                break_even = (cold_ns - hit_ns) / (direct_ns - hit_ns)
            model = {
                "direct_ns": direct_ns,
                "cold_ns": cold_ns,
                "hit_ns": hit_ns,
                "cold_over_direct": cold_ns / direct_ns if direct_ns else None,
                "hit_over_direct": hit_ns / direct_ns if direct_ns else None,
                "break_even_invocations": break_even,
                "cache_bytes": cache_size(cache),
            }
        results.append({
            "config": cfg.id, "family": cfg.family, "policy": policy,
            "cold_decision": (decision or {}).get("cache_decision"),
            "cold_reused": runner.is_hit(decision),
            "model": model, "sessions": measured_sessions,
            "direct_samples_ns": direct_samples, "hit_samples_ns": hit_samples,
        })
        shutil.rmtree(root, ignore_errors=True)
    return {"mode": "session", "rows": results,
            "reusable_configs": [row["config"] for row in reusable],
            "probed_configs": len(probe["rows"])}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["probe", "session"], default="probe")
    parser.add_argument("--tracejit", type=Path, default=runner.REPO / "target/release/tracejit")
    parser.add_argument("--scratch", type=Path, default=Path("/tmp/ac-noncompiler"))
    parser.add_argument("--vendor", type=Path, default=Path("/tmp/ac-vendor"))
    parser.add_argument("--probe-json", type=Path, default=HERE.parent / "results/phaseac/noncompiler_probe.json")
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--sessions", default="3,10,25")
    parser.add_argument("--reps", type=int, default=5)
    parser.add_argument("--only", default="", help="comma-separated config ids for --mode session")
    args = parser.parse_args(argv)

    if args.mode == "probe":
        payload = run_probe(args)
    else:
        probe = json.loads(args.probe_json.read_text())
        payload = run_session(args, probe)
    text = json.dumps(payload, indent=2, sort_keys=True)
    target = args.output or (
        HERE.parent / f"results/phaseac/noncompiler_{args.mode}.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text + "\n")
    if args.mode == "probe":
        for row in payload["rows"]:
            for policy, entry in row.get("policies", {}).items():
                print(f"{row['config']:32s} {policy:20s} {str(entry['classification']):9s} "
                      f"eligible={entry['eligible']} reused={entry['reused']} match={entry['warm_match']}")
    else:
        print(json.dumps({r["config"]: r["model"] for r in payload["rows"]}, indent=2)[:2000])
        print("reusable:", payload["reusable_configs"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
