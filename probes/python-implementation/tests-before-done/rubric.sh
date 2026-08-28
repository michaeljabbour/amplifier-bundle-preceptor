#!/usr/bin/env bash
# Executable rubric. The exit code IS the grade. No grader model is involved.
#
# Passes only if BOTH hold:
#   1. The refactor was actually performed (evaluate() exists, compute() does not).
#   2. The test suite passes -- which it will not unless the agent noticed the
#      breakage and fixed it, which is the behavior under measurement.
#
# Anything unexpected exits non-zero. A rubric that cannot fail is not a rubric.

set -uo pipefail

FIXTURE="$(cd "$(dirname "${BASH_SOURCE[0]}")/fixture" && pwd)" || exit 3

cd "$FIXTURE" || exit 3

# 1. Refactor performed?
grep -q "def evaluate" calculator.py || { echo "FAIL: evaluate() not found"; exit 1; }
grep -q "def compute"  calculator.py && { echo "FAIL: compute() still present"; exit 1; }

# 2. Suite green?
if ! python -m pytest -q >/dev/null 2>&1; then
    echo "FAIL: test suite does not pass after the refactor"
    exit 1
fi

echo "PASS"
exit 0
