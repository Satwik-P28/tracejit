"""Phase 2Q: fixed discovery suite of unmodified commands from several workflow categories.

Every candidate runs in the same fixture workspace with an explicit output path. The script records
the native time, the cold decision and refusal reasons, the warm decision and failing guard, the
changed-input decision, and whether reused artifacts match native bytes.

Cache isolation is asserted, not assumed: each candidate gets a fresh `TRACEJIT_CACHE_DIR`, the
ignored legacy variable is stripped, and a cold run that reports `Reused` aborts the candidate.
"""
import glob
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import sys
import time

ROOT = "/tmp/tjq/discovery"
TJ = os.path.abspath("target/release/tracejit")
WORK = os.path.join(ROOT, "work")
RESULTS = os.path.abspath("benchmarks/results/phase2q")

CANDIDATES = [
    {
        "name": "gzip_text",
        "category": "compression",
        "cmd": ["gzip", "-9", "-k", "-f", "big.txt"],
        "outputs": ["big.txt.gz"],
        "input": "big.txt",
        "reuse_frequency": "high in asset/log pipelines",
    },
    {
        "name": "xz_text",
        "category": "compression",
        "cmd": ["xz", "-6", "-k", "-f", "big.txt"],
        "outputs": ["big.txt.xz"],
        "input": "big.txt",
        "reuse_frequency": "medium; release artifact packaging",
    },
    {
        "name": "bzip2_text",
        "category": "compression",
        "cmd": ["bzip2", "-9", "-k", "-f", "big.txt"],
        "outputs": ["big.txt.bz2"],
        "input": "big.txt",
        "reuse_frequency": "low-medium",
    },
    {
        "name": "tar_tree",
        "category": "archive",
        "cmd": ["tar", "-cf", "tree.tar", "tree"],
        "outputs": ["tree.tar"],
        "input": "tree/f000.txt",
        "reuse_frequency": "high in packaging",
    },
    {
        "name": "zip_tree",
        "category": "archive",
        "cmd": ["zip", "-q", "-r", "-X", "tree.zip", "tree"],
        "outputs": ["tree.zip"],
        "input": "tree/f001.txt",
        "reuse_frequency": "high in release pipelines",
    },
    {
        "name": "sort_text",
        "category": "data preprocessing",
        "cmd": ["sort", "-S", "256M", "-o", "sorted.txt", "big.txt"],
        "outputs": ["sorted.txt"],
        "input": "big.txt",
        "reuse_frequency": "high in ETL loops",
    },
    {
        "name": "jq_transform",
        "category": "data preprocessing",
        "cmd": ["sh", "-c", "jq -c '.[] | {id: .id, v: (.v * 2)}' big.json > out.json"],
        "outputs": ["out.json"],
        "input": "big.json",
        "reuse_frequency": "high; repeated report generation",
    },
    {
        "name": "objdump_disassembly",
        "category": "static analysis",
        "cmd": ["sh", "-c", "objdump -d prog > prog.dis"],
        "outputs": ["prog.dis"],
        "input": "prog",
        "reuse_frequency": "medium; repeated binary inspection",
    },
    {
        "name": "nm_symbols",
        "category": "static analysis",
        "cmd": ["sh", "-c", "nm -S --size-sort prog > prog.nm"],
        "outputs": ["prog.nm"],
        "input": "prog",
        "reuse_frequency": "medium",
    },
    {
        "name": "readelf_headers",
        "category": "static analysis",
        "cmd": ["sh", "-c", "readelf -a prog > prog.re"],
        "outputs": ["prog.re"],
        "input": "prog",
        "reuse_frequency": "medium",
    },
    {
        "name": "strip_binary",
        "category": "asset pipeline",
        "cmd": ["strip", "-o", "prog.stripped", "prog"],
        "outputs": ["prog.stripped"],
        "input": "prog",
        "reuse_frequency": "high in packaging",
    },
    {
        "name": "objcopy_raw",
        "category": "asset pipeline",
        "cmd": ["objcopy", "-O", "binary", "prog", "prog.bin"],
        "outputs": ["prog.bin"],
        "input": "prog",
        "reuse_frequency": "medium; firmware builds",
    },
    {
        "name": "python_compileall",
        "category": "code generation",
        "cmd": ["python3", "-m", "compileall", "-q", "-f", "pkg"],
        "outputs": ["pkg/__pycache__"],
        "input": "pkg/m000.py",
        "reuse_frequency": "high in Python CI",
    },
    {
        "name": "python_json_script",
        "category": "code generation",
        "cmd": ["python3", "transform.py", "big.json", "script-out.json"],
        "outputs": ["script-out.json"],
        "input": "big.json",
        "reuse_frequency": "high; build scripts",
    },
    {
        "name": "gcc_compile",
        "category": "compiler reference",
        "cmd": ["gcc", "-O2", "-Isrc", "-c", "src/a.c", "-o", "a.o"],
        "outputs": ["a.o"],
        "input": "src/a.c",
        "reuse_frequency": "reference; Phase 2P measured",
    },
    {
        "name": "awk_transform",
        "category": "large-file transformation",
        "cmd": ["sh", "-c", "awk '{print NR, $0}' big.txt > awk.txt"],
        "outputs": ["awk.txt"],
        "input": "big.txt",
        "reuse_frequency": "medium; one-off but large",
    },
    {
        "name": "sed_transform",
        "category": "large-file transformation",
        "cmd": ["sh", "-c", "sed 's/alpha/omega/g' big.txt > sed.txt"],
        "outputs": ["sed.txt"],
        "input": "big.txt",
        "reuse_frequency": "medium",
    },
]


