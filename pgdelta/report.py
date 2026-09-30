from __future__ import annotations

from pgdelta.diff import Operation
from pgdelta.safety import CAUTION, DANGER, SAFE, Risk, classify_operation

_COLOR = {DANGER: "\033[31m", CAUTION: "\033[33m", SAFE: "\033[32m"}
_RESET = "\033[0m"
_RANK = {SAFE: 0, CAUTION: 1, DANGER: 2}


def _tag(level: str, color: bool) -> str:
    label = f"[{level.upper()}]"
    return f"{_COLOR[level]}{label}{_RESET}" if color else label


def max_level(levels: list[str]) -> str:
    return max(levels, key=lambda lvl: _RANK[lvl], default=SAFE)


def _risk_of(op: Operation) -> Risk:
    return classify_operation(op.kind, op.detail)


def render_diff(
    ops: list[Operation],
    from_label: str,
    to_label: str,
    color: bool = True,
    sql_only: bool = False,
) -> str:
    if not ops:
        return "No differences: the schemas already match."

    lines: list[str] = []
    counts = {SAFE: 0, CAUTION: 0, DANGER: 0}

    if sql_only:
        lines.append(f"-- pgdelta migration: {from_label} -> {to_label}")
        for op in ops:
            risk = _risk_of(op)
            counts[risk.level] += 1
            lines.append("")
            lines.append(f"-- [{risk.level.upper()}] {risk.reason}")
            if risk.safe_alternative:
                lines.append(f"-- safer: {risk.safe_alternative}")
            lines.append(op.sql)
    else:
        lines.append(f"pgdelta — changes to apply to {from_label} so it matches {to_label}")
        lines.append("")
        for op in ops:
            risk = _risk_of(op)
            counts[risk.level] += 1
            for i, stmt in enumerate(op.sql.splitlines()):
                prefix = f"  {_tag(risk.level, color)} " if i == 0 else "      "
                lines.append(f"{prefix}{stmt}")
            lines.append(f"      {risk.reason}")
            if risk.safe_alternative:
                lines.append(f"      safer: {risk.safe_alternative}")
            lines.append("")

    prefix = "-- " if sql_only else ""
    if sql_only:
        lines.append("")
    lines.append(
        f"{prefix}Summary: {len(ops)} operation(s) — "
        f"{counts[DANGER]} danger, {counts[CAUTION]} caution, {counts[SAFE]} safe"
    )
    return "\n".join(lines)


def diff_to_dicts(ops: list[Operation]) -> list[dict]:
    out = []
    for op in ops:
        risk = _risk_of(op)
        out.append(
            {
                "kind": op.kind,
                "table": op.table,
                "sql": op.sql,
                "risk": risk.level,
                "reason": risk.reason,
                "safe_alternative": risk.safe_alternative,
            }
        )
    return out
