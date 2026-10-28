#!/usr/bin/env python3
"""Real-world compatibility census for TraceJIT.

This is not a speed benchmark. It measures how far TraceJIT V1 gets on
recognizable developer workloads: what it classifies, what it refuses, and why.

Method per workload:

1. probe the tools the workload needs; a missing tool is recorded separately from
   a TraceJIT refusal and never counted as a refusal;
2. materialize the workload in a scratch directory outside the repository;
3. run the command directly and record exit status, streams, and output hashes;
4. run it under TraceJIT with a fresh cache and record the classification, the
   dependency and effect counts, and every refusal reason;
5. when TraceJIT reports the workload as eligible, take a real cache hit and
   compare its observable result with the direct run.

Nothing here mutates the repository, and no workload is tuned to make TraceJIT
pass. Eligibility is reported, never engineered.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import re
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKLOAD_DIR = Path(__file__).resolve().parent / "workloads"

UNMODELED_SYSCALL = re.compile(r"unmodeled (?:successful |failed )?syscall (\d+)")

# Categories are derived only from text TraceJIT itself emitted. They are a
# reporting convenience, not a classifier.
REASON_CATEGORIES = [
    ("access_check", "successful access() check cannot be guarded exactly"),
    ("procfs_process_relative", "process-relative procfs path dependency"),
    ("unclassified_fd", "I/O on a descriptor the tracer could not classify"),
    ("unhashable_open", "opened dependency cannot be hashed or guarded"),
    ("directory_output", "output is not a restorable regular file"),
    ("randomness", "observed randomness"),
    ("process_identity", "observed process identity"),
    ("clock", "observed clock read"),
    ("network", "observed network effect"),
    ("signal", "observed signal"),
    ("system_information", "observed mutable system information"),
]


def now_ns() -> int:
    return time.perf_counter_ns()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def percentile_95(values: list[int]) -> int:
    return sorted(values)[math.ceil(len(values) * 0.95) - 1]


def summarize(values: list[int]) -> dict[str, object]:
    return {
        "runs": len(values),
        "median_ns": int(statistics.median(values)),
        "p95_ns": percentile_95(values),
        "minimum_ns": min(values),
        "maximum_ns": max(values),
        "samples_ns": values,
    }


def categorize(reason: str) -> str:
    lowered = reason.lower()
    match = UNMODELED_SYSCALL.search(reason)
    if match:
        return f"unmodeled_syscall:{match.group(1)}"
    for name, needle in REASON_CATEGORIES:
        if needle in lowered:
            return name
    return f"other:{reason[:60]}"


def syscall_table() -> dict[int, str]:
    """Best-effort x86_64 syscall number to name map for this host.

    The names are only reported when the host actually ships the kernel header.
    A number without a confirmed name is still reported, as a number.
    """
    for candidate in (
        "/usr/include/x86_64-linux-gnu/asm/unistd_64.h",
        "/usr/include/asm/unistd_64.h",
        "/usr/include/asm-generic/unistd.h",
    ):
        path = Path(candidate)
        if not path.is_file():
            continue
        table: dict[int, str] = {}
        pattern = re.compile(r"#define\s+__NR_(\w+)\s+(\d+)")
        for line in path.read_text(errors="replace").splitlines():
            match = pattern.search(line)
            if match:
                table[int(match.group(2))] = match.group(1)
        if table:
            return table
    return {}


def tool_path(tool: str) -> str | None:
    return shutil.which(tool)


class Workload:
    def __init__(
        self,
        name: str,
        category: str,
        requires: list[str],
        note: str,
        command,
        cwd: str = "repo",
        env: dict[str, str] | None = None,
        outputs=(),
    ) -> None:
        self.name = name
        self.category = category
        self.requires = requires
        self.note = note
        self.command_factory = command
        self.cwd_kind = cwd
        self.env = env or {}
        self.output_names = list(outputs)


def setup_scratch(scratch: Path) -> dict[str, Path]:
    """Writes every generated fixture for the census into the scratch directory."""
    scratch.mkdir(parents=True, exist_ok=True)
    sales = scratch / "sales.csv"
    customers = scratch / "customers.csv"
    sales.write_text(
        "sale_id,customer_id,amount_cents\n"
        + "".join(f"s{index:04d},c{index % 12:03d},{(index * 37) % 5000}\n" for index in range(1, 401)),
        encoding="utf-8",
    )
    customers.write_text(
        "customer_id,region\n"
        + "".join(
            f"c{index:03d},{['north', 'south', 'east', 'west'][index % 4]}\n"
            for index in range(12)
        ),
        encoding="utf-8",
    )
    numbers = scratch / "numbers.txt"
    numbers.write_text("".join(f"{(index * 7919) % 100003}\n" for index in range(1, 501)), encoding="utf-8")
    schema = scratch / "schema.tsv"
    schema.write_text(
        "id\tkind\tname\n"
        + "".join(f"{index}\tFIELD_{'u32' if index % 2 else 'u64'}\tvalue_{index}\n" for index in range(24)),
        encoding="utf-8",
    )
    markdown = scratch / "notes.md"
    markdown.write_text(
        "# TraceJIT census\n\n"
        + "".join(f"- item {index}: deterministic documentation line\n" for index in range(60)),
        encoding="utf-8",
    )
    manpage = scratch / "census.1"
    manpage.write_text(
        ".TH CENSUS 1\n.SH NAME\ncensus \\- documentation conversion fixture\n"
        ".SH DESCRIPTION\n"
        + "".join(f"Paragraph {index} describes a deterministic conversion input.\n" for index in range(40)),
        encoding="utf-8",
    )
    source = scratch / "source.c"
    source.write_text(
        "#include <stdint.h>\n"
        + "".join(
            f"static uint64_t step_{index}(uint64_t value) {{ return value * 1315423911ull + {index}; }}\n"
            for index in range(300)
        )
        + "int main(void) { uint64_t value = 1;\n"
        + "".join(f"    value = step_{index}(value);\n" for index in range(300))
        + "    return (int)(value >> 60); }\n",
        encoding="utf-8",
    )
    try:
        from PIL import Image  # type: ignore

        image = Image.new("RGB", (192, 128))
        pixels = image.load()
        for x in range(192):
            for y in range(128):
                pixels[x, y] = ((x * 3) % 256, (y * 5) % 256, ((x + y) * 7) % 256)
        image.save(scratch / "source.png", format="PNG", optimize=False)
    except Exception:  # pragma: no cover - recorded as a missing tool instead
        pass
    return {
        "sales": sales,
        "customers": customers,
        "numbers": numbers,
        "schema": schema,
        "markdown": markdown,
        "manpage": manpage,
        "source": source,
        "png": scratch / "source.png",
    }


def workloads(fixture_source: Path) -> list[Workload]:
    def python_csv(scratch: Path, data: dict[str, Path]) -> list[str]:
        return [sys.executable, str(WORKLOAD_DIR / "etl.py"), str(data["sales"]), str(data["customers"]), str(scratch / "report.json")]

    def shell_pipeline(scratch: Path, data: dict[str, Path]) -> list[str]:
        return [
            "sh",
            "-c",
            f"awk '{{ digest = (digest * 1315423911 + $1) % 4294967296 }} END {{ printf \"%08x\\n\", digest }}' "
            f"{data['numbers']} | sort | uniq -c | awk '{{ print $2 }}' > {scratch / 'pipeline.out'}",
        ]

    def codegen(scratch: Path, data: dict[str, Path]) -> list[str]:
        return [
            "sh",
            "-c",
            f"awk -f {WORKLOAD_DIR / 'codegen.awk'} {data['schema']} > {scratch / 'generated.h'}",
        ]

    def compile_object(scratch: Path, _data) -> list[str]:
        return ["cc", "-O2", "-Wall", "-Wextra", "-c", str(fixture_source), "-o", str(scratch / "fixture.o")]

    def compile_large(scratch: Path, data: dict[str, Path]) -> list[str]:
        return ["cc", "-O2", "-Wall", "-Wextra", "-c", str(data["source"]), "-o", str(scratch / "source.o")]

    def docs(scratch: Path, data: dict[str, Path]) -> list[str]:
        return ["sh", "-c", f"groff -Thtml -man {data['manpage']} > {scratch / 'census.html'}"]

    def image(scratch: Path, data: dict[str, Path]) -> list[str]:
        return [sys.executable, str(WORKLOAD_DIR / "image_transform.py"), str(data["png"]), str(scratch / "transformed.png")]

    def lint(scratch: Path, _data) -> list[str]:
        return ["cc", "-fsyntax-only", "-Wall", "-Wextra", "-Werror", str(fixture_source)]

    return [
        Workload(
            "cc-compile-fixture",
            "compiler",
            ["cc"],
            "Compiles the repository's own adversarial C fixture with the system compiler.",
            compile_object,
            outputs=["fixture.o"],
        ),
        Workload(
            "cc-compile-large",
            "compiler",
            ["cc"],
            "Compiles a generated 300-function C translation unit: a real whole-file compile, not a busy loop.",
            compile_large,
            outputs=["source.o"],
        ),
        Workload(
            "shell-pipeline",
            "shell",
            ["sh", "awk", "sort", "uniq"],
            "Deterministic awk | sort | uniq -c kernel pipeline over a generated integer list.",
            shell_pipeline,
            outputs=["pipeline.out"],
        ),
        Workload(
            "python-csv-json",
            "python",
            [sys.executable],
            "CPython CSV to JSON aggregation with PYTHONHASHSEED unset (interpreter defaults).",
            python_csv,
            outputs=["report.json"],
        ),
        Workload(
            "python-csv-json-seeded",
            "python",
            [sys.executable],
            "Same CPython workload with PYTHONHASHSEED=0 and PYTHONDONTWRITEBYTECODE=1.",
            python_csv,
            env={"PYTHONHASHSEED": "0", "PYTHONDONTWRITEBYTECODE": "1"},
            outputs=["report.json"],
        ),
        Workload(
            "awk-codegen",
            "codegen",
            ["awk", "sh"],
            "Generates a C header from a TSV schema with awk, the code-generation tool available here.",
            codegen,
            outputs=["generated.h"],
        ),
        Workload(
            "groff-manpage-html",
            "documentation",
            ["groff", "sh"],
            "Converts a troff man page to HTML with groff, the documentation converter available here.",
            docs,
            outputs=["census.html"],
        ),
        Workload(
            "pil-image-transform",
            "image",
            [sys.executable],
            "Grayscale plus posterize plus resize of a generated PNG with Pillow.",
            image,
            outputs=["transformed.png"],
        ),
        Workload(
            "cc-syntax-only-lint",
            "lint",
            ["cc"],
            "Compiler front-end lint pass (cc -fsyntax-only -Wall -Wextra -Werror) over the C fixture.",
            lint,
        ),
    ]


def run_command(command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True, check=False)


def timed(command: list[str], cwd: Path, env: dict[str, str]) -> tuple[int, subprocess.CompletedProcess[bytes]]:
    started = now_ns()
    completed = run_command(command, cwd, env)
    return now_ns() - started, completed


def observe(completed: subprocess.CompletedProcess[bytes], outputs: list[Path]) -> dict[str, object]:
    present = {}
    for path in outputs:
        present[str(path)] = sha256_file(path) if path.is_file() else None
    return {
        "exit_status": completed.returncode,
        "stdout_sha256": sha256_bytes(completed.stdout),
        "stderr_sha256": sha256_bytes(completed.stderr),
        "outputs": present,
    }


def base_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GLIBC_TUNABLES"] = "glibc.malloc.tcache_count=0"
    env["MALLOC_ARENA_MAX"] = "1"
    return env


def tracejit_json(tracejit: Path, command: list[str], cwd: Path, env: dict[str, str]) -> tuple[dict[str, object], subprocess.CompletedProcess[bytes]]:
    completed = run_command(
        [str(tracejit), "run", "--json", "--", *command],
        cwd,
        env,
    )
    if completed.returncode != 0 and not completed.stdout.strip():
        raise RuntimeError(
            f"tracejit failed for {' '.join(command)} ({completed.returncode}):\n"
            f"{completed.stderr.decode(errors='replace')}"
        )
    try:
        report = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(
            f"tracejit did not emit JSON for {' '.join(command)}: {error}\n"
            f"stdout:\n{completed.stdout.decode(errors='replace')}\n"
            f"stderr:\n{completed.stderr.decode(errors='replace')}"
        ) from error
    return report, completed


def arm_env(env: dict[str, str], cache: Path) -> dict[str, str]:
    return env | {"TRACEJIT_CACHE_DIR": str(cache)}


def census_workload(
    workload: Workload,
    tracejit: Path,
    scratch_root: Path,
    runs: int,
    warmups: int,
    table: dict[int, str],
) -> dict[str, object]:
    missing = [tool for tool in workload.requires if tool_path(tool) is None]
    record: dict[str, object] = {
        "name": workload.name,
        "category": workload.category,
        "note": workload.note,
        "required_tools": workload.requires,
    }
    if missing:
        record["status"] = "blocked_missing_tool"
        record["missing_tools"] = missing
        return record

    scratch = scratch_root / workload.name
    scratch.mkdir(parents=True, exist_ok=True)
    data = setup_scratch(scratch)
    command = workload.command_factory(scratch, data)
    cwd = ROOT if workload.cwd_kind == "repo" else scratch
    outputs = [scratch / name for name in workload.output_names]
    for path in outputs:
        path.unlink(missing_ok=True)

    env = base_env() | workload.env
    record["command"] = command
    record["cwd"] = str(cwd)

    direct_samples: list[int] = []
    direct = None
    for index in range(warmups + runs):
        elapsed, completed = timed(command, cwd, env)
        if index == warmups:
            direct = completed
        if index >= warmups:
            direct_samples.append(elapsed)
    if direct is None or direct.returncode != 0:
        record["status"] = "workload_failed"
        record["exit_status"] = None if direct is None else direct.returncode
        record["stderr"] = "" if direct is None else direct.stderr.decode(errors="replace")[:2000]
        return record
    direct_observation = observe(direct, outputs)
    record["direct"] = summarize(direct_samples)
    record["direct_observation"] = direct_observation

    cold_samples: list[int] = []
    report = None
    for index in range(warmups + runs):
        # A fresh cache per sample, so every traced sample is a real cold miss.
        cold_env = arm_env(env, scratch / f"cold-{index}")
        started = now_ns()
        report, _ = tracejit_json(tracejit, command, cwd, cold_env)
        elapsed = now_ns() - started
        if index >= warmups:
            cold_samples.append(elapsed)
    assert report is not None
    record["classification"] = report.get("classification")
    record["eligible_for_reuse"] = report.get("eligible_for_reuse")
    record["reasons"] = report.get("reasons")
    record["dependency_count"] = report.get("dependency_count")
    record["output_count"] = report.get("output_count")
    record["effect_counts"] = report.get("effect_counts")
    record["process_count"] = report.get("process_count")
    record["tracejit_exit_status"] = report.get("exit_code")
    record["traced_cold"] = summarize(cold_samples)

    cold_stdout = bytes(report.get("stdout_bytes") or [])
    cold_stderr = bytes(report.get("stderr_bytes") or [])
    cold_observation = observe(
        subprocess.CompletedProcess(command, int(report.get("exit_code") or 0), cold_stdout, cold_stderr),
        outputs,
    )
    record["traced_observation"] = cold_observation

    if not report.get("eligible_for_reuse"):
        record["status"] = "refused"
        record["hit_obtained"] = False
        record["blockers"] = sorted({categorize(reason) for reason in (report.get("reasons") or [])})
        record["unsupported_syscalls"] = sorted(
            {
                int(match.group(1))
                for reason in (report.get("reasons") or [])
                for match in [UNMODELED_SYSCALL.search(reason)]
                if match
            }
        )
        record["unsupported_syscall_names"] = [
            f"{number}: {table.get(number, 'name not confirmed on this host')}"
            for number in record["unsupported_syscalls"]
        ]
        record["output_equivalence"] = (
            "PASS" if cold_observation == direct_observation else "FAIL"
        )
        return record

    hit_root = scratch / "hit"
    hit_env = arm_env(env, hit_root)
    primed, _ = tracejit_json(tracejit, command, cwd, hit_env)
    if primed.get("kind") != "Executed":
        record["status"] = "unexpected_prime_result"
        record["prime_kind"] = primed.get("kind")
        return record
    hit_samples: list[int] = []
    hit_report = None
    for index in range(warmups + runs):
        elapsed, completed = timed([str(tracejit), "run", "--json", "--", *command], cwd, hit_env)
        hit_report = json.loads(completed.stdout)
        if hit_report.get("kind") != "Reused":
            record["status"] = "reuse_was_not_obtained"
            record["hit_kind"] = hit_report.get("kind")
            record["hit_decision"] = hit_report.get("cache_decision")
            record["hit_reason"] = hit_report.get("decision_reason")
            return record
        if index >= warmups:
            hit_samples.append(elapsed)
    assert hit_report is not None
    hit_observation = observe(
        subprocess.CompletedProcess(
            command,
            int(hit_report.get("exit_code") or 0),
            bytes(hit_report.get("stdout_bytes") or []),
            bytes(hit_report.get("stderr_bytes") or []),
        ),
        outputs,
    )
    record["hit_obtained"] = True
    record["cache_hit"] = summarize(hit_samples)
    record["hit_observation"] = hit_observation
    record["speedup"] = int(record["direct"]["median_ns"]) / int(record["cache_hit"]["median_ns"])  # type: ignore[index]
    record["time_saved_ns"] = int(record["direct"]["median_ns"]) - int(record["cache_hit"]["median_ns"])  # type: ignore[index]
    record["status"] = "reused"
    record["blockers"] = []
    record["unsupported_syscalls"] = []
    record["unsupported_syscall_names"] = []
    equivalent = cold_observation == direct_observation and hit_observation == direct_observation
    record["output_equivalence"] = "PASS" if equivalent else "FAIL"
    return record


def environment() -> dict[str, object]:
    def text(command: list[str]) -> str:
        completed = subprocess.run(command, cwd=ROOT, text=True, capture_output=True, check=False)
        return (completed.stdout + completed.stderr).strip()

    return {
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "uname": text(["uname", "-a"]),
        "os_release": text(["cat", "/etc/os-release"]),
        "cpu": text(["lscpu"]),
        "memory": text(["free", "-h"]),
        "filesystem": text(["df", "-T", "."]),
        "python": text([sys.executable, "--version"]),
        "commit": text(["git", "rev-parse", "HEAD"]),
        "working_tree_dirty": bool(text(["git", "status", "--porcelain"])),
    }


def aggregate(records: list[dict[str, object]]) -> dict[str, object]:
    attempted = [record for record in records if record["status"] != "blocked_missing_tool"]
    eligible = [record for record in attempted if record.get("hit_obtained")]
    blocked = [record for record in attempted if record["status"] in ("refused", "workload_failed")]

    syscall_histogram: dict[str, dict[str, object]] = {}
    category_histogram: dict[str, list[str]] = {}
    for record in blocked:
        for number, name in zip(record.get("unsupported_syscalls") or [], record.get("unsupported_syscall_names") or []):
            entry = syscall_histogram.setdefault(str(number), {"number": number, "name": name, "workloads": []})
            entry["workloads"].append(record["name"])
        for blocker in record.get("blockers") or []:
            if blocker.startswith("unmodeled_syscall"):
                continue
            category_histogram.setdefault(blocker, []).append(record["name"])

    ranking = sorted(
        (
            {
                "blocker": blocker,
                "workloads": sorted(set(names)),
                "count": len(set(names)),
            }
            for blocker, names in category_histogram.items()
        ),
        key=lambda entry: (-entry["count"], entry["blocker"]),
    )
    syscall_ranking = sorted(
        (
            {
                "syscall": entry["number"],
                "name": entry["name"],
                "workloads": sorted(set(entry["workloads"])),
                "count": len(set(entry["workloads"])),
            }
            for entry in syscall_histogram.values()
        ),
        key=lambda entry: (-entry["count"], str(entry["syscall"])),
    )
    return {
        "denominator_definition": (
            "attempted = every requested workload whose required tools were present and whose "
            "direct execution succeeded. Tool-missing and workload-failed entries are excluded "
            "from the rate and listed separately."
        ),
        "requested": len(records),
        "attempted": len(attempted),
        "reused": len(eligible),
        "refused": len([record for record in attempted if record["status"] == "refused"]),
        "workload_failed": len([record for record in attempted if record["status"] == "workload_failed"]),
        "blocked_missing_tool": len(records) - len(attempted),
        "eligibility_rate": (len(eligible) / len(attempted)) if attempted else None,
        "blocker_ranking": ranking,
        "unmodeled_syscall_ranking": syscall_ranking,
    }


def markdown(result: dict[str, object]) -> str:
    lines = [
        "# TraceJIT real-world compatibility census",
        "",
        f"Commit: `{result['environment']['commit']}`",
        f" (working tree dirty: `{result['environment']['working_tree_dirty']}`)",
        "",
        "Every number below came from this host in this run. Refusals are reported, not excluded.",
        "",
        "## Eligibility",
        "",
        f"- Requested workloads: {result['aggregate']['requested']}",
        f"- Attempted: {result['aggregate']['attempted']}",
        f"- Reused with a verified cache hit: {result['aggregate']['reused']}",
        f"- Refused by TraceJIT: {result['aggregate']['refused']}",
        f"- Failed to execute: {result['aggregate']['workload_failed']}",
        f"- Blocked on a missing tool: {result['aggregate']['blocked_missing_tool']}",
    ]
    rate = result["aggregate"]["eligibility_rate"]
    lines.append(f"- Eligibility rate: {rate:.3f}" if rate is not None else "- Eligibility rate: n/a")
    lines.extend(
        [
            "",
            result["aggregate"]["denominator_definition"],
            "",
            "## Workloads",
            "",
            "| Workload | Category | Status | Classification | Deps | Outputs | Direct median | Cache-hit median | Speedup | Equivalence |",
            "| --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
        ]
    )
    for record in result["workloads"]:
        status = record["status"]
        if status == "blocked_missing_tool":
            lines.append(
                f"| `{record['name']}` | {record['category']} | blocked: missing {', '.join(record['missing_tools'])} | - | - | - | - | - | - | - |"
            )
            continue
        direct = record.get("direct")
        hit = record.get("cache_hit")
        speedup = record.get("speedup")
        lines.append(
            " | ".join(
                [
                    "",
                    f"`{record['name']}`",
                    record["category"],
                    status,
                    str(record.get("classification", "-")),
                    str(record.get("dependency_count", "-")),
                    str(record.get("output_count", "-")),
                    f"{direct['median_ns'] / 1_000_000:.3f} ms" if direct else "-",
                    f"{hit['median_ns'] / 1_000_000:.3f} ms" if hit else "-",
                    f"{speedup:.3f}x" if speedup else "-",
                    str(record.get("output_equivalence", "-")),
                    "",
                ]
            ).strip()
        )
    lines.extend(["", "## Blocker ranking", "", "| Blocker | Workloads blocked |", "| --- | ---: |"])
    for entry in result["aggregate"]["blocker_ranking"]:
        lines.append(f"| {entry['blocker']} | {entry['count']} |")
    lines.extend(["", "### Unmodeled syscalls", "", "| Syscall | Name | Workloads blocked |", "| ---: | --- | ---: |"])
    for entry in result["aggregate"]["unmodeled_syscall_ranking"]:
        lines.append(f"| {entry['syscall']} | {entry['name']} | {entry['count']} |")
    lines.extend(["", "## Refusal detail", ""])
    for record in result["workloads"]:
        if record["status"] in ("refused", "workload_failed", "unexpected_prime_result", "reuse_was_not_obtained"):
            lines.append(f"### `{record['name']}` ({record['status']})")
            lines.append("")
            if record.get("command"):
                lines.append(f"Command: `{' '.join(record['command'])}`")
                lines.append("")
            for reason in record.get("reasons") or [record.get("stderr", "")]:
                lines.append(f"- {reason}")
            lines.append("")
    lines.extend(["", "## Environment", "", "```text", str(result["environment"]["uname"]), "```", ""])
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tracejit", default=str(ROOT / "target" / "release" / "tracejit"))
    parser.add_argument("--output-dir", default=str(ROOT / "benchmarks" / "results" / "phase1"))
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--scratch", default=None)
    args = parser.parse_args()

    tracejit = Path(args.tracejit).resolve()
    if not tracejit.is_file():
        parser.error(f"TraceJIT binary not found: {tracejit}")
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    table = syscall_table()

    if args.scratch:
        scratch = Path(args.scratch).resolve()
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = None
    else:
        temporary = tempfile.TemporaryDirectory(prefix="tracejit-census-")
        scratch = Path(temporary.name)

    fixture_source = ROOT / "tests" / "fixtures" / "fixture_driver.c"
    records = []
    try:
        for workload in workloads(fixture_source):
            try:
                record = census_workload(workload, tracejit, scratch, args.runs, args.warmups, table)
            except Exception as error:  # noqa: BLE001 - recorded as a harness failure
                record = {
                    "name": workload.name,
                    "category": workload.category,
                    "status": "harness_error",
                    "error": str(error),
                }
            records.append(record)
            print(
                f"{record['name']:26} {record['status']:22} {record.get('classification', '-'):18} "
                f"eligible={record.get('eligible_for_reuse', '-')}",
                flush=True,
            )
    finally:
        if temporary is not None:
            temporary.cleanup()

    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, capture_output=True, check=False).stdout.strip()
    result = {
        "commit": commit,
        "generated_unix_ms": int(time.time() * 1000),
        "syscall_name_source": "host kernel headers" if table else "unavailable; numbers only",
        "environment": environment(),
        "runs": {"warmups": args.warmups, "measured": args.runs},
        "workloads": records,
        "aggregate": aggregate(records),
    }
    (output_dir / "census.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "census.md").write_text(markdown(result), encoding="utf-8")
    failures = [
        record["name"]
        for record in records
        if record["status"] in ("harness_error", "unexpected_prime_result", "reuse_was_not_obtained")
        or record.get("output_equivalence") == "FAIL"
    ]
    print(json.dumps(result["aggregate"], indent=2, sort_keys=True))
    if failures:
        print(f"CENSUS FAILURES: {', '.join(failures)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
