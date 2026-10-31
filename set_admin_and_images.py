import database
from werkzeug.security import generate_password_hash

conn = database.get_db()

# 1. Update Super Admin Credentials
pwd_hash = generate_password_hash("Obidullah@910")
conn.execute(
    "UPDATE users SET username='admin', password_hash=?, email='admin@puredropbd.com' WHERE role='super_admin' OR id=1",
    (pwd_hash,)
)

# 2. Update Categories with individual, distinct product photos
conn.execute("UPDATE categories SET image_url='/static/images/ghee_jar.png' WHERE slug='ghee' OR name_bn LIKE '%ঘি%'")
conn.execute("UPDATE categories SET image_url='/static/images/honey_jar.jpg' WHERE slug='honey' OR name_bn LIKE '%মধু%'")
conn.execute("UPDATE categories SET image_url='/static/images/mustard_oil.jpg' WHERE slug='mustard-oil' OR name_bn LIKE '%সরিষা%'")
conn.execute("UPDATE categories SET image_url='/static/images/homepage_reference.png' WHERE slug='natural-foods' OR name_bn LIKE '%প্রাকৃতিক%'")

# 3. Update Individual Products
conn.execute("UPDATE products SET main_image='/static/images/ghee_jar.png' WHERE slug='premium-cow-ghee' OR name_bn LIKE '%গাওয়া ঘি%'")
conn.execute("UPDATE products SET main_image='/static/images/honey_jar.jpg' WHERE slug='sundarbans-khalisha-honey' OR name_bn LIKE '%খলিসা%'")
conn.execute("UPDATE products SET main_image='/static/images/mustard_oil.jpg' WHERE slug='cold-pressed-mustard-oil' OR name_bn LIKE '%ঘানি%'")

conn.commit()

print("UPDATES COMPLETED:")
print("Admin updated:")
admin_row = conn.execute("SELECT id, username, email, role FROM users WHERE role='super_admin'").fetchone()
print(admin_row["id"], admin_row["username"], admin_row["email"], admin_row["role"])

print("Categories updated:")
for r in conn.execute("SELECT id, name_bn, image_url FROM categories").fetchall():
    print(r["id"], r["name_bn"], r["image_url"])

conn.close()
