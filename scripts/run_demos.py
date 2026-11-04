"""Run 07_queries.sql and 08_rule_demos.sql verbosely and save the output as report evidence."""
from dbutil import DB_DIR, ENV, OUT_DIR, run_file

OUT_DIR.mkdir(parents=True, exist_ok=True)
for name, force in [("07_queries.sql", False), ("08_rule_demos.sql", True)]:
    rc, out = run_file(DB_DIR / name, database=ENV["DB_NAME"], verbose=True, force=force)
    target = OUT_DIR / name.replace(".sql", ".txt")
    target.write_text(out, encoding="utf-8")
    errors = [l for l in out.splitlines() if l.startswith("ERROR")]
    print(f"{name}: rc={rc}, {len(errors)} ERROR lines -> {target}")
    for e in errors:
        print("   ", e)
