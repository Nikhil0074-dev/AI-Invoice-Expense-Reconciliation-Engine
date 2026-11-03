import os
import subprocess
import sys

from sqlalchemy import create_engine, inspect

BACKEND = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def run(args, db_url):
    env = {**os.environ, "DATABASE_URL": db_url}
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, env=env, capture_output=True, text=True)


def test_migrations_apply_match_models_and_downgrade(tmp_path):
    url = f"sqlite:///{tmp_path}/mig.db"
    up = run(["upgrade", "head"], url)
    assert up.returncode == 0, up.stderr
    tables = set(inspect(create_engine(url)).get_table_names())
    assert {"users", "organizations", "documents", "invoices", "bank_transactions", "reconciliation_allocations",
            "duplicate_flags", "audit_logs", "exports", "processing_jobs"} <= tables
    check = run(["check"], url)  # models and migrations must not drift
    assert check.returncode == 0, check.stdout + check.stderr
    assert run(["downgrade", "base"], url).returncode == 0


def test_upgrade_creates_missing_sqlite_directory(tmp_path):
    """Fresh-checkout quick start: `alembic upgrade head` must work when ./data does not exist yet."""
    url = f"sqlite:///{tmp_path}/not/yet/created/app.db"
    res = run(["upgrade", "head"], url)
    assert res.returncode == 0, res.stderr
    assert (tmp_path / "not" / "yet" / "created" / "app.db").exists()
