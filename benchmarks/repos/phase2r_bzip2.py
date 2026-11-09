"""Phase 2R: economic and adversarial measurement of the allocator-entropy contract.

The target is `bzip2 -9 -k -f` on a ~6 MB text file. The pre-state is a writable regular output
(the state a second invocation normally sees), so the cold trace records the same pre-state the
warm runs observe. Every arm uses the same isolated cache and environment.
"""
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import time

TJ = os.path.abspath("target/release/tracejit")
ROOT = "/tmp/tjq/phase2r"
WORK = os.path.join(ROOT, "work")
CACHE = os.path.join(ROOT, "cache")
RESULTS = os.path.abspath("benchmarks/results/phase2r")
CMD = ["bzip2", "-9", "-k", "-f", "big.txt"]
OUTPUT = "big.txt.bz2"
CONTRACT = "allocator-entropy-v1"


def build():
    shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(WORK)
    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    with open(os.path.join(WORK, "big.txt"), "w") as handle:
        for index in range(120_000):
            handle.write(" ".join(words[(index + offset) % len(words)] for offset in range(6)))
            handle.write(f" {index:08d}\n")


def env(extra=None, timing=None):
    values = {k: v for k, v in os.environ.items() if k not in ("TRACEJIT_CACHE", "TRACEJIT_CACHE_DIR")}
    values["TRACEJIT_CACHE_DIR"] = CACHE
    values["GLIBC_TUNABLES"] = "glibc.malloc.tcache_count=0"
    # Timing output is part of the environment, and the environment is part of the cache
    # identity. Keep it identical for every arm and write to one stable path.
    values["TRACEJIT_PHASE_TIMING"] = "1"
    values["TRACEJIT_PHASE_TIMING_PATH"] = os.path.join(ROOT, "timing.json")
    if extra:
        values.update(extra)
    return values


def run(cmd, extra=None, timing=None):
    started = time.perf_counter()
    result = subprocess.run(
        [TJ, "run", "--json", "--admission", "always", "--contract", CONTRACT, "--"] + cmd,
        cwd=WORK,
        env=env(extra, timing),
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    )
    elapsed = (time.perf_counter() - started) * 1000
    try:
        report = json.loads(result.stdout)
    except json.JSONDecodeError:
        report = {"kind": "NO_JSON", "stderr": result.stderr[-400:]}
    return elapsed, report, result.returncode


def native(cmd):
    started = time.perf_counter()
    result = subprocess.run(cmd, cwd=WORK, capture_output=True, stdin=subprocess.DEVNULL)
    return (time.perf_counter() - started) * 1000, result


def remove_output():
    try:
        os.remove(os.path.join(WORK, OUTPUT))
    except FileNotFoundError:
        pass


def fingerprint():
    path = os.path.join(WORK, OUTPUT)
    metadata = os.stat(path)
    with open(path, "rb") as handle:
        digest = hashlib.sha256(handle.read()).hexdigest()
    return {
        "sha256": digest,
        "size": metadata.st_size,
        "mode": oct(metadata.st_mode & 0o7777),
        "mtime_ns": metadata.st_mtime_ns,
        "uid": metadata.st_uid,
        "gid": metadata.st_gid,
    }


def cache_bytes():
    total = 0
    for base, _dirs, files in os.walk(CACHE):
        for name in files:
            total += os.path.getsize(os.path.join(base, name))
    return total


