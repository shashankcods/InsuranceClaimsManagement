"""Shared helpers: read .env and run .sql files through the mysql CLI.

Scripts that contain DELIMITER (triggers, procedures) must go through the
mysql client, not a driver's execute(), because DELIMITER is a client command.
"""
import os
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_DIR = ROOT / "db"
OUT_DIR = ROOT / "docs" / "outputs"


def load_env():
    env = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    for k in list(env):
        env[k] = os.environ.get(k, env[k])
    return env


ENV = load_env()


def _defaults_file():
    """Write a temporary option file so the password never appears on the command line."""
    fd, path = tempfile.mkstemp(suffix=".cnf")
    with os.fdopen(fd, "w") as f:
        f.write("[client]\n")
        f.write(f"host={ENV.get('DB_HOST', '127.0.0.1')}\n")
        f.write(f"port={ENV.get('DB_PORT', '3306')}\n")
        f.write(f"user={ENV['DB_USER']}\n")
        f.write(f"password={ENV['DB_PASSWORD']}\n")
        f.write("default-character-set=utf8mb4\n")
    return path


def run_sql(sql_text, database=None, verbose=False, force=False, table=True):
    """Run SQL text through the mysql CLI. Returns (returncode, combined output)."""
    cnf = _defaults_file()
    try:
        cmd = [ENV.get("MYSQL_BIN", "mysql"), f"--defaults-extra-file={cnf}", "--unbuffered"]
        if database:
            cmd.append(f"--database={database}")
        if table:
            cmd.append("--table")
        if verbose:
            cmd.append("-vvv")
        if force:
            cmd.append("--force")
        proc = subprocess.run(cmd, input=sql_text.encode("utf-8"), stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT, cwd=str(DB_DIR))
        return proc.returncode, proc.stdout.decode("utf-8", errors="replace")
    finally:
        os.remove(cnf)


def run_file(path, database=None, **kw):
    return run_sql(Path(path).read_text(encoding="utf-8"), database=database, **kw)
