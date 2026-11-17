#!/usr/bin/env bash
# Reproduce Phase Q. Isolated from the product crates; installs only a research venv.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$here"

if [ ! -x .venv/bin/python ]; then
  python3 -m venv --system-site-packages .venv
  .venv/bin/pip install --quiet dwave-samplers dimod
fi

.venv/bin/python tjq_selftest.py
.venv/bin/python tjq_experiments.py

echo
echo "report: $here/REPORT.md"
echo "raw:    $here/results/measurements.json"
