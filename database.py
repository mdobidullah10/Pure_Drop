import os
import re
import psycopg2
from psycopg2.extras import RealDictCursor
import sqlite3
import config

class DBRow(dict):
    """Allows accessing columns via index (row[0]) or key (row['id']) like sqlite3.Row."""
    def __init__(self, d, keys):
        super().__init__(d)
        self._keys = keys
        self._values = [d[k] for k in keys]

    def __getitem__(self, item):
        if isinstance(item, int):
            return self._values[item]
        return super().__getitem__(item)

    def keys(self):
        return self._keys

class PGConnectionWrapper:
    """Wraps a psycopg2 connection to mimic sqlite3 query style with ? placeholders and row_factory."""
    def __init__(self, pg_conn):
        self.conn = pg_conn
        self.row_factory = None

    def execute(self, sql, params=None):
        cur = self.cursor()
        cur.execute(sql, params)
        return cur

    def cursor(self):
        return PGCursorWrapper(self.conn.cursor(), self)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def close(self):
        self.conn.close()

class PGCursorWrapper:
    def __init__(self, pg_cursor, wrapper):
        self.cursor = pg_cursor
        self.wrapper = wrapper
        self.lastrowid = None

    def execute(self, sql, params=None):
        # Convert ? to %s for PostgreSQL
        converted_sql = re.sub(r'\?', '%s', sql)
        
        # Handle SQLite's BEGIN IMMEDIATE
        if converted_sql.strip().upper() == 'BEGIN IMMEDIATE':
            return self

        # Handle SQLite's INSERT OR IGNORE
        if re.search(r'INSERT\s+OR\s+IGNORE\s+INTO', converted_sql, re.IGNORECASE):
            converted_sql = re.sub(r'INSERT\s+OR\s+IGNORE\s+INTO', 'INSERT INTO', converted_sql, flags=re.IGNORECASE)
            converted_sql = converted_sql.rstrip().rstrip(';') + ' ON CONFLICT DO NOTHING'

        # Handle SQLite's INSERT OR REPLACE INTO site_settings
        if re.search(r'INSERT\s+OR\s+REPLACE\s+INTO\s+site_settings', converted_sql, re.IGNORECASE):
            converted_sql = re.sub(r'INSERT\s+OR\s+REPLACE\s+INTO\s+site_settings', 'INSERT INTO site_settings', converted_sql, flags=re.IGNORECASE)
            converted_sql = converted_sql.rstrip().rstrip(';') + ' ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, group_name = EXCLUDED.group_name'

        # Handle INSERT ... to populate lastrowid if not present
        is_insert = converted_sql.strip().upper().startswith('INSERT')
        has_returning = 'RETURNING' in converted_sql.upper()
        
        if is_insert and not has_returning and ('users' in converted_sql.lower() or 'products' in converted_sql.lower() or 'orders' in converted_sql.lower() or 'categories' in converted_sql.lower() or 'reviews' in converted_sql.lower() or 'blog_posts' in converted_sql.lower()):
            converted_sql = converted_sql.rstrip().rstrip(';') + ' RETURNING id'
            if params is not None:
                self.cursor.execute(converted_sql, params)
            else:
                self.cursor.execute(converted_sql)
            try:
                row = self.cursor.fetchone()
                if row:
                    self.lastrowid = row[0]
            except Exception:
                pass
            return self

        if params is not None:
            self.cursor.execute(converted_sql, params)
        else:
            self.cursor.execute(converted_sql)
        return self

    def fetchone(self):
        row = self.cursor.fetchone()
        if not row:
            return None
        col_names = [desc[0] for desc in self.cursor.description]
        d = dict(zip(col_names, row))
        return DBRow(d, col_names)

    def fetchall(self):
        rows = self.cursor.fetchall()
        if not rows:
            return []
        col_names = [desc[0] for desc in self.cursor.description]
        return [DBRow(dict(zip(col_names, r)), col_names) for r in rows]

    @property
    def description(self):
        return self.cursor.description

