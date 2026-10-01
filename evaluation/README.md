# Evaluation

`scripts/run_eval.py` runs the questions in `datasets/questions.json` against the real multi-agent
graph (`app.orchestration.runner.run_analysis`) using `sample_data/sales.csv`, and checks each
result against simple, objective criteria — it does not grade "how good" an explanation reads,
only whether the pipeline produced the kind of evidence the question requires.

## Modes

- **Default (mocked Gemini):** deterministic scripted responses drive the graph exactly like
  `backend/tests/test_orchestration.py` does. No API key or network needed. This checks that the
  *pipeline* (SQL execution, tool calls, chart building, validation, retries) works end to end.
- **`--live`:** uses a real `GEMINI_API_KEY` and the real Gemini model, so the Manager/SQL/Analyst/
  Visualization/Report agents make their own real decisions. This is the meaningful check of
  whether Gemini + the tools together answer correctly; it costs real API calls.

## Running

```bash
cd evaluation
python scripts/run_eval.py                 # mocked, offline
GEMINI_API_KEY=... python scripts/run_eval.py --live   # real Gemini
```

Results are written to `results/latest.json` with a pass/fail per check per question, plus the
raw agent trace and any validator issues, so a failure can be inspected rather than just counted.

**No scores in this README are fabricated or pre-filled** — running the script is required to
produce a `results/latest.json`; none is committed, since results in mocked mode are trivially
the same every run and live-mode results depend on a paid API key the repository does not have.
