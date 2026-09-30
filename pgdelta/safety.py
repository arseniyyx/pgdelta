from __future__ import annotations

import re
from dataclasses import dataclass

import sqlparse

SAFE = "safe"
CAUTION = "caution"
DANGER = "danger"

_ORDER = {SAFE: 0, CAUTION: 1, DANGER: 2}

_CONCURRENTLY_HINT = "Build it with CREATE INDEX CONCURRENTLY so writes are not blocked."
_NOT_VALID_HINT = (
    "Add it as NOT VALID first, then run VALIDATE CONSTRAINT in a separate "
    "transaction; validation takes a weaker lock than an immediate check."
)
_NOT_NULL_HINT = (
    "Add a CHECK (col IS NOT NULL) NOT VALID, VALIDATE CONSTRAINT, then SET NOT NULL "
    "(fast once a validated constraint exists)."
)
_TYPE_HINT = "Add a new column, backfill in batches, then swap, to avoid a full-table rewrite."
_PK_HINT = (
    "Build a unique index with CREATE UNIQUE INDEX CONCURRENTLY, then ADD PRIMARY KEY USING INDEX."
)


@dataclass
class Risk:
    level: str
    reason: str
    safe_alternative: str | None = None


_OP_RISK = {
    "create_table": Risk(SAFE, "Creating a new table is safe."),
    "drop_table": Risk(DANGER, "Drops the table and all its data."),
    "drop_column": Risk(DANGER, "Drops the column and all its data."),
    "drop_not_null": Risk(SAFE, "Dropping NOT NULL is a metadata-only change."),
    "set_default": Risk(SAFE, "Setting a default is a metadata-only change."),
    "drop_default": Risk(SAFE, "Dropping a default is a metadata-only change."),
    "alter_type": Risk(
        DANGER, "Changing a column type rewrites the table under an exclusive lock.", _TYPE_HINT
    ),
    "set_not_null": Risk(
        DANGER, "SET NOT NULL scans the whole table under an exclusive lock.", _NOT_NULL_HINT
    ),
    "create_index": Risk(
        CAUTION,
        "Building an index blocks writes on the table until it finishes.",
        _CONCURRENTLY_HINT,
    ),
    "replace_index": Risk(
        CAUTION, "Rebuilding the index blocks writes while it is built.", _CONCURRENTLY_HINT
    ),
    "drop_index": Risk(
        CAUTION, "DROP INDEX takes a brief exclusive lock.", "Use DROP INDEX CONCURRENTLY."
    ),
    "add_fk": Risk(
        DANGER,
        "Adding a foreign key locks both tables and scans the child to validate it.",
        _NOT_VALID_HINT,
    ),
    "add_check": Risk(
        DANGER, "Adding a CHECK scans the whole table under a lock to validate it.", _NOT_VALID_HINT
    ),
    "replace_fk": Risk(
        DANGER, "Re-adding the foreign key validates it under a lock.", _NOT_VALID_HINT
    ),
    "replace_check": Risk(
        DANGER, "Re-adding the CHECK validates it under a lock.", _NOT_VALID_HINT
    ),
    "drop_fk": Risk(SAFE, "Dropping a constraint is fast."),
    "drop_check": Risk(SAFE, "Dropping a constraint is fast."),
    "drop_primary_key": Risk(
        CAUTION, "Dropping the primary key removes its unique index under a lock."
    ),
    "add_primary_key": Risk(
        DANGER,
        "Adding a primary key builds a unique index and scans the table under a lock.",
        _PK_HINT,
    ),
}


def classify_operation(kind: str, detail: dict | None = None) -> Risk:
    detail = detail or {}
    if kind == "add_column":
        if not detail.get("nullable", True):
            if detail.get("has_default"):
                return Risk(
                    CAUTION,
                    "Adding a NOT NULL column with a default is fast only if the default is "
                    "constant; a volatile default rewrites the table.",
                )
            return Risk(
                DANGER,
                "Adding a NOT NULL column with no default fails on a non-empty table.",
                "Add the column nullable, backfill, then add NOT NULL via a validated CHECK.",
            )
        return Risk(SAFE, "Adding a nullable column is a metadata-only change.")
    return _OP_RISK.get(kind, Risk(CAUTION, "Unclassified operation; review by hand."))


