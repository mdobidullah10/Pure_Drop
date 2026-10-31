import database

conn = database.get_db()

# Categories
conn.execute("UPDATE categories SET image_url='/static/images/poster_goodness.png' WHERE slug='honey' OR name_bn LIKE '%মধু%'")
conn.execute("UPDATE categories SET image_url='/static/images/poster_purity.png' WHERE slug='mustard-oil' OR name_bn LIKE '%সরিষা%'")
conn.execute("UPDATE categories SET image_url='/static/images/poster_natural.png' WHERE slug='ghee' OR name_bn LIKE '%ঘি%'")
conn.execute("UPDATE categories SET image_url='/static/images/homepage_reference.png' WHERE slug='natural-foods' OR name_bn LIKE '%প্রাকৃতিক%'")

# Products images
# Sundarbans Honey
conn.execute("UPDATE products SET main_image='https://images.unsplash.com/photo-1587049352851-8d4e89133924?auto=format&fit=crop&w=900&q=80' WHERE category_name LIKE '%মধু%' AND main_image=''")
# Mustard Oil
conn.execute("UPDATE products SET main_image='https://images.unsplash.com/photo-1474979266404-7eaacbcd87c5?auto=format&fit=crop&w=900&q=80' WHERE category_name LIKE '%সরিষা%' AND main_image=''")

conn.commit()

rows = conn.execute("SELECT id, slug, image_url FROM categories").fetchall()
for r in rows:
    print(r["id"], r["slug"], "->", r["image_url"])

conn.close()
print("UPDATED_SUCCESSFULLY")
