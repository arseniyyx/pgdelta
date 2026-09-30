from __future__ import annotations

import psycopg

from pgdelta.model import Check, Column, ForeignKey, Index, Schema, Table

_COLUMNS = """
SELECT c.relname, a.attname,
       pg_catalog.format_type(a.atttypid, a.atttypmod),
       a.attnotnull,
       pg_get_expr(ad.adbin, ad.adrelid)
FROM pg_catalog.pg_class c
JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
LEFT JOIN pg_catalog.pg_attrdef ad ON ad.adrelid = c.oid AND ad.adnum = a.attnum
WHERE n.nspname = %s AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
ORDER BY c.relname, a.attnum
"""

_PRIMARY_KEYS = """
SELECT rel.relname, con.conname, a.attname
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
JOIN pg_namespace n ON n.oid = rel.relnamespace
CROSS JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
JOIN pg_attribute a ON a.attrelid = rel.oid AND a.attnum = k.attnum
WHERE con.contype = 'p' AND n.nspname = %s
ORDER BY rel.relname, k.ord
"""

_INDEXES = """
SELECT c.relname, i.relname, idx.indisunique, idx.indisprimary,
       pg_get_indexdef(idx.indexrelid)
FROM pg_index idx
JOIN pg_class i ON i.oid = idx.indexrelid
JOIN pg_class c ON c.oid = idx.indrelid
JOIN pg_namespace n ON n.oid = c.relnamespace
WHERE n.nspname = %s AND c.relkind = 'r'
ORDER BY c.relname, i.relname
"""

_CONSTRAINTS = """
SELECT rel.relname, con.conname, con.contype, pg_get_constraintdef(con.oid)
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
JOIN pg_namespace n ON n.oid = rel.relnamespace
WHERE con.contype IN ('f', 'c') AND n.nspname = %s
ORDER BY rel.relname, con.conname
"""


def introspect(dsn: str, schema: str = "public") -> Schema:
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        result = Schema(name=schema)

        cur.execute(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = %s AND c.relkind = 'r' ORDER BY c.relname",
            (schema,),
        )
        for (name,) in cur.fetchall():
            result.tables[name] = Table(name=name)

        cur.execute(_COLUMNS, (schema,))
        for table, name, type_, notnull, default in cur.fetchall():
            if table in result.tables:
                result.tables[table].columns[name] = Column(
                    name=name, type=type_, nullable=not notnull, default=default
                )

        cur.execute(_PRIMARY_KEYS, (schema,))
        for table, conname, column in cur.fetchall():
            if table in result.tables:
                result.tables[table].primary_key.append(column)
                result.tables[table].primary_key_name = conname

        cur.execute(_INDEXES, (schema,))
        for table, name, unique, is_primary, definition in cur.fetchall():
            if is_primary or table not in result.tables:
                continue
            result.tables[table].indexes[name] = Index(
                name=name, unique=unique, definition=definition
            )

        cur.execute(_CONSTRAINTS, (schema,))
        for table, name, contype, definition in cur.fetchall():
            if table not in result.tables:
                continue
            if contype == "f":
                result.tables[table].foreign_keys[name] = ForeignKey(name, definition)
            else:
                result.tables[table].checks[name] = Check(name, definition)

        return result
