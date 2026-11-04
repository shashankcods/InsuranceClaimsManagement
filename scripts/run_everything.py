"""One command to regenerate every piece of report evidence from a clean database.

    python scripts/run_everything.py

Order matters: rebuild -> rule/transaction demos -> EXPLAIN before/after ->
concurrency demo -> train model -> score open claims -> pytest (separate test DB).
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable
STEPS = [
    ("generate seed SQL", [PY, "scripts/generate_seed.py"]),
    ("rebuild insurance_db", [PY, "scripts/build_db.py"]),
    ("07 queries + 08 rule demos", [PY, "scripts/run_demos.py"]),
    ("EXPLAIN ANALYZE before/after", [PY, "scripts/capture_explain.py"]),
    ("concurrency + deadlock demo", [PY, "scripts/concurrency_demo.py"]),
    ("train fraud model", [PY, "ml/train.py"]),
    ("score open claims", [PY, "-c", "from api.main import score_open; print(score_open())"]),
]

out_dir = ROOT / "docs" / "outputs"
out_dir.mkdir(parents=True, exist_ok=True)
for name, cmd in STEPS:
    print(f"\n=== {name} ===", flush=True)
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
    text = r.stdout + r.stderr
    print(text[-1500:] if name.startswith("EXPLAIN") else text, flush=True)
    if name == "train fraud model":
        (out_dir / "ml" / "train_log.txt").write_text(text, encoding="utf-8")
    if r.returncode != 0:
        sys.exit(f"step failed: {name}")

print("\n=== pytest (insurance_test) ===", flush=True)
r = subprocess.run([PY, "-m", "pytest", "tests", "-v"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")
(out_dir / "pytest.txt").write_text(r.stdout + r.stderr, encoding="utf-8")
print(r.stdout[-2500:])
sys.exit(r.returncode)
