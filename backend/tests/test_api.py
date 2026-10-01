"""Full-stack API tests: real FastAPI + real SQLAlchemy(SQLite) + real DuckDB, fake Gemini.
Requires `pip install -r requirements.txt` (network needed once, to install packages) - these are
NOT run inside the sandbox that built this repo (no network egress there); run them with:
    cd backend && pytest tests/test_api.py -v
"""
import io
import os

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("duckdb")

os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("DUCKDB_PATH", ":memory:")
os.environ.setdefault("DATA_DIR", "/tmp/madata-test")

from fastapi.testclient import TestClient

from app.api import deps as api_deps
from app.gemini.service import GeminiService
from app.main import create_app
from fakes import FakeGemini

SALES_CSV = (
    "order_date,region,revenue\n"
    "2024-04-01,West,300\n2024-05-01,West,300\n2024-06-01,East,400\n"
    "2024-07-01,West,300\n2024-08-01,East,250\n2024-09-01,East,250\n"
)
PLAN = {"resolved_question": "What was total revenue?", "intent": "descriptive", "metric": "revenue", "time_dimension": "none",
        "date_column": "", "target_period": "", "comparison_period": "", "dimensions": [], "analysis_tasks": ["sum revenue"],
        "needs_sql": True, "needs_statistics": False, "needs_visualization": False, "visualizations": []}
SQL = {"queries": [{"purpose": "total revenue", "sql": "SELECT SUM(revenue) AS total_revenue FROM {table}"}]}
REPORT = lambda total: {"title": "Total revenue", "executive_summary": f"Total revenue was ${total:.0f}.",
                        "key_findings": [{"statement": f"Total revenue was ${total:.0f}.", "kind": "observed",
                                          "evidence": [{"ref": "sql0[0].total_revenue", "claimed_value": total, "unit": "currency"}]}],
                        "detailed_analysis": "", "conclusion": "", "methodology": "Sum aggregation over the whole table."}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/app.db")
    monkeypatch.setenv("DUCKDB_PATH", str(tmp_path / "analytics.duckdb"))
    from app.core import config as config_mod
    config_mod.get_settings.cache_clear()
    app = create_app()
    with TestClient(app) as c:
        yield c


def test_health_ok(client):
    assert client.get("/api/v1/health").json()["status"] == "ok"


def test_setup_flow_requires_valid_key_then_creates_session(client, monkeypatch):
    def fake_check(key, model):
        return (key == "good-key", "ok" if key == "good-key" else "invalid_key")
    monkeypatch.setattr("app.api.routes.config.check_api_key", fake_check)

    r = client.post("/api/v1/config/test-gemini", json={"api_key": "bad-key"})
    assert r.status_code == 200 and r.json()["valid"] is False

    r = client.post("/api/v1/config/session", json={"api_key": "bad-key"})
    assert r.status_code == 401 and r.json()["code"] == "invalid_key"

    r = client.post("/api/v1/config/session", json={"api_key": "good-key"})
    assert r.status_code == 200 and r.json()["connected"] is True
    assert "gemini_session" in r.cookies
    assert "good-key" not in r.text  # the key itself is never echoed back

    r = client.get("/api/v1/config/session")
    assert r.json()["connected"] is True

    r = client.post("/api/v1/config/logout")
    assert r.json()["connected"] is False
    assert client.get("/api/v1/config/session").json()["connected"] is False


def test_dataset_upload_rejects_bad_files_and_accepts_csv(client):
    r = client.post("/api/v1/datasets", files={"file": ("bad.exe", io.BytesIO(b"MZ..."), "application/octet-stream")})
    assert r.status_code == 415

    r = client.post("/api/v1/datasets", files={"file": ("sales.csv", io.BytesIO(SALES_CSV.encode()), "text/csv")})
    assert r.status_code == 201
    body = r.json()
    assert body["row_count"] == 6 and body["column_count"] == 3

    ds_id = body["id"]
    assert client.get(f"/api/v1/datasets/{ds_id}").json()["name"] == "sales.csv"
    assert client.get(f"/api/v1/datasets/{ds_id}/profile").json()["rows"] == 6
    assert any(d["id"] == ds_id for d in client.get("/api/v1/datasets").json())

    assert client.get("/api/v1/datasets/does-not-exist").status_code == 404


