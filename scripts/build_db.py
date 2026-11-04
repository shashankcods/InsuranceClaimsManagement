"""Rebuild a database from scratch: schema, triggers, procedures, views, seed, indexes.

    python scripts/build_db.py              # main database (insurance_db), with seed
    python scripts/build_db.py --test       # test database (insurance_test), no seed
"""
import argparse
import sys
import time

from dbutil import DB_DIR, ENV, run_file

FILES = ["01_schema.sql", "02_triggers.sql", "03_procedures.sql", "04_views.sql",
         "05_seed_data.sql", "06_indexes.sql"]


def build(database, seed=True, indexes=True, quiet=False):
    for name in FILES:
        if name == "05_seed_data.sql" and not seed:
            continue
        if name == "06_indexes.sql" and not indexes:
            continue
        t0 = time.time()
        rc, out = run_file(DB_DIR / name, database=database)
        if not quiet:
            print(f"[{database}] {name:20s} rc={rc} {time.time() - t0:6.1f}s")
            if out.strip():
                print(out.strip())
        if rc != 0:
            raise SystemExit(f"FAILED on {name}:\n{out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true", help="build the test database without seed data")
    ap.add_argument("--no-indexes", action="store_true")
    a = ap.parse_args()
    if a.test:
        build(ENV["TEST_DB_NAME"], seed=False, indexes=not a.no_indexes)
    else:
        build(ENV["DB_NAME"], seed=True, indexes=not a.no_indexes)
    sys.exit(0)
