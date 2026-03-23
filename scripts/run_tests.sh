#!/usr/bin/env bash

set -euo pipefail

export SKIP_BROWSER_TESTS="${SKIP_BROWSER_TESTS:-1}"
echo "SKIP_BROWSER_TESTS=${SKIP_BROWSER_TESTS}"

python -m pip install --upgrade pip

if [ -f "requirements-dev.txt" ]; then
  pip install -r requirements-dev.txt
else
  pip install -r requirements.txt
fi

python -m unittest discover -s tests -p "test_*.py" -v
