from pgdelta.cli import _exit_code
from pgdelta.safety import CAUTION, DANGER, SAFE, classify_operation, lint_sql


def test_classify_add_column_variants():
    assert classify_operation("add_column", {"nullable": True}).level == SAFE
    assert (
        classify_operation("add_column", {"nullable": False, "has_default": False}).level == DANGER
    )
    assert (
        classify_operation("add_column", {"nullable": False, "has_default": True}).level == CAUTION
    )


def test_classify_known_operations():
    assert classify_operation("set_not_null").level == DANGER
    assert classify_operation("alter_type").level == DANGER
    assert classify_operation("drop_table").level == DANGER
    assert classify_operation("add_fk").level == DANGER
    assert classify_operation("create_index").level == CAUTION
    assert classify_operation("drop_default").level == SAFE
    assert classify_operation("drop_not_null").level == SAFE


def test_lint_classifies_statements():
    findings = lint_sql(
        "ALTER TABLE t ALTER COLUMN x SET NOT NULL;"
        "CREATE INDEX i ON t (x);"
        "CREATE INDEX CONCURRENTLY j ON t (y);"
        "ALTER TABLE t ADD COLUMN z int NOT NULL DEFAULT 0;"
        "SELECT 1"
    )
    levels = [f.risk.level for f in findings]
    assert levels == [DANGER, CAUTION, SAFE, CAUTION, SAFE]

    concurrently = next(f for f in findings if "CONCURRENTLY" in f.statement)
    assert concurrently.risk.level == SAFE


def test_lint_flags_foreign_key_and_drop():
    findings = lint_sql(
        "ALTER TABLE a ADD CONSTRAINT fk FOREIGN KEY (b) REFERENCES c (id);DROP TABLE old"
    )
    assert all(f.risk.level == DANGER for f in findings)
    assert findings[0].risk.safe_alternative is not None


def test_exit_code_thresholds():
    assert _exit_code([SAFE, DANGER], "danger") == 1
    assert _exit_code([SAFE, CAUTION], "danger") == 0
    assert _exit_code([DANGER], "never") == 0
    assert _exit_code([CAUTION], "caution") == 1
    assert _exit_code([], "danger") == 0
