from __future__ import annotations

from dataclasses import dataclass, field

from pgdelta.model import Schema, Table


@dataclass
class Operation:
    kind: str
    table: str
    sql: str
    detail: dict = field(default_factory=dict)


def _qi(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _qname(schema: str, name: str) -> str:
    return f"{_qi(schema)}.{_qi(name)}"


def _column_clause(col) -> str:
    clause = f"{_qi(col.name)} {col.type}"
    if not col.nullable:
        clause += " NOT NULL"
    if col.default is not None:
        clause += f" DEFAULT {col.default}"
    return clause


def _create_table(schema: str, table: Table) -> Operation:
    lines = [_column_clause(c) for c in table.columns.values()]
    if table.primary_key:
        pk = ", ".join(_qi(c) for c in table.primary_key)
        lines.append(f"PRIMARY KEY ({pk})")
    body = ",\n    ".join(lines)
    sql = f"CREATE TABLE {_qname(schema, table.name)} (\n    {body}\n);"
    return Operation("create_table", table.name, sql)


def _diff_table(schema: str, src: Table, dst: Table) -> list[Operation]:
    ops: list[Operation] = []
    qt = _qname(schema, src.name)

    for name, col in dst.columns.items():
        if name not in src.columns:
            ops.append(
                Operation(
                    "add_column",
                    src.name,
                    f"ALTER TABLE {qt} ADD COLUMN {_column_clause(col)};",
                    {"nullable": col.nullable, "has_default": col.default is not None},
                )
            )

    for name, col in dst.columns.items():
        old = src.columns.get(name)
        if old is None:
            continue
        if old.type != col.type:
            ops.append(
                Operation(
                    "alter_type",
                    src.name,
                    f"ALTER TABLE {qt} ALTER COLUMN {_qi(name)} TYPE {col.type};",
                    {"column": name, "from_type": old.type, "to_type": col.type},
                )
            )
        if old.nullable and not col.nullable:
            ops.append(
                Operation(
                    "set_not_null",
                    src.name,
                    f"ALTER TABLE {qt} ALTER COLUMN {_qi(name)} SET NOT NULL;",
                    {"column": name},
                )
            )
        elif not old.nullable and col.nullable:
            ops.append(
                Operation(
                    "drop_not_null",
                    src.name,
                    f"ALTER TABLE {qt} ALTER COLUMN {_qi(name)} DROP NOT NULL;",
                    {"column": name},
                )
            )
        if (old.default or None) != (col.default or None):
            if col.default is None:
                ops.append(
                    Operation(
                        "drop_default",
                        src.name,
                        f"ALTER TABLE {qt} ALTER COLUMN {_qi(name)} DROP DEFAULT;",
                        {"column": name},
                    )
                )
            else:
                ops.append(
                    Operation(
                        "set_default",
                        src.name,
                        f"ALTER TABLE {qt} ALTER COLUMN {_qi(name)} SET DEFAULT {col.default};",
                        {"column": name},
                    )
                )

    for name in src.columns:
        if name not in dst.columns:
            ops.append(
                Operation(
                    "drop_column",
                    src.name,
                    f"ALTER TABLE {qt} DROP COLUMN {_qi(name)};",
                    {"column": name},
                )
            )

    ops += _diff_indexes(schema, src, dst)
    ops += _diff_named(schema, src, dst, "foreign_keys", "fk")
    ops += _diff_named(schema, src, dst, "checks", "check")
    ops += _diff_primary_key(schema, src, dst)
    return ops


def _diff_indexes(schema: str, src: Table, dst: Table) -> list[Operation]:
    ops: list[Operation] = []
    for name in src.indexes:
        if name not in dst.indexes:
            ops.append(
                Operation(
                    "drop_index",
                    src.name,
                    f"DROP INDEX {_qname(schema, name)};",
                    {"index": name},
                )
            )
    for name, idx in dst.indexes.items():
        old = src.indexes.get(name)
        if old is None:
            ops.append(Operation("create_index", src.name, idx.definition + ";", {"index": name}))
        elif old.definition != idx.definition:
            ops.append(
                Operation(
                    "replace_index",
                    src.name,
                    f"DROP INDEX {_qname(schema, name)};\n{idx.definition};",
                    {"index": name},
                )
            )
    return ops


def _diff_named(schema: str, src: Table, dst: Table, attr: str, kind: str) -> list[Operation]:
    ops: list[Operation] = []
    qt = _qname(schema, src.name)
    src_items = getattr(src, attr)
    dst_items = getattr(dst, attr)
    for name in src_items:
        if name not in dst_items:
            ops.append(
                Operation(
                    f"drop_{kind}",
                    src.name,
                    f"ALTER TABLE {qt} DROP CONSTRAINT {_qi(name)};",
                    {"name": name},
                )
            )
    for name, item in dst_items.items():
        old = src_items.get(name)
        if old is None:
            ops.append(
                Operation(
                    f"add_{kind}",
                    src.name,
                    f"ALTER TABLE {qt} ADD CONSTRAINT {_qi(name)} {item.definition};",
                    {"name": name},
                )
            )
        elif old.definition != item.definition:
            ops.append(
                Operation(
                    f"replace_{kind}",
                    src.name,
                    f"ALTER TABLE {qt} DROP CONSTRAINT {_qi(name)};\n"
                    f"ALTER TABLE {qt} ADD CONSTRAINT {_qi(name)} {item.definition};",
                    {"name": name},
                )
            )
    return ops


def _diff_primary_key(schema: str, src: Table, dst: Table) -> list[Operation]:
    if src.primary_key == dst.primary_key:
        return []
    qt = _qname(schema, src.name)
    ops: list[Operation] = []
    if src.primary_key and src.primary_key_name:
        ops.append(
            Operation(
                "drop_primary_key",
                src.name,
                f"ALTER TABLE {qt} DROP CONSTRAINT {_qi(src.primary_key_name)};",
                {},
            )
        )
    if dst.primary_key:
        cols = ", ".join(_qi(c) for c in dst.primary_key)
        ops.append(
            Operation(
                "add_primary_key",
                src.name,
                f"ALTER TABLE {qt} ADD PRIMARY KEY ({cols});",
                {},
            )
        )
    return ops


def diff(src: Schema, dst: Schema) -> list[Operation]:
    schema = src.name
    ops: list[Operation] = []

    new_tables = [t for name, t in dst.tables.items() if name not in src.tables]
    for table in new_tables:
        ops.append(_create_table(schema, table))
    for table in new_tables:
        empty = Table(name=table.name)
        ops += _diff_indexes(schema, empty, table)
        ops += _diff_named(schema, empty, table, "foreign_keys", "fk")
        ops += _diff_named(schema, empty, table, "checks", "check")

    for name, table in dst.tables.items():
        if name in src.tables:
            ops += _diff_table(schema, src.tables[name], table)

    for name in src.tables:
        if name not in dst.tables:
            ops.append(Operation("drop_table", name, f"DROP TABLE {_qname(schema, name)};", {}))

    return ops
