#!/bin/sh
# Deterministic integer fold. No date, random, or network commands.
set -eu
awk '
BEGIN { digest = 0 }
{
    digest = (digest * 1315423911 + $1) % 4294967296
}
END { printf "%08x\n", digest }
' benchmarks/workloads/shell-pipeline/numbers.txt
