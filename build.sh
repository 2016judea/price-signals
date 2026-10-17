#!/bin/sh
# Rebuild prices.duckdb from every source repo (read in place). ~30 s.
set -e
cd "$(dirname "$0")"
for l in load_pt_rates load_salon load_houses load_parts load_marketplace load_bricks; do
  echo "== $l"; .venv/bin/python $l.py | tail -1
done
.venv/bin/python -c "import db; db.counts(db.connect())"
