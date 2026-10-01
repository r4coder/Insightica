"""
Integration coverage note
=========================
test_orchestration.py, test_gemini_service.py and the pure-logic tests in this folder run with
zero external dependencies: Gemini is replaced by FakeGemini (fakes.py) and DuckDB/Postgres are
replaced by SqliteEngine / an in-memory sqlite metadata DB. They run as part of `pytest` with no
network access and no API key, and are the primary regression suite.

test_api.py additionally boots the real FastAPI app with TestClient, real SQLAlchemy (SQLite) and
a fake Gemini client injected through dependency overrides - still no network and no API key.

None of the test files call the real Gemini API. To manually verify the live Gemini integration:
    1. `POST /api/v1/config/test-gemini` with a real key -> expect {"valid": true}.
    2. Complete /setup in the running frontend, upload sample_data/sales.csv, and ask a question.
This can only be done with a user-provided GEMINI_API_KEY, which is why it isn't part of the
automated suite.
"""
