"""Deterministic verification of the Report Agent's numeric claims against computed evidence.

The rules are intentionally strict and explainable:
  * every cited evidence ref must exist in the evidence store and be numeric;
  * the claimed value must match the computed value (1% relative, or 0.5 points for percentages);
  * every percentage / currency-style number written in prose must be backed by a cited value,
    within rounding implied by how many decimals were written ("18%" backs 17.8, "35%" does not);
  * a sentence must not state the opposite direction (e.g. "grew") of the computed sign.
"""
from __future__ import annotations

import math
import re
from typing import Any, Dict, List, Tuple

from app.validation.evidence import resolve

_SCALE = {"k": 1e3, "thousand": 1e3, "m": 1e6, "mn": 1e6, "million": 1e6, "b": 1e9, "bn": 1e9, "billion": 1e9}
_PCT = re.compile(r"(?<![\w.])[+\-−–]?\s?(\d[\d,]*(?:\.(\d+))?)\s?%")
_AMOUNT = re.compile(
    r"(?<![\w.])[+\-−–]?\s?([$€£₹]?)\s?(\d[\d,]*(?:\.(\d+))?)\s?(billion|million|thousand|bn|mn|[KkMmBb])?(?![\w%])"
)
_DOWN = re.compile(r"\b(declin\w*|decreas\w*|drop\w*|fell|fall\w*|reduc\w*|shrank|shrink\w*|contract\w*|lower|down)\b", re.I)
_UP = re.compile(r"\b(increas\w*|grew|grow\w*|rise\w*|rose|higher|gain\w*|expand\w*|improv\w*|up)\b", re.I)
_SHARE_WORDS = re.compile(r"\b(share|account\w*|contribut\w*|portion|make[s]? up|responsible|driv\w*)\b", re.I)


def extract_numeric_claims(text: str) -> List[Dict[str, Any]]:
    """Percentages and currency/scaled numbers written in prose. Bare numbers (years, counts) are ignored."""
    claims: List[Dict[str, Any]] = []
    for m in _PCT.finditer(text or ""):
        decimals = len(m.group(2) or "")
        claims.append({"raw": m.group(0).strip(), "kind": "percent", "value": abs(float(m.group(1).replace(",", ""))),
                       "tol": 0.5 * 10 ** (-decimals)})
    for m in _AMOUNT.finditer(text or ""):
        symbol, digits, decimals, suffix = m.group(1), m.group(2), m.group(3) or "", m.group(4)
        if not symbol and not suffix:
            continue
        scale = _SCALE.get((suffix or "").lower(), 1.0)
        claims.append({"raw": m.group(0).strip(), "kind": "amount", "value": abs(float(digits.replace(",", ""))) * scale,
                       "tol": 0.5 * 10 ** (-len(decimals)) * scale})
    return claims


def values_match(claimed: Any, actual: Any, unit: str) -> bool:
    """Compare magnitudes: sign/direction is judged separately from the wording."""
    try:
        c, a = abs(float(claimed)), abs(float(actual))
    except (TypeError, ValueError):
        return False
    if not (math.isfinite(c) and math.isfinite(a)):
        return False
    if unit == "percent" and abs(c - a) <= 0.5:
        return True
    return math.isclose(c, a, rel_tol=0.01, abs_tol=0.005)


def _supported(claim: Dict[str, Any], actuals: List[Tuple[float, str]]) -> bool:
    for value, unit in actuals:
        if claim["kind"] == "percent":
            cand = abs(value) * 100 if unit == "ratio" else abs(value) if unit in ("percent", "number") else None
        else:
            cand = abs(value) if unit in ("currency", "number") else None
        if cand is not None and abs(cand - claim["value"]) <= claim["tol"] + 1e-9:
            return True
    return False


def direction_conflict(statement: str, pct_actuals: List[float]) -> bool:
    if not pct_actuals or _SHARE_WORDS.search(statement):
        return False
    down, up = bool(_DOWN.search(statement)), bool(_UP.search(statement))
    if down and not up and all(v > 0 for v in pct_actuals):
        return True
    if up and not down and all(v < 0 for v in pct_actuals):
        return True
    return False


def validate_report(report: Dict[str, Any], store: Dict[str, Any]) -> Dict[str, Any]:
    """Check a drafted report. Returns {valid, issues[], finding_ok[]}."""
    issues: List[Dict[str, Any]] = []
    finding_ok: List[bool] = []
    global_actuals: List[Tuple[float, str]] = []
    findings = report.get("key_findings", [])
    if not findings:
        issues.append({"scope": "report", "index": None, "message": "The report has no key findings."})

    for i, f in enumerate(findings):
        problems: List[str] = []
        actuals: List[Tuple[float, str]] = []
        evidence = f.get("evidence", [])
        if f.get("kind") in ("observed", "calculated") and not evidence:
            problems.append("an observed/calculated finding must cite at least one evidence ref")
        for ev in evidence:
            ref, unit = ev.get("ref", ""), ev.get("unit", "number")
            found, actual = resolve(store, ref)
            if not found:
                problems.append(f"evidence ref '{ref}' does not exist in the computed results")
            elif not isinstance(actual, (int, float)):
                problems.append(f"evidence ref '{ref}' is not numeric")
            elif not values_match(ev.get("claimed_value"), actual, unit):
                problems.append(f"claimed {ev.get('claimed_value')} for '{ref}' but the computed value is {actual:.6g}")
            else:
                actuals.append((float(actual), unit))
        statement = f.get("statement", "")
        pool = actuals if f.get("kind") in ("observed", "calculated") else (actuals + global_actuals)
        for claim in extract_numeric_claims(statement):
            if not _supported(claim, pool):
                problems.append(f"the number '{claim['raw']}' in the statement is not backed by cited evidence")
        pct_values = [v for v, u in actuals if u == "percent"]
        if direction_conflict(statement, pct_values):
            problems.append("the wording states the opposite direction of the computed percentage")
        global_actuals.extend(actuals)
        finding_ok.append(not problems)
        for p in problems:
            issues.append({"scope": "finding", "index": i, "message": p})

    for scope in ("executive_summary", "detailed_analysis", "conclusion"):
        for claim in extract_numeric_claims(report.get(scope, "")):
            if not _supported(claim, global_actuals):
                issues.append({"scope": scope, "index": None,
                               "message": f"the number '{claim['raw']}' is not backed by any verified evidence"})
    return {"valid": not issues, "issues": issues, "finding_ok": finding_ok}
