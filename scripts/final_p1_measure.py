#!/usr/bin/env python3
"""TRA-27 / mandate §§6–10 measurement driver.

Produces raw artifacts under benchmarks/results/final_p1/ for the current HEAD.
Never invents timings: every number is measured on this host from the release binary.

Objectives covered:
  §6  tracing completeness samples (strace -c reference + TraceJIT effect counts)
  §8  compatibility census (≥25 workloads; separate census.py invocation preferred)
  §9  four e2e objectives (hit floor, throughput, session, concurrency)
  §10 admission-eval regret matrix

§7 is a design deliverable (docs), not a timing arm.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import platform
import shutil
import statistics
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BINARY = ROOT / "target" / "release" / "tracejit"


def close_fds_cmd(argv: list[str]) -> list[str]:
    inner = " ".join(f'"{a}"' if " " in a else a for a in argv)
    script = (
        "for e in /proc/self/fd/*; do f=${e##*/}; "
        'case "$f" in 0|1|2) ;; *) eval "exec ${f}>&-" 2>/dev/null || true ;; esac; '
        f"done; exec {inner}"
    )
    return ["bash", "-c", script]


def git_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def summarize(samples_ns: list[int]) -> dict[str, object]:
    if not samples_ns:
        return {"runs": 0}
    ordered = sorted(samples_ns)
    median = statistics.median(ordered)
    mean = statistics.mean(ordered)
    # Simple percentile bootstrap CI on the median (B=400), honest uncertainty.
    rng_seed = 0xC0FFEE
    boot = []
    n = len(ordered)
    state = rng_seed
    for _ in range(400):
        draw = []
        for _ in range(n):
            state = (1103515245 * state + 12345) & 0x7FFFFFFF
            draw.append(ordered[state % n])
        boot.append(statistics.median(draw))
    boot.sort()
    lo = boot[int(0.025 * (len(boot) - 1))]
    hi = boot[int(0.975 * (len(boot) - 1))]
    return {
        "runs": n,
        "median_ns": int(median),
        "mean_ns": int(mean),
        "p05_ns": ordered[max(0, math.ceil(0.05 * n) - 1)],
        "p95_ns": ordered[math.ceil(0.95 * n) - 1],
        "min_ns": ordered[0],
        "max_ns": ordered[-1],
        "stdev_ns": float(statistics.pstdev(ordered)),
        "median_bootstrap_95ci_ns": [int(lo), int(hi)],
        "samples_ns": samples_ns,
    }


def run_json(command: list[str], env: dict[str, str], cwd: Path | None = None) -> dict:
    completed = subprocess.run(
        close_fds_cmd(command),
        cwd=cwd or ROOT,
        env=env,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0 and not completed.stdout.strip():
        raise RuntimeError(
            f"command failed ({completed.returncode}): {command}\n"
            f"{completed.stderr.decode(errors='replace')}"
        )
    return json.loads(completed.stdout)


def base_env(cache: Path) -> dict[str, str]:
    return {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
        "GLIBC_TUNABLES": "glibc.malloc.tcache_count=0",
        "MALLOC_ARENA_MAX": "1",
        "TRACEJIT_CACHE_DIR": str(cache),
    }


def compile_etl() -> Path:
    workload = ROOT / "benchmarks/workloads/c-etl"
    binary = workload / "etl"
    subprocess.run(
        ["cc", "-O2", "-Wall", "-Wextra", "-o", str(binary), str(workload / "main.c")],
        cwd=ROOT,
        check=True,
    )
    return binary


def compile_transform() -> Path:
    workload = ROOT / "benchmarks/workloads/c-transform"
    binary = workload / "transform"
    src = workload / "main.c"
    if not src.is_file():
        # Fall back to large generated compile if transform missing.
        return compile_etl()
    subprocess.run(
        ["cc", "-O2", "-Wall", "-Wextra", "-o", str(binary), str(src)],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return binary


def measure_direct(argv: list[str], warmups: int, runs: int, env: dict[str, str]) -> dict:
    samples = []
    for i in range(warmups + runs):
        started = time.perf_counter_ns()
        subprocess.run(argv, env=env, cwd=ROOT, capture_output=True, check=True)
        elapsed = time.perf_counter_ns() - started
        if i >= warmups:
            samples.append(elapsed)
    return summarize(samples)


def measure_tracejit(
    argv: list[str],
    warmups: int,
    runs: int,
    mode: str,
    admission: str = "always",
) -> dict:
    """mode: cold | warm | auto-session"""
    samples = []
    kinds: dict[str, int] = {}
    decisions: dict[str, int] = {}
    last = None
    with tempfile.TemporaryDirectory(prefix="tj-p1-") as tmp:
        cache = Path(tmp) / "cache"
        env = base_env(cache)
        cmd = [str(BINARY), "run", "--json", "--admission", admission, "--", *argv]
        if mode == "warm":
            # Prime once.
            last = run_json(cmd, env)
            kinds[str(last.get("kind"))] = kinds.get(str(last.get("kind")), 0) + 1
            decisions[str(last.get("cache_decision"))] = (
                decisions.get(str(last.get("cache_decision")), 0) + 1
            )
        for i in range(warmups + runs):
            if mode == "cold":
                env = base_env(Path(tmp) / f"cold-{i}")
            started = time.perf_counter_ns()
            last = run_json(cmd, env)
            elapsed = time.perf_counter_ns() - started
            kinds[str(last.get("kind"))] = kinds.get(str(last.get("kind")), 0) + 1
            decisions[str(last.get("cache_decision"))] = (
                decisions.get(str(last.get("cache_decision")), 0) + 1
            )
            if i >= warmups:
                samples.append(elapsed)
    return {
        "timing": summarize(samples),
        "kind_counts": kinds,
        "cache_decision_counts": decisions,
        "last_report": {
            "kind": None if last is None else last.get("kind"),
            "cache_decision": None if last is None else last.get("cache_decision"),
            "classification": None if last is None else last.get("classification"),
            "eligible_for_reuse": None if last is None else last.get("eligible_for_reuse"),
            "dependency_count": None if last is None else last.get("dependency_count"),
            "output_count": None if last is None else last.get("output_count"),
            "process_count": None if last is None else last.get("process_count"),
            "effect_counts": None if last is None else last.get("effect_counts"),
            "decision_reason": None if last is None else last.get("decision_reason"),
        },
    }


def tracing_completeness(etl: Path) -> dict:
    """§6: complete-event baseline samples. Selective tracing is not enabled."""
    fixture = ROOT / "tests/fixtures/fixture_driver.c"
    cases = {
        "c-etl": [str(etl)],
        "plain_file_read": [
            str(ROOT / "target/release/fixture-driver")
            if (ROOT / "target/release/fixture-driver").is_file()
            else str(etl),
            "plain_file_read",
        ],
    }
    # Prefer fixture_driver when buildable.
    with tempfile.TemporaryDirectory(prefix="tj-trace-") as tmp:
        driver = Path(tmp) / "fixture-driver"
        built = subprocess.run(
            [
                "cc",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-pthread",
                str(fixture),
                "-o",
                str(driver),
            ],
            capture_output=True,
            check=False,
        )
        if built.returncode == 0:
            work = Path(tmp) / "work"
            work.mkdir()
            (work / "input.txt").write_text("final-p1 plain file\n", encoding="utf-8")
            cases["plain_file_read"] = [str(driver), "plain_file_read", str(work)]

        out: dict[str, object] = {
            "method": (
                "Reference: strace -c counts (host). TraceJIT: JSON effect/process counts "
                "from a single cold traced run. Selective seccomp-BPF tracing is NOT enabled; "
                "complete-event coverage remains the production obligation."
            ),
            "cases": {},
        }
        for name, argv in cases.items():
            entry: dict[str, object] = {"argv": argv}
            # strace reference (measurement adjunct only); optional on minimal images.
            if shutil.which("strace") is None:
                entry["strace_available"] = False
                entry["strace_summary"] = "strace not installed on this host"
            else:
                strace = subprocess.run(
                    ["strace", "-c", "-f", "--", *argv],
                    cwd=ROOT,
                    capture_output=True,
                    check=False,
                    text=True,
                )
                entry["strace_available"] = strace.returncode == 0 or bool(strace.stderr)
                entry["strace_summary"] = (strace.stderr or strace.stdout)[-4000:]
            cache = Path(tmp) / f"cache-{name}"
            report = run_json(
                [str(BINARY), "run", "--json", "--", *argv],
                base_env(cache),
            )
            entry["tracejit"] = {
                "kind": report.get("kind"),
                "classification": report.get("classification"),
                "eligible_for_reuse": report.get("eligible_for_reuse"),
                "process_count": report.get("process_count"),
                "dependency_count": report.get("dependency_count"),
                "output_count": report.get("output_count"),
                "effect_counts": report.get("effect_counts"),
                "reasons": report.get("reasons"),
            }
            out["cases"][name] = entry
        out["selective_tracing"] = {
            "status": "deferred",
            "reason": (
                "Complete-event coverage proof obligation is not yet discharged for a "
                "filtered syscall set; production remains ptrace-all stops."
            ),
        }
        return out


def objective_hit_floor(etl: Path, warmups: int, runs: int) -> dict:
    with tempfile.TemporaryDirectory(prefix="tj-floor-") as tmp:
        driver = Path(tmp) / "fixture-driver"
        subprocess.run(
            [
                "cc",
                "-O2",
                "-Wall",
                "-Wextra",
                "-Werror",
                "-pthread",
                str(ROOT / "tests/fixtures/fixture_driver.c"),
                "-o",
                str(driver),
            ],
            check=True,
            capture_output=True,
        )
        work = Path(tmp) / "work"
        work.mkdir()
        (work / "input.txt").write_text("final-p1 plain file\n", encoding="utf-8")
        argv = [str(driver), "plain_file_read", str(work)]
        direct_env = {
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", "/tmp"),
            "LC_ALL": "C",
            "LANG": "C",
            "TZ": "UTC",
        }
        return {
            "shape": "plain_file_read",
            "direct": measure_direct(argv, warmups, runs, direct_env),
            "cold_trace": measure_tracejit(argv, warmups, runs, "cold"),
            "warm_hit": measure_tracejit(argv, warmups, runs, "warm"),
            "auto": measure_tracejit(argv, warmups, runs, "warm", admission="auto"),
        }


def objective_throughput(transform: Path, warmups: int, runs: int) -> dict:
    argv = [str(transform)]
    direct_env = {
        "PATH": os.environ["PATH"],
        "HOME": os.environ.get("HOME", "/tmp"),
        "LC_ALL": "C",
        "LANG": "C",
        "TZ": "UTC",
    }
    return {
        "shape": "c-transform-or-etl",
        "binary": str(transform),
        "direct": measure_direct(argv, warmups, runs, direct_env),
        "cold_trace": measure_tracejit(argv, warmups, runs, "cold"),
        "warm_hit": measure_tracejit(argv, warmups, runs, "warm"),
        "auto": measure_tracejit(argv, warmups, runs, "warm", admission="auto"),
    }


def objective_session(etl: Path, warmups: int, runs: int) -> dict:
    """Developer-session savings: interleaved miss/hit/deopt stream, cumulative wall."""
    argv = [str(etl)]
    with tempfile.TemporaryDirectory(prefix="tj-session-") as tmp:
        cache = Path(tmp) / "cache"
        env = base_env(cache)
        # Mutate input between blocks if the workload has one; c-etl uses fixed paths.
        timeline = []
        cumulative = 0
        # Sequence: cold, warm×N, always, auto×N
        plan = [("always", "cold")] + [("always", "warm")] * runs + [("auto", "warm")] * runs
        for admission, _ in plan:
            cmd = [str(BINARY), "run", "--json", "--admission", admission, "--", *argv]
            started = time.perf_counter_ns()
            report = run_json(cmd, env)
            elapsed = time.perf_counter_ns() - started
            cumulative += elapsed
            timeline.append(
                {
                    "admission": admission,
                    "kind": report.get("kind"),
                    "cache_decision": report.get("cache_decision"),
                    "elapsed_ns": elapsed,
                }
            )
        # Direct cumulative for same count
        direct_env = {
            "PATH": os.environ["PATH"],
            "HOME": os.environ.get("HOME", "/tmp"),
            "LC_ALL": "C",
            "LANG": "C",
            "TZ": "UTC",
        }
        direct_cumulative = 0
        for _ in plan:
            started = time.perf_counter_ns()
            subprocess.run(argv, env=direct_env, cwd=ROOT, capture_output=True, check=True)
            direct_cumulative += time.perf_counter_ns() - started
        kind_counts: dict[str, int] = {}
        decision_counts: dict[str, int] = {}
        for row in timeline:
            kind_counts[str(row["kind"])] = kind_counts.get(str(row["kind"]), 0) + 1
            decision_counts[str(row["cache_decision"])] = (
                decision_counts.get(str(row["cache_decision"]), 0) + 1
            )
        return {
            "plan_length": len(plan),
            "tracejit_cumulative_ns": cumulative,
            "direct_cumulative_ns": direct_cumulative,
            "kind_counts": kind_counts,
            "cache_decision_counts": decision_counts,
            "timeline": timeline,
        }


def objective_concurrency(etl: Path, workers: int = 8) -> dict:
    argv = [str(etl)]
    with tempfile.TemporaryDirectory(prefix="tj-conc-") as tmp:
        cache = Path(tmp) / "cache"
        env = base_env(cache)
        # Prime
        run_json([str(BINARY), "run", "--json", "--", *argv], env)
        # Concurrent warm hits
        procs = []
        started = time.perf_counter_ns()
        for _ in range(workers):
            procs.append(
                subprocess.Popen(
                    close_fds_cmd([str(BINARY), "run", "--json", "--", *argv]),
                    cwd=ROOT,
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
            )
        results = []
        for proc in procs:
            out, err = proc.communicate()
            report = json.loads(out) if out.strip() else {"error": err.decode(errors="replace")}
            results.append(
                {
                    "returncode": proc.returncode,
                    "kind": report.get("kind"),
                    "cache_decision": report.get("cache_decision"),
                    "exit_code": report.get("exit_code"),
                }
            )
        wall = time.perf_counter_ns() - started
        kind_counts: dict[str, int] = {}
        for row in results:
            kind_counts[str(row.get("kind"))] = kind_counts.get(str(row.get("kind")), 0) + 1
        return {
            "workers": workers,
            "wall_ns": wall,
            "kind_counts": kind_counts,
            "all_success": all(r["returncode"] == 0 for r in results),
            "results": results,
        }


def admission_eval(output_dir: Path) -> dict:
    completed = subprocess.run(
        [str(BINARY), "admission-eval"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    text = completed.stdout + completed.stderr
    (output_dir / "admission-eval.txt").write_text(text, encoding="utf-8")
    # Prefer JSON if the tool emits it on a known path; else parse RESULT lines.
    parsed_lines = [line for line in text.splitlines() if line.startswith("policy ") or line.startswith("RESULT ")]
    return {
        "returncode": completed.returncode,
        "result_lines": parsed_lines,
        "raw_path": str(output_dir / "admission-eval.txt"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", default=str(ROOT / "benchmarks/results/final_p1"))
    parser.add_argument("--warmups", type=int, default=5)
    parser.add_argument("--runs", type=int, default=30)
    parser.add_argument("--skip-admission", action="store_true")
    args = parser.parse_args()

    if not BINARY.is_file():
        raise SystemExit(f"missing release binary: {BINARY} (cargo build -p tracejit-cli --release)")

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    etl = compile_etl()
    transform = compile_transform()

    print("§6 tracing completeness…", flush=True)
    tracing = tracing_completeness(etl)
    (output_dir / "tracing_completeness.json").write_text(
        json.dumps(tracing, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print("§9 objective 1 hit floor…", flush=True)
    hit_floor = objective_hit_floor(etl, args.warmups, args.runs)
    print("§9 objective 2 throughput…", flush=True)
    throughput = objective_throughput(transform, args.warmups, args.runs)
    print("§9 objective 3 session…", flush=True)
    session = objective_session(etl, args.warmups, max(args.runs // 2, 10))
    print("§9 objective 4 concurrency…", flush=True)
    concurrency = objective_concurrency(etl)

    admission = None
    if not args.skip_admission:
        print("§10 admission-eval…", flush=True)
        admission = admission_eval(output_dir)

    # Aggregate HIT/DEOPT/EXECUTED across measured arms.
    def accumulate(dst: dict[str, int], src: dict[str, int] | None) -> None:
        if not src:
            return
        for key, value in src.items():
            dst[key] = dst.get(key, 0) + int(value)

    kind_totals: dict[str, int] = {}
    decision_totals: dict[str, int] = {}
    for arm in (hit_floor, throughput):
        for key in ("cold_trace", "warm_hit", "auto"):
            accumulate(kind_totals, arm[key].get("kind_counts"))
            accumulate(decision_totals, arm[key].get("cache_decision_counts"))
    accumulate(kind_totals, session.get("kind_counts"))
    accumulate(decision_totals, session.get("cache_decision_counts"))
    accumulate(kind_totals, concurrency.get("kind_counts"))

    payload = {
        "commit": git_sha(),
        "generated_unix_ms": int(time.time() * 1000),
        "host": {
            "uname": platform.uname()._asdict(),
            "python": platform.python_version(),
            "cpus": os.cpu_count(),
        },
        "protocol": {
            "warmups": args.warmups,
            "runs": args.runs,
            "bootstrap_median_ci": "400 resamples, 95%",
            "release_binary": str(BINARY),
        },
        "section6_tracing": "tracing_completeness.json",
        "section9": {
            "hit_floor": hit_floor,
            "throughput": throughput,
            "session": session,
            "concurrency": concurrency,
        },
        "section10_admission": admission,
        "aggregate_counts": {
            "kind_counts": kind_totals,
            "cache_decision_counts": decision_totals,
        },
        "competitors_not_re_run_here": {
            "note": (
                "Make/Ninja/ccache competitive arms were measured on tip 364331b in "
                "benchmarks/results/phase_k8/; this package re-measures TraceJIT DIRECT/"
                "cold/warm/AUTO on the current tip. Missing tools are not scored as losses."
            ),
            "prior_raw": "benchmarks/results/phase_k8/competitive.json",
        },
    }
    (output_dir / "e2e.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # Compact markdown summary (numbers only from payload).
    def ms(summary: dict) -> str:
        if not summary or "median_ns" not in summary:
            return "n/a"
        lo, hi = summary.get("median_bootstrap_95ci_ns", [None, None])
        return (
            f"{summary['median_ns'] / 1e6:.3f} ms "
            f"(95% CI {lo / 1e6:.3f}–{hi / 1e6:.3f}, n={summary['runs']})"
        )

    lines = [
        f"# Final P1 e2e measurements",
        "",
        f"Commit: `{payload['commit']}`",
        "",
        "## Aggregate kind / decision counts",
        "",
        f"- kind_counts: `{json.dumps(kind_totals, sort_keys=True)}`",
        f"- cache_decision_counts: `{json.dumps(decision_totals, sort_keys=True)}`",
        "",
        "## Hit floor (`plain_file_read`)",
        "",
        f"- DIRECT: {ms(hit_floor['direct'])}",
        f"- cold: {ms(hit_floor['cold_trace']['timing'])}",
        f"- warm: {ms(hit_floor['warm_hit']['timing'])}",
        f"- auto: {ms(hit_floor['auto']['timing'])}",
        "",
        "## Throughput",
        "",
        f"- binary: `{throughput['binary']}`",
        f"- DIRECT: {ms(throughput['direct'])}",
        f"- cold: {ms(throughput['cold_trace']['timing'])}",
        f"- warm: {ms(throughput['warm_hit']['timing'])}",
        f"- auto: {ms(throughput['auto']['timing'])}",
        "",
        "## Session cumulative",
        "",
        f"- TraceJIT cumulative: {session['tracejit_cumulative_ns'] / 1e6:.3f} ms",
        f"- DIRECT cumulative: {session['direct_cumulative_ns'] / 1e6:.3f} ms",
        f"- kinds: `{json.dumps(session['kind_counts'], sort_keys=True)}`",
        "",
        "## Concurrency",
        "",
        f"- workers={concurrency['workers']} wall={concurrency['wall_ns'] / 1e6:.3f} ms "
        f"all_success={concurrency['all_success']} kinds=`{json.dumps(concurrency['kind_counts'], sort_keys=True)}`",
        "",
        "## Admission",
        "",
    ]
    if admission:
        lines.extend(f"- {line}" for line in admission.get("result_lines") or [])
    else:
        lines.append("- skipped")
    lines.append("")
    (output_dir / "e2e.md").write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps(payload["aggregate_counts"], indent=2, sort_keys=True))
    print(f"wrote {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
