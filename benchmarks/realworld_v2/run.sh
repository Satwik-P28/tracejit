#!/usr/bin/env bash
# One-command Phase AA real-world benchmark.
#
#   ./benchmarks/realworld_v2/run.sh                # full run, evidence into benchmarks/results/phaseaa
#   AA_MODE=smoke ./benchmarks/realworld_v2/run.sh  # PR smoke: held-out excluded, small sample
#   AA_SKIP_BUILD=1 ./benchmarks/realworld_v2/run.sh
#
# Every stage writes its own artifact; a failing stage stops the run and keeps
# the artifacts produced so far. Nothing here writes outside the workspace
# except the scratch cache under AA_SCRATCH (default /tmp).
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo="$(cd "${here}/../.." && pwd)"
cd "${repo}"

mode="${AA_MODE:-full}"
tracejit="${AA_TRACEJIT:-${repo}/target/release/tracejit}"
output="${AA_OUTPUT:-${repo}/benchmarks/results/phaseaa}"
scratch="${AA_SCRATCH:-/tmp/tracejit-realworld-v2}"
vendor="${AA_VENDOR:-${scratch}/vendor}"

export PATH="${HOME}/.cargo/bin:${HOME}/.local/bin:${PATH}"

echo "== environment =="
uname -a
command -v gcc cc make tar gzip || true
python3 --version
if [[ -z "${AA_TRACEJIT:-}" ]]; then
  echo "== build =="
  if [[ "${AA_SKIP_BUILD:-0}" != "1" ]]; then
    cargo build --workspace --release
  fi
fi
test -x "${tracejit}" || { echo "missing TraceJIT binary ${tracejit}" >&2; exit 1; }
"${tracejit}" doctor || true

echo "== pinned inputs =="
python3 "${here}/fetch_inputs.py" --vendor "${vendor}"

echo "== manifest =="
python3 "${here}/runner.py" --mode manifest

mkdir -p "${output}"
echo "${tracejit}" > "${output}/TRACEJIT_PATH.txt"
sha256sum "${tracejit}" > "${output}/TRACEJIT_SHA256.txt"

case "${mode}" in
  smoke)
    splits="dev"
    scale="0.25"
    policies="native,compiler-runtime-v1"
    trials="4"
    ;;
  full)
    splits="dev,validation,heldout"
    scale="1.0"
    policies="native,allocator-entropy-v1,compiler-runtime-v1"
    trials="12"
    ;;
  *)
    echo "unknown AA_MODE=${mode} (expected smoke or full)" >&2
    exit 2
    ;;
esac

echo "== qualification and timing (splits=${splits}) =="
python3 "${here}/runner.py" \
  --tracejit "${tracejit}" \
  --mode both \
  --policies "${policies}" \
  --splits "${splits}" \
  --reps-scale "${scale}" \
  --output-dir "${output}" \
  --scratch "${scratch}" \
  --vendor "${vendor}"

echo "== schema and protocol validation =="
python3 "${here}/validate.py" "${output}/results.json"

echo "== adversarial =="
python3 "${here}/adversarial.py" --tracejit "${tracejit}" --trials "${trials}" \
  --output "${output}/adversarial.json"

echo "== competitive =="
if [[ "${AA_SKIP_COMPETITIVE:-0}" != "1" ]]; then
  python3 "${here}/competitive.py" --tracejit "${tracejit}" \
    --output-dir "${output}" --vendor "${vendor}" --repeats "${AA_COMPETITIVE_REPEATS:-12}"
fi

echo "== done: ${output} =="
ls -1 "${output}"
