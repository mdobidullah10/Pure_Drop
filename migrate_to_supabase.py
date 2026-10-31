import sqlite3
import psycopg2
import config

def migrate():
    sq_conn = sqlite3.connect("pure_drop.db")
    sq_conn.row_factory = sqlite3.Row
    pg_conn = psycopg2.connect(config.DATABASE_URL)
    pg_cur = pg_conn.cursor()

    tables = [
        "categories", "products", "product_variants", "users", "orders", "order_items",
        "coupons", "delivery_zones", "reviews", "blog_posts", "subscribers", "site_settings",
        "audit_logs", "stock_logs"
    ]

    for table in tables:
        rows = sq_conn.execute(f"SELECT * FROM {table}").fetchall()
        if not rows:
            print(f"Skipping {table} (empty)")
            continue
        cols = [d[0] for d in sq_conn.execute(f"SELECT * FROM {table} LIMIT 1").description]
        cols_str = ", ".join(cols)
        placeholders = ", ".join(["%s"] * len(cols))

        try:
            pg_cur.execute(f"TRUNCATE TABLE {table} RESTART IDENTITY CASCADE;")
        except Exception as e:
            pg_conn.rollback()

        insert_sql = f"INSERT INTO {table} ({cols_str}) VALUES ({placeholders})"
        for r in rows:
            vals = [r[c] for c in cols]
            pg_cur.execute(insert_sql, vals)

        if table != "site_settings":
            try:
                pg_cur.execute(f"SELECT setval(pg_get_serial_sequence('{table}', 'id'), coalesce(max(id), 1)) FROM {table};")
            except Exception as e:
                pass

        print(f"Migrated {len(rows)} records into '{table}'")

    pg_conn.commit()
    sq_conn.close()
    pg_conn.close()
    print("ALL DATA SUCCESSFULLY TRANSFERRED TO SUPABASE!")

if __name__ == "__main__":
    migrate()