def main():
    os.makedirs(RESULTS, exist_ok=True)
    build()
    rows = {"command": CMD, "contract": CONTRACT, "phases": {}}

    native_times = []
    for _ in range(5):
        remove_output()
        elapsed, result = native(CMD)
        assert result.returncode == 0
        native_times.append(elapsed)
    remove_output()
    native(CMD)  # establish the writable regular output pre-state
    rows["native_ms"] = [round(value, 2) for value in native_times]
    rows["native_median_ms"] = round(statistics.median(native_times), 2)
    rows["native_output"] = fingerprint()

    cold_ms, cold, _ = run(CMD, timing=os.path.join(ROOT, "cold-timing.json"))
    rows["cold_ms"] = round(cold_ms, 2)
    rows["cold_decision"] = cold.get("cache_decision")
    rows["cold_kind"] = cold.get("kind")
    rows["cold_phases"] = cold.get("phases")
    rows["cold_output"] = fingerprint()

    warm_times = []
    warm_reports = []
    for _ in range(5):
        elapsed, report, _ = run(CMD)
        warm_times.append(elapsed)
        warm_reports.append(
            {
                "kind": report.get("kind"),
                "decision": report.get("cache_decision"),
                "reason": report.get("decision_reason"),
                "phases": report.get("phases"),
            }
        )
    rows["warm_ms"] = [round(value, 2) for value in warm_times]
    rows["warm_median_ms"] = round(statistics.median(warm_times), 2)
    rows["warm_reports"] = warm_reports
    rows["warm_output"] = fingerprint()
    rows["warm_output_matches_cold"] = rows["warm_output"] == rows["cold_output"]
    rows["cache_bytes"] = cache_bytes()

    # A content change must invalidate and produce the new bytes.
    source = os.path.join(WORK, "big.txt")
    original = open(source, "rb").read()
    with open(source, "ab") as handle:
        handle.write(b"\nphase2r-change\n")
    changed_ms, changed, _ = run(CMD)
    rows["changed_input"] = {
        "decision": changed.get("cache_decision"),
        "kind": changed.get("kind"),
        "reason": changed.get("decision_reason"),
        "ms": round(changed_ms, 2),
        "output": fingerprint(),
        "differs": fingerprint()["sha256"] != rows["cold_output"]["sha256"],
    }
    with open(source, "wb") as handle:
        handle.write(original)

    # Different arguments are a different identity.
    altered_ms, altered, _ = run(["bzip2", "-1", "-k", "-f", "big.txt"])
    rows["changed_arguments"] = {
        "decision": altered.get("cache_decision"),
        "kind": altered.get("kind"),
        "reason": altered.get("decision_reason"),
        "ms": round(altered_ms, 2),
    }

    # Environment is part of the identity.
    env_ms, env_report, _ = run(CMD, extra={"PHASE2R_PROBE": "1"})
    rows["changed_environment"] = {
        "decision": env_report.get("cache_decision"),
        "kind": env_report.get("kind"),
        "reason": env_report.get("decision_reason"),
        "ms": round(env_ms, 2),
    }

    # A corrupt CAS object must be detected before exposure and retraced.
    objects = os.path.join(CACHE, "objects")
    victims = sorted(
        (os.path.getsize(os.path.join(objects, name)), name) for name in os.listdir(objects)
    )
    victim = os.path.join(objects, victims[-1][1])
    with open(victim, "r+b") as handle:
        first = handle.read(1)
        handle.seek(0)
        handle.write(bytes([first[0] ^ 0xFF]))
    corrupt_ms, corrupt, _ = run(CMD)
    rows["cache_corruption"] = {
        "decision": corrupt.get("cache_decision"),
        "kind": corrupt.get("kind"),
        "reason": corrupt.get("decision_reason"),
        "ms": round(corrupt_ms, 2),
        "output_restored": fingerprint()["sha256"],
        "matches_native": fingerprint()["sha256"] == rows["native_output"]["sha256"],
    }

    # Concurrent warm runs must all be correct and must not hit a lock error.
    import concurrent.futures

    def one(_):
        elapsed, report, code = run(CMD)
        return {
            "decision": report.get("cache_decision"),
            "kind": report.get("kind"),
            "exit": code,
            "sha": fingerprint()["sha256"],
            "ms": round(elapsed, 2),
        }

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        rows["concurrent"] = list(pool.map(one, range(8)))

    repeats = 10
    remove_output()
    repeated_native = []
    for _ in range(repeats):
        elapsed, result = native(CMD)
        assert result.returncode == 0
        repeated_native.append(elapsed)
    repeated_warm = []
    for _ in range(repeats):
        elapsed, report, _ = run(CMD)
        repeated_warm.append(elapsed)
    rows["repeated"] = {
        "runs": repeats,
        "native_total_ms": round(sum(repeated_native), 2),
        "warm_total_ms": round(sum(repeated_warm), 2),
        "net_ms": round(sum(repeated_native) - sum(repeated_warm), 2),
        "speedup": round(sum(repeated_native) / sum(repeated_warm), 2),
        "all_reused": all(report["decision"] == "Reused" for report in warm_reports),
    }

    with open(os.path.join(RESULTS, "bzip2.json"), "w") as handle:
        json.dump(rows, handle, indent=2, sort_keys=True)
    print(json.dumps(rows, indent=1, sort_keys=True)[:4000])


if __name__ == "__main__":
    main()