def get_db():
    if config.USE_SUPABASE:
        pg_conn = psycopg2.connect(config.DATABASE_URL)
        return PGConnectionWrapper(pg_conn)
    else:
        conn = sqlite3.connect(config.SQLITE_PATH)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    # Tables schema in Postgres compatible syntax
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id SERIAL PRIMARY KEY,
        username TEXT UNIQUE NOT NULL,
        name TEXT NOT NULL,
        email TEXT UNIQUE,
        phone TEXT UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'customer',
        permissions TEXT DEFAULT '[]',
        is_active INTEGER NOT NULL DEFAULT 1,
        last_login TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS categories (
        id SERIAL PRIMARY KEY,
        name_bn TEXT NOT NULL,
        name_en TEXT NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        description TEXT DEFAULT '',
        image_url TEXT DEFAULT '',
        sort_order INTEGER DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS products (
        id SERIAL PRIMARY KEY,
        name_bn TEXT NOT NULL,
        name_en TEXT DEFAULT '',
        slug TEXT UNIQUE NOT NULL,
        sku TEXT UNIQUE,
        category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
        category_name TEXT NOT NULL,
        short_desc TEXT DEFAULT '',
        description TEXT DEFAULT '',
        ingredients TEXT DEFAULT '',
        nutrition TEXT DEFAULT '',
        usage_instructions TEXT DEFAULT '',
        regular_price DOUBLE PRECISION NOT NULL CHECK(regular_price >= 0),
        discount_price DOUBLE PRECISION DEFAULT NULL,
        cost_price DOUBLE PRECISION DEFAULT 0,
        stock INTEGER NOT NULL DEFAULT 0 CHECK(stock >= 0),
        low_stock_threshold INTEGER DEFAULT 10,
        unit TEXT DEFAULT 'প্যাকেট',
        main_image TEXT DEFAULT '',
        gallery_images TEXT DEFAULT '[]',
        is_featured INTEGER DEFAULT 0,
        is_bestseller INTEGER DEFAULT 0,
        is_new INTEGER DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,
        rating_avg DOUBLE PRECISION DEFAULT 5.0,
        rating_count INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS product_variants (
        id SERIAL PRIMARY KEY,
        product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        title TEXT NOT NULL,
        sku TEXT,
        price DOUBLE PRECISION NOT NULL,
        discount_price DOUBLE PRECISION DEFAULT NULL,
        stock INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER DEFAULT 1
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS orders (
        id SERIAL PRIMARY KEY,
        order_number TEXT UNIQUE NOT NULL,
        customer_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
        customer_name TEXT NOT NULL,
        phone TEXT NOT NULL,
        email TEXT DEFAULT '',
        division TEXT DEFAULT 'ঢাকা',
        district TEXT NOT NULL,
        thana_area TEXT DEFAULT '',
        full_address TEXT NOT NULL,
        order_notes TEXT DEFAULT '',
        payment_method TEXT NOT NULL DEFAULT 'Cash on Delivery',
        payment_status TEXT NOT NULL DEFAULT 'Unpaid',
        payment_trx_id TEXT DEFAULT '',
        payment_sender_phone TEXT DEFAULT '',
        subtotal DOUBLE PRECISION NOT NULL,
        delivery_fee DOUBLE PRECISION NOT NULL DEFAULT 70,
        discount_amount DOUBLE PRECISION NOT NULL DEFAULT 0,
        coupon_code TEXT DEFAULT '',
        total DOUBLE PRECISION NOT NULL,
        status TEXT NOT NULL DEFAULT 'Pending',
        courier_name TEXT DEFAULT '',
        tracking_code TEXT DEFAULT '',
        admin_notes TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS order_items (
        id SERIAL PRIMARY KEY,
        order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
        product_id INTEGER REFERENCES products(id) ON DELETE SET NULL,
        product_name TEXT NOT NULL,
        variant_title TEXT DEFAULT '',
        quantity INTEGER NOT NULL CHECK(quantity > 0),
        unit_price DOUBLE PRECISION NOT NULL,
        line_total DOUBLE PRECISION NOT NULL,
        image_url TEXT DEFAULT ''
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS coupons (
        id SERIAL PRIMARY KEY,
        code TEXT UNIQUE NOT NULL,
        discount_type TEXT NOT NULL DEFAULT 'fixed',
        discount_value DOUBLE PRECISION NOT NULL,
        min_order_value DOUBLE PRECISION DEFAULT 0,
        max_discount DOUBLE PRECISION DEFAULT NULL,
        usage_limit INTEGER DEFAULT 1000,
        times_used INTEGER DEFAULT 0,
        start_date TEXT DEFAULT '',
        end_date TEXT DEFAULT '',
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS delivery_zones (
        id SERIAL PRIMARY KEY,
        name TEXT NOT NULL,
        delivery_fee DOUBLE PRECISION NOT NULL,
        free_delivery_threshold DOUBLE PRECISION DEFAULT 2000,
        estimated_days TEXT DEFAULT '২-৩ কর্মদিবস',
        is_default INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reviews (
        id SERIAL PRIMARY KEY,
        product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        customer_name TEXT NOT NULL,
        customer_phone TEXT DEFAULT '',
        customer_email TEXT DEFAULT '',
        rating INTEGER NOT NULL CHECK(rating >= 1 AND rating <= 5),
        comment TEXT NOT NULL,
        verified_purchase INTEGER DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'approved',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS blog_posts (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        category TEXT DEFAULT 'স্বাস্থ্য ও পুষ্টি',
        excerpt TEXT DEFAULT '',
        content TEXT NOT NULL,
        cover_image TEXT DEFAULT '',
        author_name TEXT DEFAULT 'Pure Drop Editorial',
        is_published INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS subscribers (
        id SERIAL PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        is_active INTEGER DEFAULT 1,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS site_settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        group_name TEXT DEFAULT 'general'
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audit_logs (
        id SERIAL PRIMARY KEY,
        user_id INTEGER,
        username TEXT NOT NULL,
        action TEXT NOT NULL,
        entity_type TEXT DEFAULT '',
        entity_id TEXT DEFAULT '',
        details TEXT DEFAULT '',
        ip_address TEXT DEFAULT '',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS stock_logs (
        id SERIAL PRIMARY KEY,
        product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
        change_amount INTEGER NOT NULL,
        new_stock INTEGER NOT NULL,
        reason TEXT DEFAULT 'Adjustment',
        created_by TEXT DEFAULT 'System',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    conn.commit()
    conn.close()

def get_settings():
    conn = get_db()
    rows = conn.execute("SELECT key, value FROM site_settings").fetchall()
    conn.close()
    return {row["key"]: row["value"] for row in rows}

def log_audit(user_id, username, action, entity_type='', entity_id='', details='', ip_address=''):
    conn = get_db()
    conn.execute("""
        INSERT INTO audit_logs (user_id, username, action, entity_type, entity_id, details, ip_address)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, username, action, entity_type, str(entity_id), details, ip_address))
    conn.commit()
    conn.close()