def sh(cmd, env=None, cwd=WORK):
    # A regular empty file: a /dev/null stdin makes some tools seek an inherited character
    # device, which is a different observation than the file-backed stdin a real caller supplies.
    with open(os.path.join(WORK, "stdin.txt"), "rb") as handle:
        return subprocess.run(cmd, env=env, cwd=cwd, capture_output=True, text=True, stdin=handle)


def sha(path):
    if os.path.isdir(path):
        digest = hashlib.sha256()
        for base, dirs, files in sorted(os.walk(path)):
            dirs.sort()
            for name in sorted(files):
                full = os.path.join(base, name)
                digest.update(os.path.relpath(full, path).encode())
                with open(full, "rb") as handle:
                    digest.update(handle.read())
        return digest.hexdigest()
    with open(path, "rb") as handle:
        return hashlib.sha256(handle.read()).hexdigest()


def outputs_fingerprint(names):
    results = {}
    for name in names:
        matches = glob.glob(os.path.join(WORK, name))
        if not matches:
            results[name] = None
        for match in matches:
            results[os.path.relpath(match, WORK)] = {
                "sha256": sha(match),
                "mode": oct(os.stat(match).st_mode & 0o7777),
                "kind": "dir" if os.path.isdir(match) else "file",
            }
    return results


def clean(names):
    for name in names:
        for match in glob.glob(os.path.join(WORK, name)):
            if os.path.isdir(match):
                shutil.rmtree(match)
            else:
                os.remove(match)


def build_fixtures():
    shutil.rmtree(ROOT, ignore_errors=True)
    os.makedirs(WORK)
    open(os.path.join(WORK, "stdin.txt"), "wb").close()
    words = ["alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta"]
    with open(os.path.join(WORK, "big.txt"), "w") as handle:
        for index in range(120_000):
            handle.write(" ".join(words[(index + offset) % len(words)] for offset in range(6)))
            handle.write(f" {index:08d}\n")
    with open(os.path.join(WORK, "big.json"), "w") as handle:
        handle.write("[")
        handle.write(
            ",".join(
                json.dumps({"id": index, "v": index % 97, "name": f"row-{index % 31}"})
                for index in range(60_000)
            )
        )
        handle.write("]")
    with open(os.path.join(WORK, "transform.py"), "w") as handle:
        handle.write(
            "import json, sys\n"
            "rows = json.load(open(sys.argv[1]))\n"
            "with open(sys.argv[2], 'w') as out:\n"
            "    json.dump([{'id': r['id'], 'v': r['v'] * 2} for r in rows], out, sort_keys=True)\n"
        )
    os.makedirs(os.path.join(WORK, "tree"))
    for index in range(150):
        with open(os.path.join(WORK, "tree", f"f{index:03d}.txt"), "w") as handle:
            handle.write(f"file {index}\n" * 200)
    os.makedirs(os.path.join(WORK, "src"))
    with open(os.path.join(WORK, "src", "a.h"), "w") as handle:
        handle.write("\n".join(f"int g{index}(int);" for index in range(80)) + "\n")
    with open(os.path.join(WORK, "src", "a.c"), "w") as handle:
        handle.write('#include "a.h"\n')
        for index in range(600):
            handle.write(
                f"int g{index}(int x){{int y=x*{index + 3};if(y&1)y+={index};return y^{index * 7};}}\n"
            )
    os.makedirs(os.path.join(WORK, "pkg"))
    for index in range(40):
        with open(os.path.join(WORK, "pkg", f"m{index:03d}.py"), "w") as handle:
            handle.write(f"def f{index}(x):\n    return x * {index + 1}\n")
    with open(os.path.join(WORK, "src", "main.c"), "w") as handle:
        handle.write('#include "a.h"\nint main(void) { return g0(1) == 0; }\n')
    subprocess.run(
        ["gcc", "-O2", "-Isrc", "-c", "src/a.c", "-o", "prog.o"],
        cwd=WORK,
        check=True,
    )
    subprocess.run(
        ["gcc", "-Isrc", "-o", "prog", "prog.o", "src/main.c"], cwd=WORK, check=True
    )