_RULES = [
    (re.compile(r"\bDROP\s+TABLE\b", re.I), Risk(DANGER, "Drops a table and all its data.")),
    (re.compile(r"\bDROP\s+COLUMN\b", re.I), Risk(DANGER, "Drops a column and all its data.")),
    (
        re.compile(r"\bSET\s+NOT\s+NULL\b", re.I),
        Risk(DANGER, "SET NOT NULL scans the whole table under an exclusive lock.", _NOT_NULL_HINT),
    ),
    (
        re.compile(r"\bALTER\s+COLUMN\b.*\bTYPE\b", re.I | re.S),
        Risk(
            DANGER, "Changing a column type rewrites the table under an exclusive lock.", _TYPE_HINT
        ),
    ),
    (
        re.compile(r"\bADD\b.*\bFOREIGN\s+KEY\b", re.I | re.S),
        Risk(
            DANGER,
            "Adding a foreign key locks both tables and scans the child to validate it.",
            _NOT_VALID_HINT,
        ),
    ),
    (
        re.compile(r"\bADD\b.*\bCHECK\b", re.I | re.S),
        Risk(
            DANGER, "Adding a CHECK scans the table under a lock to validate it.", _NOT_VALID_HINT
        ),
    ),
    (
        re.compile(r"\bADD\s+PRIMARY\s+KEY\b", re.I),
        Risk(
            DANGER,
            "Adding a primary key builds a unique index and scans the table under a lock.",
            _PK_HINT,
        ),
    ),
    (
        re.compile(r"\bCREATE\s+(UNIQUE\s+)?INDEX\b", re.I),
        Risk(
            CAUTION,
            "Building an index blocks writes on the table until it finishes.",
            _CONCURRENTLY_HINT,
        ),
    ),
    (
        re.compile(r"\bDROP\s+INDEX\b", re.I),
        Risk(CAUTION, "DROP INDEX takes a brief exclusive lock.", "Use DROP INDEX CONCURRENTLY."),
    ),
]


@dataclass
class LintFinding:
    statement: str
    risk: Risk


_ADD_COLUMN_NOT_NULL = re.compile(r"\bADD\s+COLUMN\b.*\bNOT\s+NULL\b", re.I | re.S)
_HAS_DEFAULT = re.compile(r"\bDEFAULT\b", re.I)


def _add_column_risk(flat: str) -> Risk | None:
    if not _ADD_COLUMN_NOT_NULL.search(flat):
        return None
    if _HAS_DEFAULT.search(flat):
        return Risk(
            CAUTION,
            "A NOT NULL column with a default is fast only if the default is constant; "
            "a volatile default rewrites the table.",
        )
    return Risk(
        DANGER,
        "Adds a NOT NULL column; fails on a non-empty table unless a constant default is given.",
        "Add the column nullable, backfill, then enforce NOT NULL.",
    )


def lint_sql(text: str) -> list[LintFinding]:
    findings: list[LintFinding] = []
    for raw in sqlparse.split(text):
        statement = sqlparse.format(raw, strip_comments=True).strip()
        if not statement:
            continue
        flat = " ".join(statement.split())
        candidates: list[Risk] = []
        if "concurrently" not in flat.lower():
            for pattern, risk in _RULES:
                if pattern.search(flat):
                    candidates.append(risk)
            add_col = _add_column_risk(flat)
            if add_col is not None:
                candidates.append(add_col)
        if candidates:
            best = max(candidates, key=lambda r: _ORDER[r.level])
        else:
            best = Risk(SAFE, "No blocking operation detected.")
        findings.append(LintFinding(statement=statement, risk=best))
    return findings
