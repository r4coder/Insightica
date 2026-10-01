"""Read-only SQL guard for LLM-generated DuckDB queries.

Token-based (not regex-on-raw-text) so keywords inside string literals or quoted identifiers
do not trigger false positives. Enforces: a single SELECT/WITH statement, no DDL/DML/admin
keywords, no file/system table functions, and that every table referenced is either an allowed
dataset table or a CTE defined in the query.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Tuple


class SQLValidationError(ValueError):
    """Raised when a query is not safe, read-only analytical SQL."""


MAX_SQL_LENGTH = 8000

FORBIDDEN_KEYWORDS = frozenset({
    "DROP", "DELETE", "UPDATE", "INSERT", "ALTER", "CREATE", "TRUNCATE", "REPLACE_INTO",
    "ATTACH", "DETACH", "COPY", "EXPORT", "IMPORT", "INSTALL", "LOAD", "PRAGMA", "CALL",
    "EXECUTE", "VACUUM", "CHECKPOINT", "GRANT", "REVOKE", "MERGE", "UPSERT", "USE", "SET",
    "INTO", "PREPARE", "DEALLOCATE", "COMMIT", "ROLLBACK", "BEGIN", "FORCE", "RESET",
})
_FORBIDDEN_FUNCTIONS = re.compile(
    r"^(read_\w*|\w*_scan|parquet_\w+|duckdb_\w+|pragma_\w+|sqlite_\w+|glob|query|query_table|"
    r"sniff_csv|getenv|current_setting|which_secret|list_secrets|write_\w+|copy_\w+|"
    r"load_extension|install_extension|shell|system)$",
    re.IGNORECASE,
)
_ALLOWED_TABLE_FUNCTIONS = frozenset({"UNNEST", "GENERATE_SERIES", "RANGE"})
_FROM_INSIDE_FUNCTIONS = frozenset({"EXTRACT", "TRIM", "SUBSTRING", "OVERLAY", "POSITION", "DATE_PART"})
_CLAUSES = frozenset({"SELECT", "WHERE", "GROUP", "ORDER", "HAVING", "LIMIT", "QUALIFY", "WINDOW",
                      "ON", "USING", "UNION", "INTERSECT", "EXCEPT", "OFFSET"})

_TOKEN_RE = re.compile(
    r"""
    (?P<ws>\s+)
   |(?P<lc>--[^\n]*)
   |(?P<bc>/\*.*?\*/)
   |(?P<str>'(?:[^']|'')*')
   |(?P<qid>"(?:[^"]|"")*")
   |(?P<num>\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)
   |(?P<word>[A-Za-z_][A-Za-z0-9_$]*)
   |(?P<sym><=|>=|<>|!=|\|\||::|[(),.;*=<>+\-/%\[\]:?|&^~@#$])
    """,
    re.VERBOSE | re.DOTALL,
)

Token = Tuple[str, str]


def _tokenize(sql: str) -> List[Token]:
    tokens: List[Token] = []
    pos = 0
    while pos < len(sql):
        match = _TOKEN_RE.match(sql, pos)
        if match is None:
            raise SQLValidationError(f"Unrecognized or unterminated token near position {pos}.")
        kind = match.lastgroup or ""
        text = match.group()
        pos = match.end()
        if kind in ("lc", "bc"):
            continue
        tokens.append(("ws", " ") if kind == "ws" else (kind, text))
    return [t for i, t in enumerate(tokens) if not (t[0] == "ws" and (i == 0 or i == len(tokens) - 1))]


def _unquote(kind: str, text: str) -> str:
    return text[1:-1].replace('""', '"') if kind == "qid" else text


def validate_sql(sql: str, allowed_tables: Iterable[str]) -> str:
    """Return the cleaned SQL (comments stripped, trailing ';' removed) or raise SQLValidationError."""
    if not isinstance(sql, str) or not sql.strip():
        raise SQLValidationError("SQL is empty.")
    if len(sql) > MAX_SQL_LENGTH:
        raise SQLValidationError(f"SQL exceeds {MAX_SQL_LENGTH} characters.")
    allowed = {t.lower() for t in allowed_tables}

    all_tokens = _tokenize(sql)
    while all_tokens and (all_tokens[-1] == ("sym", ";") or all_tokens[-1][0] == "ws"):
        all_tokens.pop()
    tokens = [t for t in all_tokens if t[0] != "ws"]
    if not tokens:
        raise SQLValidationError("SQL is empty.")
    if any(t == ("sym", ";") for t in tokens):
        raise SQLValidationError("Only a single SQL statement is allowed.")

    first = tokens[0][1].upper() if tokens[0][0] == "word" else ""
    if first not in ("SELECT", "WITH"):
        raise SQLValidationError("Only SELECT queries (optionally starting with WITH) are allowed.")

    depth = 0
    for kind, text in tokens:
        if kind == "sym" and text == "(":
            depth += 1
        elif kind == "sym" and text == ")":
            depth -= 1
            if depth < 0:
                raise SQLValidationError("Unbalanced parentheses.")
    if depth != 0:
        raise SQLValidationError("Unbalanced parentheses.")

    for kind, text in tokens:
        if kind == "word" and text.upper() in FORBIDDEN_KEYWORDS:
            raise SQLValidationError(f"Keyword {text.upper()} is not allowed (read-only analytics only).")

    ctes = set()
    for i in range(len(tokens) - 2):
        (k0, t0), (k1, t1), (k2, t2) = tokens[i], tokens[i + 1], tokens[i + 2]
        if k0 in ("word", "qid") and k1 == "word" and t1.upper() == "AS":
            if t2 == "(" or (k2 == "word" and t2.upper() in ("MATERIALIZED", "NOT")):
                ctes.add(_unquote(k0, t0).lower())

    for i, (kind, text) in enumerate(tokens[:-1]):
        if kind == "word" and tokens[i + 1] == ("sym", "(") and _FORBIDDEN_FUNCTIONS.match(text):
            raise SQLValidationError(f"Function {text} is not allowed.")

    _check_table_references(tokens, allowed, ctes)

    parts = []
    for kind, text in all_tokens:
        parts.append(" " if kind == "ws" else text)
    return "".join(parts).strip()


def _check_table_references(tokens: List[Token], allowed: set, ctes: set) -> None:
    stack = [{"fn": None, "clause": None, "expect": False}]
    i = 0
    while i < len(tokens):
        kind, text = tokens[i]
        frame = stack[-1]
        up = text.upper() if kind == "word" else ""

        if frame["expect"]:
            frame["expect"] = False
            if kind == "str":
                raise SQLValidationError("Reading from files or string paths is not allowed.")
            if kind in ("word", "qid"):
                parts = [_unquote(kind, text)]
                j = i
                while j + 2 < len(tokens) and tokens[j + 1] == ("sym", ".") and tokens[j + 2][0] in ("word", "qid"):
                    parts.append(_unquote(*tokens[j + 2]))
                    j += 2
                if j + 1 < len(tokens) and tokens[j + 1] == ("sym", "("):
                    if len(parts) == 1 and parts[0].upper() in _ALLOWED_TABLE_FUNCTIONS:
                        i = j + 1
                        continue
                    raise SQLValidationError(f"Table function {'.'.join(parts)}() is not allowed.")
                name = parts[-1].lower()
                qualified_ok = len(parts) == 1 or (len(parts) == 2 and parts[0].lower() == "main")
                if not qualified_ok or (name not in allowed and not (len(parts) == 1 and name in ctes)):
                    raise SQLValidationError(
                        f"Unknown or disallowed table '{'.'.join(parts)}'. Allowed tables: {sorted(allowed)}."
                    )
                i = j + 1
                continue

        if kind == "sym" and text == "(":
            prev = tokens[i - 1] if i > 0 else ("", "")
            stack.append({"fn": prev[1].upper() if prev[0] == "word" else None, "clause": None, "expect": False})
        elif kind == "sym" and text == ")":
            stack.pop()
        elif up in ("FROM", "JOIN"):
            prev_up = tokens[i - 1][1].upper() if i > 0 and tokens[i - 1][0] == "word" else ""
            inside_fn = frame["fn"] in _FROM_INSIDE_FUNCTIONS
            if not inside_fn and prev_up != "DISTINCT":
                if up == "FROM":
                    frame["clause"] = "FROM"
                frame["expect"] = True
        elif up in _CLAUSES:
            frame["clause"] = up
        elif kind == "sym" and text == "," and frame["clause"] == "FROM":
            frame["expect"] = True
        i += 1


def wrap_with_limit(sql: str, limit: int) -> str:
    """Wrap validated SQL so the engine can never return more than limit + 1 rows."""
    return f"SELECT * FROM (\n{sql}\n) AS _q LIMIT {int(limit) + 1}"
