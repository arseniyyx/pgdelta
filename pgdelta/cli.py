from __future__ import annotations

import argparse
import json
import sys

from pgdelta import report
from pgdelta.diff import diff
from pgdelta.introspect import introspect
from pgdelta.report import max_level
from pgdelta.safety import DANGER, SAFE, lint_sql


def cmd_diff(args) -> int:
    src = introspect(args.from_dsn, args.schema)
    dst = introspect(args.to_dsn, args.schema)
    ops = diff(src, dst)

    if args.json:
        print(json.dumps(report.diff_to_dicts(ops), indent=2))
    else:
        print(
            report.render_diff(
                ops,
                _label(args.from_dsn),
                _label(args.to_dsn),
                color=not args.no_color,
                sql_only=args.sql,
            )
        )

    return _exit_code([r["risk"] for r in report.diff_to_dicts(ops)], args.fail_on)


def cmd_lint(args) -> int:
    with open(args.file) as fh:
        text = fh.read()
    findings = lint_sql(text)

    if args.json:
        print(
            json.dumps(
                [
                    {
                        "statement": f.statement,
                        "risk": f.risk.level,
                        "reason": f.risk.reason,
                        "safe_alternative": f.risk.safe_alternative,
                    }
                    for f in findings
                ],
                indent=2,
            )
        )
    else:
        color = not args.no_color
        for f in findings:
            head = f.statement.splitlines()[0]
            print(f"{report._tag(f.risk.level, color)} {head}")
            print(f"    {f.risk.reason}")
            if f.risk.safe_alternative:
                print(f"    safer: {f.risk.safe_alternative}")
        counts = {level: 0 for level in (SAFE, "caution", DANGER)}
        for f in findings:
            counts[f.risk.level] += 1
        print(
            f"\nSummary: {len(findings)} statement(s) — "
            f"{counts[DANGER]} danger, {counts['caution']} caution, {counts[SAFE]} safe"
        )

    return _exit_code([f.risk.level for f in findings], args.fail_on)


def _label(dsn: str) -> str:
    from urllib.parse import urlparse

    p = urlparse(dsn)
    return f"{p.hostname or ''}/{p.path.lstrip('/')}" if p.scheme else dsn


def _exit_code(levels: list[str], fail_on: str) -> int:
    worst = max_level(levels)
    threshold = {"safe": SAFE, "caution": "caution", "danger": DANGER, "never": None}[fail_on]
    if threshold is None:
        return 0
    rank = {SAFE: 0, "caution": 1, DANGER: 2}
    return 1 if rank[worst] >= rank[threshold] else 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pgdelta", description="PostgreSQL schema diff and migration linter."
    )
    p.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    p.add_argument(
        "--fail-on",
        choices=["safe", "caution", "danger", "never"],
        default="never",
        help="exit non-zero when a finding at or above this level is present",
    )
    sub = p.add_subparsers(dest="command", required=True)

    pd = sub.add_parser("diff", help="diff two schemas and show the migration")
    pd.add_argument("--from", dest="from_dsn", required=True, help="current database DSN")
    pd.add_argument("--to", dest="to_dsn", required=True, help="desired database DSN")
    pd.add_argument("--schema", default="public", help="schema to compare (default: public)")
    pd.add_argument("--sql", action="store_true", help="print runnable SQL with risk comments")
    pd.add_argument("--json", action="store_true", help="print findings as JSON")
    pd.set_defaults(func=cmd_diff)

    pl = sub.add_parser("lint", help="lint a migration .sql file for risky operations")
    pl.add_argument("file", help="path to a .sql file")
    pl.add_argument("--json", action="store_true", help="print findings as JSON")
    pl.set_defaults(func=cmd_lint)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # noqa: BLE001
        print(f"pgdelta: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
