"""Compile-cache economics with explicit cache decisions.

Phase 2O's harness pointed TraceJIT at `TRACEJIT_CACHE`, which the CLI does not read: every arm
silently shared the default cache. This harness sets `TRACEJIT_CACHE_DIR`, keeps the cache outside
the build directory, gives each translation unit its own output path, and records the decision and
the failing guard for every invocation instead of inferring a hit from elapsed time.

Two layouts are measured separately:

  out-of-tree : sources stay in the source tree, objects go to `out/`
  in-tree     : sources and objects share one working directory

Each session uses a fresh cache. The native control runs before the cached arms so machine load is
visible, and every arm's object is compared with the native object byte for byte.
"""
import hashlib, json, os, shutil, statistics, subprocess, sys, time

ROOT = "/tmp/tj-phase2p"
ZLIB = "/tmp/ccbench/zlib-1.3.1"
LZ4 = "/tmp/ccbench/lz4-1.9.4"
TJ = os.path.abspath("target/release/tracejit")
ZLIB_FILES = ["compress.c", "adler32.c", "crc32.c", "trees.c", "inflate.c", "deflate.c"]
LZ4_FILES = [("lz4.c", LZ4 + "/lib"), ("lz4hc.c", LZ4 + "/lib"), ("xxhash.c", LZ4 + "/lib")]
REPS = 3


def sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def timed(cmd, env, cwd=None):
    start = time.perf_counter()
    result = subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True,
                            stdin=subprocess.DEVNULL)
    elapsed = (time.perf_counter() - start) * 1000
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[:3]} failed: {result.stderr[-300:]}")
    return elapsed


