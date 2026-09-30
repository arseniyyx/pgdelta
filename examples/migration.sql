-- A sample migration to try the linter:  pgdelta lint examples/migration.sql

-- safe: a nullable column is metadata-only
ALTER TABLE orders ADD COLUMN note text;

-- danger: rewrites/locks the table to validate every existing row
ALTER TABLE orders ALTER COLUMN status SET NOT NULL;

-- caution: building the index blocks writes until it finishes
CREATE INDEX idx_orders_customer ON orders (customer_id);

-- safe: the concurrent build does not block writes
CREATE INDEX CONCURRENTLY idx_orders_created ON orders (created_at);

-- danger: locks both tables and scans orders to validate the key
ALTER TABLE orders ADD CONSTRAINT fk_customer
    FOREIGN KEY (customer_id) REFERENCES customers (id);

-- danger: dropping a column throws the data away
ALTER TABLE orders DROP COLUMN legacy_ref;
