from app.validation.claims import direction_conflict, extract_numeric_claims, validate_report, values_match
from app.validation.evidence import build_evidence_store, render_for_prompt, resolve

SQL = [{"id": "sql0", "purpose": "revenue by quarter", "columns": ["quarter", "revenue", "pct_change"], "row_count": 2, "error": None,
        "rows": [{"quarter": "2024-Q2", "revenue": 1000000.0, "pct_change": None},
                 {"quarter": "2024-Q3", "revenue": 821543.2, "pct_change": -17.8457}]}]
TOOLS = [{"id": "tool1", "tool": "contribution_analysis", "args": {}, "error": None,
          "result": {"total": {"pct_change": -17.8457, "delta": -178456.8}, "table": [{"dimension_value": "Enterprise", "share_of_total_change_pct": 61.2}]}}]


def store():
    return build_evidence_store(SQL, TOOLS)


def report(statement, evidence, kind="calculated", summary="", detail="", conclusion=""):
    return {"executive_summary": summary, "detailed_analysis": detail, "conclusion": conclusion,
            "key_findings": [{"statement": statement, "kind": kind, "evidence": evidence}]}


def test_evidence_store_refs_resolve():
    s = store()
    assert resolve(s, "sql0[1].pct_change") == (True, -17.8457)
    assert resolve(s, "tool1.total.delta")[0] is True
    assert resolve(s, "tool1.table[0].dimension_value") == (True, "Enterprise")
    assert resolve(s, "sql0[9].revenue")[0] is False
    assert resolve(s, "SQL0[1].REVENUE")[0] is True  # case-insensitive fallback


def test_prompt_rendering_contains_citable_refs():
    text = render_for_prompt(SQL, TOOLS)
    assert "sql0[ROW].column" in text and "tool1.total.pct_change = -17.8457" in text


def test_extract_numeric_claims_ignores_years_and_quarters():
    claims = extract_numeric_claims("In 2024 Q3, revenue fell 17.8% to $821,543 across 4 regions; that is $0.8M.")
    kinds = sorted((c["kind"], c["raw"]) for c in claims)
    assert ("percent", "17.8%") in kinds and any(k == "amount" for k, _ in kinds)
    assert not any(c["raw"] in ("2024", "4", "3") for c in claims)


def test_correct_claim_passes_and_rounding_is_tolerated():
    ev = [{"ref": "sql0[1].pct_change", "claimed_value": -17.8, "unit": "percent"}]
    assert validate_report(report("Revenue declined by 17.8% in Q3.", ev), store())["valid"]
    assert validate_report(report("Revenue declined by about 18% in Q3.", ev), store())["valid"]


def test_fabricated_number_is_rejected():
    """The spec's example: report says 35% while the computed value is 17.8%."""
    ev = [{"ref": "sql0[1].pct_change", "claimed_value": -35.0, "unit": "percent"}]
    out = validate_report(report("Revenue declined by 35% in Q3.", ev), store())
    assert not out["valid"] and out["finding_ok"] == [False]
    assert any("computed value" in i["message"] for i in out["issues"])


def test_number_in_text_must_match_cited_evidence_even_if_evidence_is_right():
    ev = [{"ref": "sql0[1].pct_change", "claimed_value": -17.8457, "unit": "percent"}]
    out = validate_report(report("Revenue declined by 35% in Q3.", ev), store())
    assert not out["valid"]
    assert any("not backed" in i["message"] for i in out["issues"])


def test_nonexistent_ref_and_missing_evidence_rejected():
    out = validate_report(report("Revenue fell.", [{"ref": "sql9[0].x", "claimed_value": 1, "unit": "number"}]), store())
    assert not out["valid"] and "does not exist" in out["issues"][0]["message"]
    assert not validate_report(report("Revenue fell.", []), store())["valid"]
    assert validate_report(report("Patterns look seasonal.", [], kind="interpretation"), store())["valid"]


def test_direction_check():
    assert direction_conflict("Revenue grew 17.8%", [-17.8])
    assert not direction_conflict("Revenue fell 17.8%", [-17.8])
    assert not direction_conflict("Enterprise accounted for 61.2% of the decline", [61.2])


def test_summary_numbers_must_be_backed_by_verified_evidence():
    ev = [{"ref": "sql0[1].pct_change", "claimed_value": -17.8, "unit": "percent"}]
    good = report("Revenue declined by 17.8%.", ev, summary="Revenue fell 17.8% in Q3.")
    bad = report("Revenue declined by 17.8%.", ev, summary="Revenue fell 42% in Q3.")
    assert validate_report(good, store())["valid"]
    out = validate_report(bad, store())
    assert not out["valid"] and out["issues"][0]["scope"] == "executive_summary"


def test_currency_rounding_supported():
    ev = [{"ref": "sql0[1].revenue", "claimed_value": 821543.2, "unit": "currency"}]
    assert validate_report(report("Q3 revenue was $821,543.", ev), store())["valid"]
    assert validate_report(report("Q3 revenue was $0.8M.", ev), store())["valid"]
    assert not validate_report(report("Q3 revenue was $1.2M.", ev), store())["valid"]


def test_values_match_uses_magnitude():
    assert values_match(-17.8, 17.8457, "percent")
    assert not values_match(35, 17.8457, "percent")
