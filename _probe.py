import sqlglot
from sqlglot import exp

samples = {
    "insert": "INSERT INTO customers (name) VALUES ('x')",
    "update": "UPDATE customers SET name='y'",
    "delete": "DELETE FROM customers",
    "drop": "DROP TABLE customers",
    "create": "CREATE TABLE t (id int)",
    "alter": "ALTER TABLE customers ADD COLUMN c int",
    "truncate": "TRUNCATE TABLE customers",
    "merge": "MERGE INTO customers USING x ON a=b WHEN MATCHED THEN DELETE",
    "grant": "GRANT SELECT ON customers TO bob",
    "vacuum": "VACUUM customers",
    "select_into": "SELECT * INTO newt FROM customers",
    "cte_insert": "WITH x AS (SELECT 1) INSERT INTO customers SELECT * FROM x",
    "for_update": "SELECT * FROM customers FOR UPDATE",
    "func": "SELECT COUNT(*) AS total FROM customers",
    "subq": "SELECT name FROM customers WHERE id IN (SELECT owner_id FROM pets)",
}
for k, s in samples.items():
    try:
        parsed = sqlglot.parse(s, read="postgres")
        types = [type(p).__name__ for p in parsed]
        into = None
        if parsed and isinstance(parsed[0], exp.Select):
            into = parsed[0].args.get("into")
        print(k, "->", types, "into=", type(into).__name__ if into else None)
    except Exception as e:
        print(k, "ERR", type(e).__name__)

for name in ["Insert", "Update", "Delete", "Merge", "Create", "Drop", "Alter",
             "TruncateTable", "Command", "Into", "Select", "Lock"]:
    print(name, hasattr(exp, name))