def test_analysis_requires_gemini_session(client):
    upload = client.post("/api/v1/datasets", files={"file": ("s.csv", io.BytesIO(SALES_CSV.encode()), "text/csv")})
    r = client.post("/api/v1/analysis", json={"dataset_id": upload.json()["id"], "question": "total revenue?"})
    assert r.status_code == 401 and r.json()["code"] == "session_expired"


def test_full_analysis_lifecycle_with_fake_gemini(client, monkeypatch):
    monkeypatch.setattr("app.api.routes.config.check_api_key", lambda key, model: (True, "ok"))
    client.post("/api/v1/config/session", json={"api_key": "good-key"})

    upload = client.post("/api/v1/datasets", files={"file": ("s.csv", io.BytesIO(SALES_CSV.encode()), "text/csv")})
    ds_id = upload.json()["id"]
    table = f"s_{ds_id.replace('-', '')[:8]}"

    fake = FakeGemini({"ManagerPlan": [PLAN], "SQLPlan": [{"queries": [{"purpose": "total revenue",
                       "sql": SQL["queries"][0]["sql"].format(table=table)}]}], "ChartPlan": [], "ReportDraft": [REPORT(1800.0)]})
    client.app.dependency_overrides[api_deps.get_gemini_service] = lambda: fake

    r = client.post("/api/v1/analysis", json={"dataset_id": ds_id, "question": "What was total revenue?"})
    assert r.status_code == 202
    analysis_id = r.json()["id"]

    import time
    for _ in range(50):
        got = client.get(f"/api/v1/analysis/{analysis_id}").json()
        if got["status"] != "running":
            break
        time.sleep(0.05)
    assert got["status"] == "completed", got.get("error")
    assert got["result"]["report"]["key_findings"][0]["evidence"][0]["actual_value"] == 1800.0

    history = client.get("/api/v1/analysis", params={"dataset_id": ds_id}).json()
    assert history and history[0]["id"] == analysis_id and "result" not in history[0]
    assert client.get(f"/api/v1/analysis/{analysis_id}").json()["session_id"]

    client.app.dependency_overrides.clear()


def test_delete_dataset_removes_it(client):
    upload = client.post("/api/v1/datasets", files={"file": ("s.csv", io.BytesIO(SALES_CSV.encode()), "text/csv")})
    ds_id = upload.json()["id"]
    assert client.delete(f"/api/v1/datasets/{ds_id}").status_code == 204
    assert client.get(f"/api/v1/datasets/{ds_id}").status_code == 404


def test_new_session_row_is_committed_before_dependent_rows(client):
    """Regression test for a real bug: analysis_service.create() linked AnalysisResult to a brand-new
    AnalysisSession by copying the id as a plain string, with no SQLAlchemy relationship() between them.
    Without an explicit db.flush() of the new session first, nothing guarantees the session INSERT
    happens before the dependent AnalysisResult/AnalysisMessage INSERTs in the same flush - SQLite
    (without PRAGMA foreign_keys=ON) silently allowed the wrong order, while PostgreSQL correctly
    raised ForeignKeyViolation. See database/session.py's sqlite PRAGMA for why this test can catch it."""
    upload = client.post("/api/v1/datasets", files={"file": ("s.csv", io.BytesIO(SALES_CSV.encode()), "text/csv")})
    ds_id = upload.json()["id"]

    monkeypatch_target = "app.api.routes.config.check_api_key"
    import unittest.mock as mock
    with mock.patch(monkeypatch_target, lambda key, model: (True, "ok")):
        client.post("/api/v1/config/session", json={"api_key": "good-key"})

    fake = FakeGemini({"ManagerPlan": [PLAN], "SQLPlan": [{"queries": []}], "ChartPlan": [], "ReportDraft": [REPORT(0.0)]})
    client.app.dependency_overrides[api_deps.get_gemini_service] = lambda: fake

    # No session_id passed -> service.create() must create AND commit a new AnalysisSession row
    # such that the AnalysisResult row referencing it does not violate the foreign key.
    r = client.post("/api/v1/analysis", json={"dataset_id": ds_id, "question": "What was total revenue?"})
    assert r.status_code == 202, r.text  # a 500 here means the ordering bug has regressed
    assert r.json()["session_id"]

    client.app.dependency_overrides.clear()