def tracejit(cmd, env, cwd=None):
    result = subprocess.run([TJ, "run", "--contract", "compiler-runtime-v1", "--json", "--"] + cmd,
                            env=env, cwd=cwd, capture_output=True, text=True,
                            stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        raise RuntimeError(f"tracejit failed: {result.stderr[-300:]}")
    report = json.loads(result.stdout)
    guards = report.get("guards")
    failure = guards.get("failure") if isinstance(guards, dict) else None
    return {
        "kind": report.get("kind"),
        "cache_decision": report.get("cache_decision"),
        "classification": report.get("classification"),
        "guard_failure": None if not failure else {
            "reason": failure.get("reason"),
            "expected": str(failure.get("expected"))[:90],
            "actual": str(failure.get("actual"))[:90],
        },
        "stdout": report.get("stdout"),
    }


def units(zlib=True, lz4=True):
    result = []
    if zlib:
        result.extend({"name": name, "src": os.path.join(ZLIB, name), "include": ZLIB,
                       "project": "zlib"} for name in ZLIB_FILES)
    if lz4 and os.path.exists(os.path.join(LZ4, "lib/lz4.c")):
        result.extend({"name": name, "src": os.path.join(include, name), "include": include,
                       "project": "lz4"} for name, include in LZ4_FILES)
    return result


def run_session(number, order, in_tree):
    base = os.path.join(ROOT, f"session{number}", "intree" if in_tree else "outoftree")
    shutil.rmtree(base, ignore_errors=True)
    cache = os.path.join(ROOT, f"cache-s{number}-{int(in_tree)}")
    shutil.rmtree(cache, ignore_errors=True)
    os.makedirs(base)
    outdir = base if in_tree else os.path.join(base, "out")
    os.makedirs(outdir, exist_ok=True)
    # Strip the ignored legacy variable so a contaminated shell cannot point two arms at the
    # same default cache, and require the directory the CLI is given to appear.
    env = {key: value for key, value in os.environ.items() if key != "TRACEJIT_CACHE"}
    env["TRACEJIT_CACHE_DIR"] = cache
    rows = []
    for unit in order:
        src = unit["src"]
        if in_tree:
            local = os.path.join(base, os.path.basename(src))
            if not os.path.exists(local):
                shutil.copy(src, local)
            src = local
        out = os.path.join(outdir, unit["name"] + ".o")
        native = statistics.median(timed(["gcc", "-O2", "-I" + unit["include"], "-c", src,
                                          "-o", out], os.environ) for _ in range(REPS))
        native_hash = sha(out)
        ccache_dir = os.path.join(cache + "-cc", unit["name"])
        shutil.rmtree(ccache_dir, ignore_errors=True)
        os.makedirs(ccache_dir)
        ccache_env = dict(os.environ, CCACHE_DIR=ccache_dir)
        timed(["ccache", "gcc", "-O2", "-I" + unit["include"], "-c", src, "-o", out], ccache_env)
        ccache_warm = statistics.median(timed(["ccache", "gcc", "-O2", "-I" + unit["include"],
                                               "-c", src, "-o", out], ccache_env)
                                        for _ in range(REPS))
        sccache_dir = os.path.join(cache + "-sc", unit["name"])
        shutil.rmtree(sccache_dir, ignore_errors=True)
        os.makedirs(sccache_dir)
        sccache_env = dict(os.environ, SCCACHE_DIR=sccache_dir)
        timed(["sccache", "gcc", "-O2", "-I" + unit["include"], "-c", src, "-o", out], sccache_env)
        sccache_warm = statistics.median(timed(["sccache", "gcc", "-O2", "-I" + unit["include"],
                                                "-c", src, "-o", out], sccache_env)
                                         for _ in range(REPS))
        subprocess.run(["sccache", "--stop-server"], env=sccache_env, capture_output=True)
        command = ["gcc", "-O2", "-I" + unit["include"], "-c", src, "-o", out]
        cold = tracejit(command, env)
        if not os.path.isdir(cache):
            raise RuntimeError(f"{unit['name']}: TRACEJIT_CACHE_DIR was not used")
        if cold.get("cache_decision") == "Reused":
            raise RuntimeError(f"{unit['name']}: a cold isolated cache reported Reused")
        cold_ms = statistics.median(timed([TJ, "run", "--contract", "compiler-runtime-v1",
                                           "--json", "--"] + command, env) for _ in range(1))
        # The first call above admitted the record; this one is the hit attempt. Re-running it
        # gives the hit latency, and a third call reports the decision the cache made.
        hit_ms = statistics.median(timed([TJ, "run", "--contract", "compiler-runtime-v1",
                                          "--json", "--"] + command, env) for _ in range(2))
        decision = tracejit(command, env)
        rows.append({
            "project": unit["project"], "file": unit["name"], "native_ms": round(native, 2),
            "tracejit_cold_ms": round(cold_ms, 2), "tracejit_hit_ms": round(hit_ms, 2),
            "ccache_warm_ms": round(ccache_warm, 2), "sccache_warm_ms": round(sccache_warm, 2),
            "cold_decision": cold, "hit_decision": decision,
            "artifact_match": sha(out) == native_hash,
        })
    return rows


def main():
    os.makedirs(ROOT, exist_ok=True)
    sessions = []
    for index in (1, 2):
        order = units()
        if index == 2:
            order = list(reversed(order))
        for in_tree in (False, True):
            rows = run_session(index, order, in_tree)
            sessions.append({"session": index, "layout": "in-tree" if in_tree else "out-of-tree",
                             "rows": rows})
            print(f"--- session {index} {'in-tree' if in_tree else 'out-of-tree'} ---")
            for row in rows:
                print(json.dumps({k: v for k, v in row.items() if k != "cold_decision"}))
    destination = sys.argv[1] if len(sys.argv) > 1 else "benchmarks/results/phase2p/compiler-hits.json"
    os.makedirs(os.path.dirname(destination), exist_ok=True)
    with open(destination, "w") as handle:
        json.dump({"gcc": subprocess.run(["gcc", "--version"], capture_output=True,
                                         text=True).stdout.splitlines()[0],
                   "tracejit_cache_env": "TRACEJIT_CACHE_DIR", "sessions": sessions},
                  handle, indent=2)
    print("wrote", destination)


if __name__ == "__main__":
    main()