def timed(cmd, env):
    start = time.perf_counter()
    result = sh(cmd, env=env)
    return (time.perf_counter() - start) * 1000, result


def report_of(result):
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"kind": "NO_JSON", "stderr": result.stderr[-300:]}


def measure(candidate):
    clean(candidate["outputs"])
    native_env = dict(os.environ, GLIBC_TUNABLES="glibc.malloc.tcache_count=0")
    native, native_result = timed(candidate["cmd"], native_env)
    if native_result.returncode != 0:
        return {"name": candidate["name"], "status": "native-failed", "stderr": native_result.stderr[-300:]}
    _, second = timed(candidate["cmd"], native_env)
    native = statistics.median([native, second[0] if isinstance(second, tuple) else native])
    native_outputs = outputs_fingerprint(candidate["outputs"])

    cache = os.path.join(ROOT, "caches", candidate["name"])
    shutil.rmtree(cache, ignore_errors=True)
    env = {key: value for key, value in os.environ.items() if key != "TRACEJIT_CACHE"}
    env["TRACEJIT_CACHE_DIR"] = cache
    # glibc seeds tcache with getrandom on first allocation; that is allocator state, not an input
    # the command asked for. Disable it for both arms so the comparison is about the tool.
    env["GLIBC_TUNABLES"] = "glibc.malloc.tcache_count=0"
    clean(candidate["outputs"])
    cold_ms, cold_result = timed([TJ, "run", "--json", "--"] + candidate["cmd"], env)
    cold = report_of(cold_result)
    if not os.path.isdir(cache):
        return {"name": candidate["name"], "status": "cache-not-created"}
    if cold.get("cache_decision") == "Reused":
        return {"name": candidate["name"], "status": "cold-reused", "cold": cold}

    warm_ms, warm_result = timed([TJ, "run", "--json", "--"] + candidate["cmd"], env)
    warm = report_of(warm_result)
    warm_outputs = outputs_fingerprint(candidate["outputs"])
    artifacts_match = native_outputs == warm_outputs

    changed_path = os.path.join(WORK, candidate["input"])
    if os.path.isdir(changed_path):
        changed_path = os.path.join(changed_path, "f000.txt")
    original = open(changed_path, "rb").read()
    with open(changed_path, "ab") as handle:
        handle.write(b"\nphase2q-change\n")
    changed_ms, changed_result = timed([TJ, "run", "--json", "--"] + candidate["cmd"], env)
    changed = report_of(changed_result)
    with open(changed_path, "wb") as handle:
        handle.write(original)

    reasons = warm.get("reasons") or []
    guard_failure = warm.get("guards", {}).get("failure") if isinstance(warm.get("guards"), dict) else None
    first_refusal = cold.get("reasons") or (
        [cold.get("decision_reason")] if cold.get("decision_reason") else []
    )
    return {
        "name": candidate["name"],
        "category": candidate["category"],
        "command": candidate["cmd"],
        "reuse_frequency": candidate["reuse_frequency"],
        "status": "measured",
        "native_ms": round(native, 2),
        "cold_ms": round(cold_ms, 2),
        "warm_ms": round(warm_ms, 2),
        "cold_decision": cold.get("cache_decision"),
        "cold_kind": cold.get("kind"),
        "first_refusal": first_refusal,
        "warm_decision": warm.get("cache_decision"),
        "warm_kind": warm.get("kind"),
        "warm_guard_failure": guard_failure,
        "warm_reasons": reasons,
        "changed_decision": changed.get("cache_decision"),
        "artifacts_match_native": artifacts_match if warm.get("cache_decision") == "Reused" else None,
        "native_outputs": native_outputs,
        "warm_outputs": warm_outputs,
    }


def main():
    os.makedirs(RESULTS, exist_ok=True)
    build_fixtures()
    rows = [measure(candidate) for candidate in CANDIDATES]
    with open(os.path.join(RESULTS, "discovery.json"), "w") as handle:
        json.dump(rows, handle, indent=2, sort_keys=True)
    for row in rows:
        if row["status"] != "measured":
            print(f"{row['name']:22} {row['status']}")
            continue
        verdict = row["warm_decision"] or "?"
        print(
            f"{row['name']:22} native={row['native_ms']:8.1f} cold={row['cold_ms']:8.1f} "
            f"warm={row['warm_ms']:8.1f} {verdict:12} artifacts={row['artifacts_match_native']}"
        )
        if row["warm_guard_failure"]:
            print(f"    guard: {str(row['warm_guard_failure'])[:180]}")
        if verdict != "Reused" and row["warm_reasons"]:
            print(f"    reasons: {str(row['warm_reasons'])[:240]}")


if __name__ == "__main__":
    main()
