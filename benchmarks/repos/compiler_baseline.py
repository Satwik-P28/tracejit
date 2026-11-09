"""Competitive baseline: native gcc vs ccache vs sccache vs TraceJIT contract mode.

Every arm compiles the same file with the same flags into the same output path. Warm arms
repeat the identical command, which is what a developer's edit-build loop asks of a cache:
changed sources are cold for all caches, so cold cost is measured separately.
"""
import hashlib, json, os, shutil, statistics, subprocess, sys, time

ROOT = "/tmp/tj-compiler-baseline"
ZLIB = "/tmp/ccbench/zlib-1.3.1"
TJ = os.path.abspath("target/release/tracejit")
FILES = ["compress.c", "adler32.c", "crc32.c", "trees.c", "inflate.c", "deflate.c"]
WARM_REPS = 5


def sh(cmd, env=None, cwd=None):
    return subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True)


def sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def timed(cmd, env):
    start = time.perf_counter()
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    elapsed = (time.perf_counter() - start) * 1000
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[:2]} failed: {result.stderr[:300]}")
    return elapsed


def session(name, order):
    base = os.path.join(ROOT, name)
    shutil.rmtree(base, ignore_errors=True)
    os.makedirs(base)
    ccache_dir = os.path.join(base, "ccache")
    sccache_dir = os.path.join(base, "sccache")
    shutil.os.makedirs(ccache_dir, exist_ok=True)
    os.makedirs(sccache_dir, exist_ok=True)
    tj_cache = os.path.join(base, "tracejit")
    ccache_env = dict(os.environ, CCACHE_DIR=ccache_dir, CCACHE_MAXSIZE="2G")
    sccache_env = dict(os.environ, SCCACHE_DIR=sccache_dir)
    # `TRACEJIT_CACHE` is not read by the CLI; the Phase 2O harness used it and every arm
    # silently shared the default cache. Assert the directory the CLI is actually given.
    tj_env = dict(os.environ, TRACEJIT_CACHE_DIR=tj_cache)
    out = os.path.join(base, "out.o")
    rows = []
    for name_ in order:
        src = os.path.join(ZLIB, name_)
        arm = {}
        arm["native_ms"] = statistics.median(timed(["gcc", "-O2", "-I" + ZLIB, "-c", src, "-o", out], os.environ) for _ in range(WARM_REPS))
        native_hash = sha(out)
        sh(["ccache", "-C"], ccache_env)
        cold = timed(["ccache", "gcc", "-O2", "-I" + ZLIB, "-c", src, "-o", out], ccache_env)
        warm = statistics.median(timed(["ccache", "gcc", "-O2", "-I" + ZLIB, "-c", src, "-o", out], ccache_env) for _ in range(WARM_REPS))
        arm.update(ccache_cold_ms=cold, ccache_warm_ms=warm, ccache_match=sha(out) == native_hash)
        sh(["sccache", "--stop-server"], sccache_env)
        try:
            sccache_dir2 = os.path.join(base, "sccache-" + name_)
            os.makedirs(sccache_dir2, exist_ok=True)
            sccache_env = dict(os.environ, SCCACHE_DIR=sccache_dir2)
            cold = timed(["sccache", "gcc", "-O2", "-I" + ZLIB, "-c", src, "-o", out], sccache_env)
            warm = statistics.median(timed(["sccache", "gcc", "-O2", "-I" + ZLIB, "-c", src, "-o", out], sccache_env) for _ in range(WARM_REPS))
            arm.update(sccache_cold_ms=cold, sccache_warm_ms=warm, sccache_match=sha(out) == native_hash)
            sh(["sccache", "--stop-server"], sccache_env)
        except Exception as error:  # noqa: BLE001 - recorded as an incomplete arm
            arm["sccache_error"] = str(error)[:200]
        cold = timed([TJ, "run", "--contract", "compiler-runtime-v1", "--json", "--", "gcc", "-O2", "-I" + ZLIB, "-c", src, "-o", out], tj_env)
        arm.update(tracejit_cold_ms=cold, tracejit_match=sha(out) == native_hash)
        second = sh([TJ, "run", "--contract", "compiler-runtime-v1", "--json", "--", "gcc", "-O2", "-I" + ZLIB, "-c", src, "-o", out], tj_env)
        report = json.loads(second.stdout)
        arm["tracejit_second_kind"] = report["kind"]
        arm["tracejit_second_decision"] = report.get("cache_decision")
        rows.append({"file": name_, **arm})
    return rows


def main():
    sessions = []
    for index, order in enumerate((FILES, list(reversed(FILES))), start=1):
        rows = session(f"session{index}", order)
        sessions.append({"session": f"session{index}", "rows": rows})
        print(f"--- session{index} ---")
        for row in rows:
            print(json.dumps(row))
    out = sys.argv[1] if len(sys.argv) > 1 else "benchmarks/results/phase2o/compiler-baseline.json"
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "w") as handle:
        json.dump({"zlib": "1.3.1", "gcc": sh(["gcc", "--version"]).stdout.splitlines()[0],
                   "ccache": sh(["ccache", "--version"]).stdout.splitlines()[0],
                   "sccache": sh(["sccache", "--version"]).stdout.strip(), "sessions": sessions}, handle, indent=2)
    print("wrote", out)


if __name__ == "__main__":
    main()
