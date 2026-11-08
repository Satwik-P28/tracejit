"""Compile-cache economics: native, ccache, sccache and TraceJIT contract reuse.

Two independent sessions with reversed file order, native control in each arm, byte-equality
checked against the native object. TraceJIT's first invocation is the cold trace; subsequent
identical invocations are cache hits.
"""
import hashlib, json, os, shutil, statistics, subprocess, sys, time

ROOT = "/tmp/tj-compile-hits"
ZLIB = "/tmp/ccbench/zlib-1.3.1"
TJ = os.path.abspath("target/release/tracejit")
FILES = ["compress.c", "adler32.c", "crc32.c", "trees.c", "inflate.c", "deflate.c"]


def timed(cmd, env):
    start = time.perf_counter()
    result = subprocess.run(cmd, env=env, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if result.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {result.stderr[-300:]}")
    return (time.perf_counter() - start) * 1000


def sha(path):
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def main():
    sessions = []
    for index, order in enumerate((FILES, list(reversed(FILES))), start=1):
        base = os.path.join(ROOT, f"session{index}")
        shutil.rmtree(base, ignore_errors=True)
        os.makedirs(base)
        env = dict(os.environ, TRACEJIT_CACHE=base + "/tj")
        out = base + "/out.o"
        rows = []
        for name in order:
            src = os.path.join(ZLIB, name)
            native = statistics.median(timed(["gcc", "-O2", "-I" + ZLIB, "-c", src, "-o", out], os.environ) for _ in range(5))
            native_hash = sha(out)
            ccache_dir = base + "/cc-" + name
            os.makedirs(ccache_dir, exist_ok=True)
            ccache_env = dict(os.environ, CCACHE_DIR=ccache_dir)
            timed(["ccache", "gcc", "-O2", "-I" + ZLIB, "-c", src, "-o", out], ccache_env)
            ccache_warm = statistics.median(timed(["ccache", "gcc", "-O2", "-I" + ZLIB, "-c", src, "-o", out], ccache_env) for _ in range(5))
            sccache_env = dict(os.environ, SCCACHE_DIR=base + "/sc-" + name)
            os.makedirs(sccache_env["SCCACHE_DIR"], exist_ok=True)
            timed(["sccache", "gcc", "-O2", "-I" + ZLIB, "-c", src, "-o", out], sccache_env)
            sccache_warm = statistics.median(timed(["sccache", "gcc", "-O2", "-I" + ZLIB, "-c", src, "-o", out], sccache_env) for _ in range(5))
            subprocess.run(["sccache", "--stop-server"], env=sccache_env, capture_output=True)
            cold = timed([TJ, "run", "--contract", "compiler-runtime-v1", "--json", "--", "gcc", "-O2", "-I" + ZLIB, "-c", src, "-o", out], env)
            hits = [timed([TJ, "run", "--contract", "compiler-runtime-v1", "--json", "--", "gcc", "-O2", "-I" + ZLIB, "-c", src, "-o", out], env) for _ in range(3)]
            report = subprocess.run([TJ, "run", "--contract", "compiler-runtime-v1", "--json", "--", "gcc", "-O2", "-I" + ZLIB, "-c", src, "-o", out], env=env, capture_output=True, text=True)
            kind = json.loads(report.stdout)["kind"]
            rows.append({
                "file": name, "native_ms": native, "tracejit_cold_ms": cold,
                "tracejit_hit_ms": statistics.median(hits),
                "ccache_warm_ms": ccache_warm, "sccache_warm_ms": sccache_warm,
                "artifact_match": sha(out) == native_hash, "same_identity_kind": kind,
            })
        sessions.append({"session": f"session{index}", "rows": rows})
        print(f"--- session{index} ---")
        for row in rows:
            print(json.dumps({k: round(v, 1) if isinstance(v, float) else v for k, v in row.items()}))
    out = sys.argv[1] if len(sys.argv) > 1 else "benchmarks/results/phase2o/compiler-hits.json"
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w") as handle:
        json.dump({"gcc": subprocess.run(["gcc", "--version"], capture_output=True, text=True).stdout.splitlines()[0], "sessions": sessions}, handle, indent=2)
    print("wrote", out)


if __name__ == "__main__":
    main()
