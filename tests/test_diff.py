from pgdelta.diff import diff
from pgdelta.introspect import introspect


def _run(from_dsn, to_dsn):
    return diff(introspect(from_dsn), introspect(to_dsn))


def test_identical_schemas_produce_no_diff(setup_schemas, from_dsn, to_dsn):
    ddl = "CREATE TABLE t (id int primary key, x text)"
    setup_schemas(ddl, ddl)
    assert _run(from_dsn, to_dsn) == []


def test_new_table_and_nullable_column(setup_schemas, from_dsn, to_dsn):
    setup_schemas(
        "CREATE TABLE users (id serial primary key, email text)",
        "CREATE TABLE users (id serial primary key, email text, created_at timestamptz);"
        "CREATE TABLE audit (id bigserial primary key, msg text)",
    )
    ops = _run(from_dsn, to_dsn)
    kinds = {o.kind for o in ops}
    assert "create_table" in kinds
    add = next(o for o in ops if o.kind == "add_column")
    assert add.detail["nullable"] is True


def test_column_type_nullability_and_drop(setup_schemas, from_dsn, to_dsn):
    setup_schemas(
        "CREATE TABLE t (id int primary key, a text, b int, c text)",
        "CREATE TABLE t (id int primary key, a text NOT NULL, b bigint)",
    )
    kinds = {o.kind for o in _run(from_dsn, to_dsn)}
    assert "set_not_null" in kinds
    assert "alter_type" in kinds
    assert "drop_column" in kinds


def test_index_and_foreign_key(setup_schemas, from_dsn, to_dsn):
    setup_schemas(
        "CREATE TABLE customers (id int primary key);"
        "CREATE TABLE orders (id int primary key, customer_id int)",
        "CREATE TABLE customers (id int primary key);"
        "CREATE TABLE orders (id int primary key, customer_id int);"
        "CREATE INDEX orders_cust_idx ON orders (customer_id);"
        "ALTER TABLE orders ADD CONSTRAINT fk_c "
        "FOREIGN KEY (customer_id) REFERENCES customers (id)",
    )
    kinds = {o.kind for o in _run(from_dsn, to_dsn)}
    assert "create_index" in kinds
    assert "add_fk" in kinds


def test_drop_table(setup_schemas, from_dsn, to_dsn):
    setup_schemas("CREATE TABLE gone (id int)", "")
    assert any(o.kind == "drop_table" for o in _run(from_dsn, to_dsn))
