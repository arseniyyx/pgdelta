# pgdelta

A schema diff for PostgreSQL that cares about *how* the migration runs, not just what it
changes. Point it at two databases and it prints the DDL to bring the first in line with the
second — and flags the statements that would take a heavy lock or rewrite a table under load,
with the safer way to do each one.

It has a second mode that skips the diff entirely: hand it a migration `.sql` file and it lints
the statements the same way. Good as a pre-merge check on a migration someone wrote by hand.

Every query it runs is a read against the system catalogs. It changes nothing in either
database.

## Why

Most schema-diff tools stop at "here's the SQL." But in production the SQL is the easy part —
the trap is that `ALTER TABLE ... SET NOT NULL` or `ADD CONSTRAINT ... FOREIGN KEY` takes an
`ACCESS EXCLUSIVE` lock and scans the whole table while every other query waits. pgdelta calls
those out and tells you the online-safe rewrite.

## What it flags

| level | examples |
|---|---|
| danger | drop table/column, change column type, `SET NOT NULL`, add FK/CHECK, add primary key, add `NOT NULL` column with no default |
| caution | `CREATE INDEX` without `CONCURRENTLY`, drop index, add `NOT NULL` column with a default |
| safe | create table, add a nullable column, drop `NOT NULL`, set/drop default, drop a constraint |

Each danger and caution finding comes with the safer rewrite (add the constraint `NOT VALID`
then `VALIDATE`, build the index `CONCURRENTLY`, backfill before enforcing `NOT NULL`, and so
on).

## Install and run

```bash
uv sync

# diff two databases: what would I run to make "from" match "to"?
uv run pgdelta diff \
  --from postgresql://user:pass@localhost/app_prod \
  --to   postgresql://user:pass@localhost/app_staging

# print it as runnable SQL with the risks as comments
uv run pgdelta diff --from "$FROM" --to "$TO" --sql > migration.sql

# lint a migration file you already have
uv run pgdelta lint examples/migration.sql
```

Add `--schema <name>` to compare something other than `public`, and `--fail-on danger`
(or `caution`) to make it exit non-zero for CI.

## Example

```
$ pgdelta lint examples/migration.sql
[SAFE] ALTER TABLE orders ADD COLUMN note text;
    No blocking operation detected.
[DANGER] ALTER TABLE orders ALTER COLUMN status SET NOT NULL;
    SET NOT NULL scans the whole table under an exclusive lock.
    safer: Add a CHECK (col IS NOT NULL) NOT VALID, VALIDATE CONSTRAINT, then SET NOT NULL.
[CAUTION] CREATE INDEX idx_orders_customer ON orders (customer_id);
    Building an index blocks writes on the table until it finishes.
    safer: Build it with CREATE INDEX CONCURRENTLY so writes are not blocked.
...
Summary: 7 statement(s) — 4 danger, 1 caution, 2 safe
```

## How it works

Introspection reads `pg_class`, `pg_attribute`, `pg_index`, and `pg_constraint` into a plain
model of each schema: tables, columns (type, nullability, default), primary keys, indexes, and
foreign-key / check constraints. The diff walks the two models and emits one operation per
change, each carrying enough context for the safety layer to judge it. Index and constraint
DDL comes straight from `pg_get_indexdef` / `pg_get_constraintdef`, so it round-trips exactly.

The safety layer is a lookup from operation kind to a risk level plus a rewrite hint. The lint
mode reuses the same rules over statements split out of a `.sql` file with `sqlparse`, matching
the dangerous shapes textually.

## Tests

```bash
docker run -d -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:16
psql postgresql://postgres:postgres@localhost/postgres -c 'CREATE DATABASE pgdelta_src' -c 'CREATE DATABASE pgdelta_dst'
PGDELTA_FROM_DSN=postgresql://postgres:postgres@localhost/pgdelta_src \
PGDELTA_TO_DSN=postgresql://postgres:postgres@localhost/pgdelta_dst \
  uv run pytest
```

The diff tests build real schemas in two databases and assert the operations that come back;
the safety and lint tests need no database.

## What I'd add next

- Sequences and identity columns, so a generated `CREATE TABLE` is runnable as-is.
- A desired-state mode: diff a live database against a `.sql` schema file, not just another DB.
- Views, materialized views, partitioned tables, and enum types.
- Column and table renames inferred from position, instead of drop + add.
- An allow/deny config so a team can decide which "caution" rules block a merge.
