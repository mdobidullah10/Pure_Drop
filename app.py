import os
import json
import secrets
import csv
import io
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    session, flash, abort, jsonify, Response, send_from_directory
)
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

import database
from database import get_db, get_settings, log_audit
from auth_helpers import (
    is_setup_required, get_current_user, user_has_permission,
    login_required, admin_required, super_admin_required, permission_required
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# On Vercel / serverless, filesystem is read-only except /tmp
IS_VERCEL = bool(os.environ.get("VERCEL"))
if IS_VERCEL:
    UPLOAD_FOLDER = "/tmp"
else:
    UPLOAD_FOLDER = os.path.join(BASE_DIR, "static", "uploads")
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}

app = Flask(__name__, static_folder="static")
app.secret_key = os.environ.get("SECRET_KEY", "pure-drop-production-secret-key-bangladesh-2026")
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max

# Explicit route to guarantee static assets (CSS, JS, images) are served on Vercel
@app.route("/static/<path:filename>")
def serve_static(filename):
    static_dir = os.path.join(BASE_DIR, "static")
    return send_from_directory(static_dir, filename)

# Initialize database tables
try:
    database.init_db()
except Exception as e:
    app.logger.warning(f"Database init skipped or already initialized: {e}")

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# ==============================================================================
# CONTEXT PROCESSORS & FILTERS
# ==============================================================================
@app.template_filter("money")
def money_filter(value):
    try:
        return f"৳{float(value):,.0f}"
    except (ValueError, TypeError):
        return f"৳{value}"

@app.context_processor
def inject_global_data():
    conn = get_db()
    # Cart count
    cart = session.get("cart", {})
    cart_count = sum(int(v.get("quantity", 0)) for v in cart.values())

    # Settings
    settings = get_settings()

    # Active categories for nav
    nav_categories = conn.execute(
        "SELECT name_bn, name_en, slug FROM categories WHERE is_active=1 ORDER BY sort_order ASC, id ASC"
    ).fetchall()

    # Admin info if logged in
    current_admin = None
    admin_id = session.get("admin_user_id")
    if admin_id:
        current_admin = conn.execute("SELECT * FROM users WHERE id=?", (admin_id,)).fetchone()

    # Customer user if logged in
    current_user = None
    user_id = session.get("user_id")
    if user_id:
        current_user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()

    conn.close()

    return {
        "cart_count": cart_count,
        "settings": settings,
        "nav_categories": nav_categories,
        "current_admin": current_admin,
        "current_user": current_user,
        "user": current_user
    }

# Helper to calculate cart totals
def calculate_cart_totals(cart, coupon_code=""):
    conn = get_db()
    items = []
    subtotal = 0.0

    for item_key, item_data in cart.items():
        pid = item_data.get("product_id")
        qty = item_data.get("quantity", 1)
        var_id = item_data.get("variant_id")

        p = conn.execute("SELECT * FROM products WHERE id=? AND is_active=1", (pid,)).fetchone()
        if not p:
            continue

        price = p["discount_price"] if p["discount_price"] and p["discount_price"] < p["regular_price"] else p["regular_price"]
        variant_title = ""

        if var_id:
            v = conn.execute("SELECT * FROM product_variants WHERE id=? AND is_active=1", (var_id,)).fetchone()
            if v:
                variant_title = v["title"]
                price = v["discount_price"] if v["discount_price"] and v["discount_price"] < v["price"] else v["price"]

        line_total = price * qty
        subtotal += line_total
        items.append({
            "product": p,
            "product_id": p["id"],
            "name": p["name_bn"],
            "image": p["main_image"],
            "unit_price": price,
            "quantity": qty,
            "variant_id": var_id,
            "variant_title": variant_title,
            "line_total": line_total
        })

    # Coupon calculation
    discount = 0.0
    if coupon_code and subtotal > 0:
        c = conn.execute(
            "SELECT * FROM coupons WHERE code=? AND is_active=1", (coupon_code.upper().strip(),)
        ).fetchone()
        if c and subtotal >= c["min_order_value"]:
            if c["discount_type"] == "percent":
                discount = (subtotal * c["discount_value"]) / 100.0
                if c["max_discount"] and discount > c["max_discount"]:
                    discount = c["max_discount"]
            else:
                discount = min(c["discount_value"], subtotal)

    # Free delivery threshold (e.g. 2000)
    free_thresh = 2000.0
    delivery_fee = 0.0 if subtotal >= free_thresh or subtotal == 0 else 70.0

    total = max(0.0, subtotal - discount + delivery_fee)
    conn.close()

    return items, subtotal, discount, delivery_fee, total

# ==============================================================================
# STOREFRONT ROUTES
# ==============================================================================
@app.route("/")
def home():
    conn = get_db()
    categories = conn.execute("SELECT * FROM categories WHERE is_active=1 ORDER BY sort_order ASC").fetchall()
    featured_products = conn.execute(
        "SELECT * FROM products WHERE is_active=1 AND (is_featured=1 OR is_bestseller=1) ORDER BY id DESC LIMIT 8"
    ).fetchall()
    if not featured_products:
        featured_products = conn.execute("SELECT * FROM products WHERE is_active=1 ORDER BY id DESC LIMIT 8").fetchall()
    blog_posts = conn.execute("SELECT * FROM blog_posts WHERE is_published=1 ORDER BY id DESC LIMIT 3").fetchall()
    conn.close()

    return render_template(
        "home.html",
        categories=categories,
        featured_products=featured_products,
        blog_posts=blog_posts
    )

@app.route("/products")
def products():
    category_slug = request.args.get("category", "").strip()
    search_query = request.args.get("q", "").strip()
    sort = request.args.get("sort", "newest").strip()

    conn = get_db()
    categories = conn.execute("SELECT * FROM categories WHERE is_active=1 ORDER BY sort_order ASC").fetchall()
    selected_category = None
    if category_slug:
        selected_category = conn.execute("SELECT * FROM categories WHERE slug=?", (category_slug,)).fetchone()

    # Query builder
    query = "SELECT * FROM products WHERE is_active=1"
    params = []

    if selected_category:
        query += " AND category_id=?"
        params.append(selected_category["id"])

    if search_query:
        query += " AND (name_bn LIKE ? OR name_en LIKE ? OR description LIKE ? OR sku LIKE ?)"
        term = f"%{search_query}%"
        params.extend([term, term, term, term])

    # Sorting
    if sort == "price_low":
        query += " ORDER BY COALESCE(discount_price, regular_price) ASC"
    elif sort == "price_high":
        query += " ORDER BY COALESCE(discount_price, regular_price) DESC"
    elif sort == "rating":
        query += " ORDER BY rating_avg DESC, id DESC"
    else:
        query += " ORDER BY id DESC"

    products_list = conn.execute(query, params).fetchall()
    conn.close()

    return render_template(
        "products.html",
        products=products_list,
        categories=categories,
        selected_category=selected_category,
        search_query=search_query,
        sort=sort
    )

@app.route("/product/<slug>")
def product_detail(slug):
    conn = get_db()
    # Support lookup by slug or by numeric id
    if slug.isdigit():
        product = conn.execute("SELECT * FROM products WHERE id=? AND is_active=1", (int(slug),)).fetchone()
    else:
        product = conn.execute("SELECT * FROM products WHERE slug=? AND is_active=1", (slug,)).fetchone()

    if not product:
        conn.close()
        abort(404)

    category = conn.execute("SELECT * FROM categories WHERE id=?", (product["category_id"],)).fetchone()
    variants = conn.execute("SELECT * FROM product_variants WHERE product_id=? AND is_active=1", (product["id"],)).fetchall()
    reviews = conn.execute("SELECT * FROM reviews WHERE product_id=? AND status='approved' ORDER BY id DESC", (product["id"],)).fetchall()
    related_products = conn.execute(
        "SELECT * FROM products WHERE category_id=? AND id!=? AND is_active=1 LIMIT 4",
        (product["category_id"], product["id"])
    ).fetchall()

    gallery = []
    try:
        gallery = json.loads(product["gallery_images"] or "[]")
    except Exception:
        pass

    conn.close()

    return render_template(
        "product_detail.html",
        product=product,
        category=category,
        variants=variants,
        reviews=reviews,
        related_products=related_products,
        gallery=gallery
    )

# ==============================================================================
# SHOPPING CART & CHECKOUT
# ==============================================================================
@app.route("/cart")
def cart():
    cart_dict = session.get("cart", {})
    coupon_code = session.get("coupon_code", "")
    items, subtotal, discount, delivery_fee, total = calculate_cart_totals(cart_dict, coupon_code)

    return render_template(
        "cart.html",
        items=items,
        subtotal=subtotal,
        discount=discount,
        coupon_code=coupon_code,
        delivery_fee=delivery_fee,
        total=total
    )

@app.post("/cart/update")
def cart_update():
    cart_dict = session.get("cart", {})
    conn = get_db()
    new_cart = {}

    for key in list(cart_dict.keys()):
        field_name = f"qty_{key.split('_')[0]}"
        qty_str = request.form.get(field_name)
        if qty_str and qty_str.isdigit():
            qty = max(1, min(99, int(qty_str)))
            pid = cart_dict[key].get("product_id")
            p = conn.execute("SELECT stock FROM products WHERE id=?", (pid,)).fetchone()
            if p and p["stock"] >= qty:
                cart_dict[key]["quantity"] = qty
                new_cart[key] = cart_dict[key]
        else:
            new_cart[key] = cart_dict[key]

    conn.close()
    session["cart"] = new_cart
    flash("শপিং কার্ট সফলভাবে আপডেট হয়েছে।", "success")
    return redirect(url_for("cart"))

@app.post("/coupon/apply")
def apply_coupon():
    code = request.form.get("coupon_code", "").strip().upper()
    if not code:
        flash("অনুগ্রহ করে কুপন কোড লিখুন।", "error")
        return redirect(url_for("cart"))

    conn = get_db()
    c = conn.execute("SELECT * FROM coupons WHERE code=? AND is_active=1", (code,)).fetchone()
    conn.close()

    if not c:
        flash("কুপন কোডটি সঠিক নয় অথবা মেয়াদ শেষ হয়ে গেছে।", "error")
    else:
        session["coupon_code"] = code
        flash(f"কুপন '{code}' সফলভাবে সক্রিয় হয়েছে!", "success")

    return redirect(url_for("cart"))

@app.route("/coupon/remove")
def remove_coupon():
    session.pop("coupon_code", None)
    flash("কুপন কোড বাতিল করা হয়েছে।", "info")
    return redirect(url_for("cart"))

@app.route("/checkout")
def checkout():
    # Direct Buy Now check
    direct_pid = request.args.get("direct_product_id")
    if direct_pid and direct_pid.isdigit():
        qty = max(1, int(request.args.get("quantity", 1)))
        var_id = request.args.get("variant_id")
        var_id = int(var_id) if var_id and var_id.isdigit() else None
        item_key = f"{direct_pid}_{var_id or 0}"
        session["cart"] = {item_key: {"product_id": int(direct_pid), "quantity": qty, "variant_id": var_id}}

    cart_dict = session.get("cart", {})
    if not cart_dict:
        flash("চেকআউট করার আগে কার্টে পণ্য যোগ করুন।", "error")
        return redirect(url_for("products"))

    coupon_code = session.get("coupon_code", "")
    items, subtotal, discount, delivery_fee, total = calculate_cart_totals(cart_dict, coupon_code)

    return render_template(
        "checkout.html",
        items=items,
        subtotal=subtotal,
        discount=discount,
        coupon_code=coupon_code,
        delivery_fee=delivery_fee,
        total=total
    )

@app.post("/checkout/submit")
def checkout_submit():
    cart_dict = session.get("cart", {})
    if not cart_dict:
        flash("আপনার কার্ট খালি। নতুন পণ্য যোগ করুন।", "error")
        return redirect(url_for("products"))

    name = request.form.get("customer_name", "").strip()
    phone = request.form.get("phone", "").strip()
    email = request.form.get("email", "").strip()
    district = request.form.get("district", "Dhaka").strip()
    thana_area = request.form.get("thana_area", "").strip()
    full_address = request.form.get("full_address", "").strip()
    order_notes = request.form.get("order_notes", "").strip()
    payment_method = request.form.get("payment_method", "Cash on Delivery").strip()

    payment_trx_id = request.form.get("payment_trx_id") or request.form.get("payment_trx_id_nagad") or ""
    payment_sender = request.form.get("payment_sender_phone") or request.form.get("payment_sender_phone_nagad") or ""

    if not name or not phone or not district or not thana_area or not full_address:
        flash("অনুগ্রহ করে নাম, মোবাইল নম্বর এবং সম্পূর্ণ ডেলিভারি ঠিকানা দিন।", "error")
        return redirect(url_for("checkout"))

    coupon_code = session.get("coupon_code", "")
    items, subtotal, discount, standard_delivery, calculated_total = calculate_cart_totals(cart_dict, coupon_code)

    if not items:
        flash("কার্টে কোনো পণ্য পাওয়া যায়নি।", "error")
        return redirect(url_for("products"))

    # District delivery charge calculation
    is_dhaka = "dhaka" in district.lower() or "ঢাকা" in district
    delivery_fee = 0.0 if subtotal >= 2000 else (70.0 if is_dhaka else 130.0)
    final_total = max(0.0, subtotal - discount + delivery_fee)

    # Initial payment status
    payment_status = "Unpaid"
    if payment_method in ["bKash", "Nagad"] and payment_trx_id:
        payment_status = "Pending Verification"

    order_number = "PD-" + secrets.token_hex(4).upper()

    conn = get_db()
    try:
        conn.execute("BEGIN IMMEDIATE")
        
        # Verify stock and lock rows
        for itm in items:
            p = conn.execute("SELECT stock, name_bn FROM products WHERE id=?", (itm["product_id"],)).fetchone()
            if not p or p["stock"] < itm["quantity"]:
                raise ValueError(f"দুঃখিত, '{itm['name']}' এর পর্যাপ্ত স্টক নেই। অনুগ্রহ করে কার্ট সমন্বয় করুন।")

        # Insert Order
        cur = conn.execute("""
            INSERT INTO orders (
                order_number, customer_id, customer_name, phone, email,
                division, district, thana_area, full_address, order_notes,
                payment_method, payment_status, payment_trx_id, payment_sender_phone,
                subtotal, delivery_fee, discount_amount, coupon_code, total, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            order_number, session.get("user_id"), name, phone, email,
            "ঢাকা" if is_dhaka else district, district, thana_area, full_address, order_notes,
            payment_method, payment_status, payment_trx_id.strip(), payment_sender.strip(),
            subtotal, delivery_fee, discount, coupon_code, final_total, "Pending"
        ))
        order_id = cur.lastrowid

        # Insert Order Items & decrement stock
        for itm in items:
            conn.execute("""
                INSERT INTO order_items (
                    order_id, product_id, product_name, variant_title,
                    quantity, unit_price, line_total, image_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                order_id, itm["product_id"], itm["name"], itm["variant_title"],
                itm["quantity"], itm["unit_price"], itm["line_total"], itm["image"]
            ))
            # Decrement product stock
            conn.execute("UPDATE products SET stock = stock - ? WHERE id=?", (itm["quantity"], itm["product_id"]))

        # Increment coupon times_used if applied
        if coupon_code:
            conn.execute("UPDATE coupons SET times_used = times_used + 1 WHERE code=?", (coupon_code.upper(),))

        conn.commit()

        # Clear cart and coupon
        session["cart"] = {}
        session.pop("coupon_code", None)

        flash("আপনার অর্ডার সফলভাবে গৃহীত হয়েছে!", "success")
        return redirect(url_for("order_success", order_number=order_number))

    except ValueError as val_err:
        conn.rollback()
        flash(str(val_err), "error")
        return redirect(url_for("cart"))
    except Exception as e:
        conn.rollback()
        app.logger.exception("Order placement failed")
        flash("অর্ডার প্রসেস করার সময় সমস্যা হয়েছে। অনুগ্রহ করে আবার চেষ্টা করুন।", "error")
        return redirect(url_for("checkout"))
    finally:
        conn.close()

@app.route("/order-success/<order_number>")
def order_success(order_number):
    conn = get_db()
    order = conn.execute("SELECT * FROM orders WHERE order_number=?", (order_number,)).fetchone()
    if not order:
        conn.close()
        abort(404)
    items = conn.execute("SELECT * FROM order_items WHERE order_id=?", (order["id"],)).fetchall()
    conn.close()

    return render_template("order_success.html", order=order, items=items)

@app.route("/track", methods=["GET", "POST"])
def track():
    order = None
    items = []
    order_number = request.values.get("order_number", "").strip().upper()
    phone = request.values.get("phone", "").strip()

    if order_number and phone:
        conn = get_db()
        order = conn.execute(
            "SELECT * FROM orders WHERE order_number=? AND phone LIKE ?",
            (order_number, f"%{phone[-10:]}%")
        ).fetchone()
        if order:
            items = conn.execute("SELECT * FROM order_items WHERE order_id=?", (order["id"],)).fetchall()
        else:
            flash("অর্ডার নম্বর বা ফোন নম্বরটি সঠিক নয়। দয়া করে মিলিয়ে দেখুন।", "error")
        conn.close()

    return render_template(
        "track.html",
        order=order,
        items=items,
        order_number=order_number,
        phone=phone
    )

@app.route("/wishlist")
def wishlist():
    return render_template("wishlist.html")

# ==============================================================================
# BLOG & STATIC PAGES
# ==============================================================================
@app.route("/blog")
def blog():
    conn = get_db()
    posts = conn.execute("SELECT * FROM blog_posts WHERE is_published=1 ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("blog.html", posts=posts)

@app.route("/blog/<slug>")
def blog_detail(slug):
    conn = get_db()
    post = conn.execute("SELECT * FROM blog_posts WHERE slug=? AND is_published=1", (slug,)).fetchone()
    conn.close()
    if not post:
        abort(404)
    return render_template("blog_detail.html", post=post)

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/contact")
def contact():
    return render_template("contact.html")

@app.post("/contact/submit")
def contact_submit():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    msg = request.form.get("message", "").strip()
    flash("ধন্যবাদ! আপনার বার্তা আমরা পেয়েছি। আমাদের টিম দ্রুত যোগাযোগ করবে।", "success")
    return redirect(url_for("contact"))

@app.route("/policy")
def policy():
    return render_template("policy.html")

@app.post("/newsletter/subscribe")
def newsletter_subscribe():
    email = request.form.get("email", "").strip().lower()
    if email and "@" in email:
        conn = get_db()
        try:
            conn.execute("INSERT OR IGNORE INTO subscribers (email) VALUES (?)", (email,))
            conn.commit()
            flash("ধন্যবাদ! Pure Drop নিউজলেটারে আপনি সফলভাবে যুক্ত হয়েছেন।", "success")
        except Exception:
            pass
        finally:
            conn.close()
    else:
        flash("অনুগ্রহ করে একটি সঠিক ইমেইল অ্যাড্রেস প্রদান করুন।", "error")
    return redirect(request.referrer or url_for("home"))

@app.post("/review/submit/<int:product_id>")
def submit_review(product_id):
    name = request.form.get("customer_name", "").strip()
    phone = request.form.get("customer_phone", "").strip()
    rating = int(request.form.get("rating", 5))
    comment = request.form.get("comment", "").strip()

    if name and comment:
        conn = get_db()
        conn.execute("""
            INSERT INTO reviews (product_id, customer_name, customer_phone, rating, comment, status)
            VALUES (?, ?, ?, ?, ?, 'approved')
        """, (product_id, name, phone, rating, comment))
        conn.commit()
        conn.close()
        flash("আপনার রিভিউ সফলভাবে যুক্ত হয়েছে! মূল্যায়নের জন্য ধন্যবাদ।", "success")
    else:
        flash("রিভিউয়ের নাম ও মন্তব্য আবশ্যক।", "error")

    return redirect(request.referrer or url_for("home"))

# ==============================================================================
# AJAX JSON API ENDPOINTS
# ==============================================================================
@app.route("/api/cart")
def api_cart():
    cart_dict = session.get("cart", {})
    coupon_code = session.get("coupon_code", "")
    items, subtotal, discount, delivery_fee, total = calculate_cart_totals(cart_dict, coupon_code)

    items_data = []
    for itm in items:
        items_data.append({
            "id": itm["product_id"],
            "name": itm["name"],
            "image": itm["image"],
            "price": itm["unit_price"],
            "quantity": itm["quantity"],
            "variant": itm["variant_title"],
            "total": itm["line_total"]
        })

    return jsonify({
        "items": items_data,
        "count": sum(i["quantity"] for i in items),
        "subtotal": subtotal,
        "discount": discount,
        "delivery_fee": delivery_fee,
        "total": total
    })

@app.post("/api/cart/add")
def api_cart_add():
    pid = request.form.get("product_id")
    qty = max(1, min(99, int(request.form.get("quantity", 1) or 1)))
    var_id = request.form.get("variant_id")
    var_id = int(var_id) if var_id and var_id.isdigit() else None

    if not pid or not pid.isdigit():
        return jsonify({"success": False, "message": "ভুল পণ্য আইডি।"}), 400

    conn = get_db()
    product = conn.execute("SELECT id, name_bn, stock, is_active FROM products WHERE id=?", (int(pid),)).fetchone()
    conn.close()

    if not product or not product["is_active"]:
        return jsonify({"success": False, "message": "পণ্যটি পাওয়া যাচ্ছে না।"}), 404

    if product["stock"] < 1:
        return jsonify({"success": False, "message": "দুঃখিত, এই পণ্যটি বর্তমানে স্টকে নেই।"}), 400

    cart = session.get("cart", {})
    item_key = f"{pid}_{var_id or 0}"
    current_qty = cart.get(item_key, {}).get("quantity", 0)
    new_qty = min(product["stock"], current_qty + qty)

    cart[item_key] = {
        "product_id": int(pid),
        "quantity": new_qty,
        "variant_id": var_id
    }
    session["cart"] = cart

    total_count = sum(v.get("quantity", 0) for v in cart.values())
    return jsonify({
        "success": True,
        "message": f"'{product['name_bn']}' কার্টে যোগ হয়েছে!",
        "count": total_count
    })

@app.post("/api/cart/remove")
def api_cart_remove():
    pid = request.form.get("product_id")
    var_id = request.form.get("variant_id") or 0
    if not pid:
        return jsonify({"success": False}), 400

    cart = session.get("cart", {})
    item_key = f"{pid}_{var_id}"
    
    # Try exact key or any key starting with pid
    if item_key in cart:
        del cart[item_key]
    else:
        for k in list(cart.keys()):
            if k.startswith(f"{pid}_"):
                del cart[k]

    session["cart"] = cart
    return jsonify({"success": True, "count": sum(v.get("quantity", 0) for v in cart.values())})

@app.route("/api/search-suggestions")
def api_search_suggestions():
    q = request.args.get("q", "").strip()
    if len(q) < 2:
        return jsonify([])

    conn = get_db()
    results = conn.execute("""
        SELECT id, name_bn, slug, regular_price, discount_price, unit, main_image
        FROM products
        WHERE is_active=1 AND (name_bn LIKE ? OR name_en LIKE ? OR sku LIKE ?)
        LIMIT 5
    """, (f"%{q}%", f"%{q}%", f"%{q}%")).fetchall()
    conn.close()

    return jsonify([dict(r) for r in results])

@app.post("/api/wishlist-products")
def api_wishlist_products():
    data = request.get_json() or {}
    ids = data.get("ids", [])
    if not ids:
        return jsonify([])

    clean_ids = [int(i) for i in ids if str(i).isdigit()]
    if not clean_ids:
        return jsonify([])

    placeholders = ",".join("?" for _ in clean_ids)
    conn = get_db()
    rows = conn.execute(
        f"SELECT * FROM products WHERE id IN ({placeholders}) AND is_active=1", clean_ids
    ).fetchall()
    conn.close()

    return jsonify([dict(r) for r in rows])

# ==============================================================================
# CUSTOMER AUTHENTICATION
# ==============================================================================
@app.route("/customer/login", methods=["GET", "POST"])
def customer_login():
    if request.method == "POST":
        login_id = request.form.get("login_id", "").strip()
        password = request.form.get("password", "")
        next_page = request.form.get("next") or url_for("customer_account")

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE (username=? OR phone=? OR email=?) AND is_active=1",
            (login_id, login_id, login_id)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["user_name"] = user["name"]
            session["user_role"] = user["role"]
            flash(f"স্বাগতম, {user['name']}!", "success")
            return redirect(next_page)
        else:
            flash("মোবাইল নম্বর/ইউজারনেম অথবা পাসওয়ার্ড সঠিক নয়।", "error")

    return render_template("customer/login.html")

@app.route("/customer/register", methods=["GET", "POST"])
def customer_register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        if not name or not phone or not password or len(password) < 6:
            flash("অনুগ্রহ করে নাম, সঠিক ফোন নম্বর ও অন্তত ৬ অক্ষরের পাসওয়ার্ড দিন।", "error")
            return redirect(url_for("customer_register"))

        username = phone  # default username is phone
        pwd_hash = generate_password_hash(password)

        conn = get_db()
        try:
            cur = conn.execute("""
                INSERT INTO users (username, name, email, phone, password_hash, role)
                VALUES (?, ?, ?, ?, ?, 'customer')
            """, (username, name, email or None, phone, pwd_hash))
            conn.commit()
            session["user_id"] = cur.lastrowid
            session["user_name"] = name
            session["user_role"] = "customer"
            flash("অভিনন্দন! আপনার Pure Drop একাউন্ট তৈরি সফল হয়েছে।", "success")
            return redirect(url_for("customer_account"))
        except sqlite3.IntegrityError:
            flash("এই মোবাইল নম্বর বা ইমেইল দিয়ে ইতোমধ্যে একটি একাউন্ট খোলা আছে।", "error")
        finally:
            conn.close()

    return render_template("customer/register.html")

@app.post("/customer/logout")
def customer_logout():
    session.pop("user_id", None)
    session.pop("user_name", None)
    session.pop("user_role", None)
    flash("সফলভাবে লগআউট সম্পন্ন হয়েছে।", "info")
    return redirect(url_for("home"))

@app.route("/customer/account")
@login_required
def customer_account():
    user = get_current_user()
    conn = get_db()
    orders = conn.execute(
        "SELECT * FROM orders WHERE customer_id=? OR phone=? ORDER BY id DESC",
        (user["id"], user["phone"])
    ).fetchall()
    conn.close()

    return render_template("customer/account.html", user=user, orders=orders)

# ==============================================================================
# SUPER ADMIN CONTROL CENTER
# ==============================================================================
@app.route("/admin/setup", methods=["GET", "POST"])
def admin_setup():
    # If a Super Admin already exists, lock this page permanently
    if not is_setup_required():
        flash("সুপার অ্যাডমিন একাউন্ট ইতোমধ্যে বিদ্যমান। দয়া করে লগইন করুন।", "info")
        return redirect(url_for("admin_login"))

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        if not name or not username or not password or len(password) < 8:
            flash("সকল তথ্য দিন এবং কমপক্ষে ৮ অক্ষরের শক্তিশালী পাসওয়ার্ড নির্ধারণ করুন।", "error")
            return redirect(url_for("admin_setup"))

        if password != confirm:
            flash("উভয় পাসওয়ার্ড একই হতে হবে।", "error")
            return redirect(url_for("admin_setup"))

        pwd_hash = generate_password_hash(password)
        conn = get_db()
        try:
            cur = conn.execute("""
                INSERT INTO users (username, name, email, phone, password_hash, role, permissions)
                VALUES (?, ?, ?, ?, ?, 'super_admin', '["all"]')
            """, (username, name, email, phone, pwd_hash))
            conn.commit()
            log_audit(cur.lastrowid, username, "INITIAL_SETUP", "system", "1", "Super Admin established")

            session["admin_user_id"] = cur.lastrowid
            session["admin_user"] = username
            session["admin_role"] = "super_admin"
            flash("সুপার অ্যাডমিন একাউন্ট সফলভাবে স্থাপিত হয়েছে! কন্ট্রোল সেন্টারে স্বাগতম।", "success")
            return redirect(url_for("admin_dashboard"))
        except sqlite3.IntegrityError:
            flash("এই ইউজারনেম বা ইমেইল ইতোমধ্যে ব্যবহৃত হয়েছে।", "error")
        finally:
            conn.close()

    return render_template("admin/setup.html")

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if is_setup_required():
        return redirect(url_for("admin_setup"))

    if session.get("admin_user_id"):
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        next_url = request.form.get("next") or url_for("admin_dashboard")

        conn = get_db()
        user = conn.execute(
            "SELECT * FROM users WHERE (username=? OR email=?) AND is_active=1",
            (username, username)
        ).fetchone()
        conn.close()

        if user and user["role"] != "customer" and check_password_hash(user["password_hash"], password):
            session.clear()
            session["admin_user_id"] = user["id"]
            session["admin_user"] = user["username"]
            session["admin_role"] = user["role"]

            # Update last_login
            conn = get_db()
            conn.execute("UPDATE users SET last_login=CURRENT_TIMESTAMP WHERE id=?", (user["id"],))
            conn.commit()
            conn.close()

            log_audit(user["id"], user["username"], "ADMIN_LOGIN", "users", str(user["id"]), "Admin logged in successfully", request.remote_addr)

            flash(f"স্বাগতম, {user['name']}!", "success")
            return redirect(next_url)
        else:
            flash("অ্যাডমিন ইউজারনেম বা পাসওয়ার্ড সঠিক নয়।", "error")

    return render_template("admin/login.html")

@app.post("/admin/logout")
def admin_logout():
    uid = session.get("admin_user_id")
    uname = session.get("admin_user", "Admin")
    if uid:
        log_audit(uid, uname, "ADMIN_LOGOUT", "users", str(uid), "Admin logged out", request.remote_addr)
    session.pop("admin_user_id", None)
    session.pop("admin_user", None)
    session.pop("admin_role", None)
    flash("প্রশাসনিক প্যানেল থেকে লগআউট সম্পন্ন হয়েছে।", "info")
    return redirect(url_for("admin_login"))

# 1. Admin Dashboard
@app.route("/admin")
@admin_required
def admin_dashboard():
    conn = get_db()
    stats = {
        "total_sales": conn.execute("SELECT COALESCE(SUM(total), 0) FROM orders WHERE status!='Cancelled'").fetchone()[0],
        "total_orders": conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
        "pending_orders": conn.execute("SELECT COUNT(*) FROM orders WHERE status='Pending'").fetchone()[0],
        "low_stock_count": conn.execute("SELECT COUNT(*) FROM products WHERE stock <= low_stock_threshold AND is_active=1").fetchone()[0],
        "active_products": conn.execute("SELECT COUNT(*) FROM products WHERE is_active=1").fetchone()[0],
        "total_customers": conn.execute("SELECT COUNT(*) FROM users WHERE role='customer'").fetchone()[0]
    }
    recent_orders = conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 8").fetchall()
    low_stock_products = conn.execute(
        "SELECT * FROM products WHERE stock <= low_stock_threshold AND is_active=1 ORDER BY stock ASC LIMIT 5"
    ).fetchall()
    conn.close()

    return render_template(
        "admin/dashboard.html",
        stats=stats,
        recent_orders=recent_orders,
        low_stock_products=low_stock_products
    )

# 2. Products Management
@app.route("/admin/products")
@admin_required
@permission_required("products_manage")
def admin_products():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()

    conn = get_db()
    categories = conn.execute("SELECT name_bn FROM categories ORDER BY name_bn").fetchall()

    query = "SELECT * FROM products WHERE 1=1"
    params = []
    if q:
        query += " AND (name_bn LIKE ? OR name_en LIKE ? OR sku LIKE ?)"
        term = f"%{q}%"
        params.extend([term, term, term])
    if category:
        query += " AND category_name=?"
        params.append(category)

    query += " ORDER BY id DESC"
    products_list = conn.execute(query, params).fetchall()
    conn.close()

    return render_template("admin/products.html", products=products_list, categories=categories)

@app.route("/admin/products/new", methods=["GET", "POST"])
@app.route("/admin/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
@permission_required("products_manage")
def admin_product_form_handler(product_id=None):
    conn = get_db()
    product = conn.execute("SELECT * FROM products WHERE id=?", (product_id,)).fetchone() if product_id else None
    if product_id and not product:
        conn.close()
        abort(404)

    categories = conn.execute("SELECT * FROM categories ORDER BY sort_order ASC").fetchall()

    if request.method == "POST":
        name_bn = request.form.get("name_bn", "").strip()
        name_en = request.form.get("name_en", "").strip()
        slug = request.form.get("slug", "").strip()
        sku = request.form.get("sku", "").strip()
        category_id = int(request.form.get("category_id", 1))
        short_desc = request.form.get("short_desc", "").strip()
        description = request.form.get("description", "").strip()
        ingredients = request.form.get("ingredients", "").strip()
        nutrition = request.form.get("nutrition", "").strip()
        usage_instructions = request.form.get("usage_instructions", "").strip()

        try:
            regular_price = float(request.form.get("regular_price", 0))
            disc_raw = request.form.get("discount_price", "").strip()
            discount_price = float(disc_raw) if disc_raw else None
            cost_price = float(request.form.get("cost_price", 0) or 0)
            stock = int(request.form.get("stock", 0))
            low_thresh = int(request.form.get("low_stock_threshold", 10))
            unit = request.form.get("unit", "প্যাকেট").strip()
        except ValueError:
            conn.close()
            flash("দয়া করে সঠিক সংখ্যা ও মূল্য প্রদান করুন।", "error")
            return redirect(request.url)

        # Image handling
        main_image = request.form.get("main_image", "").strip()
        if "image_file" in request.files:
            file = request.files["image_file"]
            if file and file.filename and allowed_file(file.filename):
                fname = secure_filename(file.filename)
                unique_fname = f"{int(datetime.now().timestamp())}_{fname}"
                file.save(os.path.join(app.config["UPLOAD_FOLDER"], unique_fname))
                main_image = f"/static/uploads/{unique_fname}"

        is_active = 1 if request.form.get("is_active") else 0
        is_featured = 1 if request.form.get("is_featured") else 0
        is_bestseller = 1 if request.form.get("is_bestseller") else 0
        is_new = 1 if request.form.get("is_new") else 0

        # Find category name
        cat_row = conn.execute("SELECT name_bn FROM categories WHERE id=?", (category_id,)).fetchone()
        category_name = cat_row["name_bn"] if cat_row else "সাধারণ"

        if product:
            conn.execute("""
                UPDATE products SET
                    name_bn=?, name_en=?, slug=?, sku=?, category_id=?, category_name=?,
                    short_desc=?, description=?, ingredients=?, nutrition=?, usage_instructions=?,
                    regular_price=?, discount_price=?, cost_price=?, stock=?, low_stock_threshold=?,
                    unit=?, main_image=?, is_active=?, is_featured=?, is_bestseller=?, is_new=?,
                    updated_at=CURRENT_TIMESTAMP
                WHERE id=?
            """, (
                name_bn, name_en, slug, sku, category_id, category_name,
                short_desc, description, ingredients, nutrition, usage_instructions,
                regular_price, discount_price, cost_price, stock, low_thresh,
                unit, main_image or product["main_image"], is_active, is_featured, is_bestseller, is_new,
                product_id
            ))
            conn.commit()
            log_audit(session.get("admin_user_id"), session.get("admin_user"), "PRODUCT_UPDATE", "products", str(product_id), f"Updated {name_bn}")
            flash(f"'{name_bn}' সফলভাবে আপডেট হয়েছে।", "success")
        else:
            cur = conn.execute("""
                INSERT INTO products (
                    name_bn, name_en, slug, sku, category_id, category_name,
                    short_desc, description, ingredients, nutrition, usage_instructions,
                    regular_price, discount_price, cost_price, stock, low_stock_threshold,
                    unit, main_image, is_active, is_featured, is_bestseller, is_new
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                name_bn, name_en, slug, sku, category_id, category_name,
                short_desc, description, ingredients, nutrition, usage_instructions,
                regular_price, discount_price, cost_price, stock, low_thresh,
                unit, main_image, is_active, is_featured, is_bestseller, is_new
            ))
            new_id = cur.lastrowid
            conn.commit()
            log_audit(session.get("admin_user_id"), session.get("admin_user"), "PRODUCT_CREATE", "products", str(new_id), f"Created {name_bn}")
            flash(f"নতুন পণ্য '{name_bn}' সফলভাবে যুক্ত হয়েছে।", "success")

        conn.close()
        return redirect(url_for("admin_products"))

    conn.close()
    return render_template("admin/product_form.html", product=product, categories=categories)

# Named route wrappers for form
@app.route("/admin/products/new", endpoint="admin_product_new")
@app.route("/admin/products/<int:product_id>/edit", endpoint="admin_product_edit")
def _product_form_bridge(product_id=None):
    return admin_product_form_handler(product_id)

@app.post("/admin/products/<int:product_id>/toggle")
@admin_required
@permission_required("products_manage")
def admin_product_toggle(product_id):
    conn = get_db()
    conn.execute("UPDATE products SET is_active = CASE is_active WHEN 1 THEN 0 ELSE 1 END WHERE id=?", (product_id,))
    conn.commit()
    conn.close()
    flash("পণ্যের স্ট্যাটাস সফলভাবে পরিবর্তন হয়েছে।", "success")
    return redirect(url_for("admin_products"))

@app.post("/admin/products/<int:product_id>/delete")
@admin_required
@permission_required("products_manage")
def admin_product_delete(product_id):
    conn = get_db()
    conn.execute("DELETE FROM products WHERE id=?", (product_id,))
    conn.commit()
    conn.close()
    log_audit(session.get("admin_user_id"), session.get("admin_user"), "PRODUCT_DELETE", "products", str(product_id), "Deleted product")
    flash("পণ্যটি সফলভাবে মুছে ফেলা হয়েছে।", "success")
    return redirect(url_for("admin_products"))

# 3. Categories Management
@app.route("/admin/categories")
@admin_required
def admin_categories():
    conn = get_db()
    categories = conn.execute("""
        SELECT c.*, COUNT(p.id) AS product_count
        FROM categories c
        LEFT JOIN products p ON c.id = p.category_id
        GROUP BY c.id
        ORDER BY c.sort_order ASC, c.id ASC
    """).fetchall()
    conn.close()
    return render_template("admin/categories.html", categories=categories)

@app.post("/admin/categories/add")
@admin_required
def admin_category_add():
    name_bn = request.form.get("name_bn", "").strip()
    name_en = request.form.get("name_en", "").strip()
    slug = request.form.get("slug", "").strip()
    image_url = request.form.get("image_url", "").strip()
    description = request.form.get("description", "").strip()
    sort_order = int(request.form.get("sort_order", 0))

    if name_bn and slug:
        conn = get_db()
        try:
            conn.execute("""
                INSERT INTO categories (name_bn, name_en, slug, description, image_url, sort_order)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (name_bn, name_en, slug, description, image_url, sort_order))
            conn.commit()
            log_audit(session.get("admin_user_id"), session.get("admin_user"), "CATEGORY_CREATE", "categories", slug, f"Created {name_bn}")
            flash(f"ক্যাটাগরি '{name_bn}' সফলভাবে যুক্ত হয়েছে।", "success")
        except sqlite3.IntegrityError:
            flash("এই স্লাগ দিয়ে ইতোমধ্যে ক্যাটাগরি আছে।", "error")
        finally:
            conn.close()
    return redirect(url_for("admin_categories"))

@app.post("/admin/categories/<int:category_id>/delete")
@admin_required
def admin_category_delete(category_id):
    conn = get_db()
    conn.execute("DELETE FROM categories WHERE id=?", (category_id,))
    conn.commit()
    conn.close()
    flash("ক্যাটাগরি মুছে ফেলা হয়েছে।", "success")
    return redirect(url_for("admin_categories"))

# 4. Inventory & Stock Adjustments
@app.route("/admin/inventory")
@admin_required
@permission_required("inventory_manage")
def admin_inventory():
    filter_type = request.args.get("filter", "")
    conn = get_db()
    total_products = conn.execute("SELECT COUNT(*) FROM products WHERE is_active=1").fetchone()[0]
    low_stock_count = conn.execute("SELECT COUNT(*) FROM products WHERE stock <= low_stock_threshold AND is_active=1").fetchone()[0]

    if filter_type == "low":
        products = conn.execute("SELECT * FROM products WHERE stock <= low_stock_threshold AND is_active=1 ORDER BY stock ASC").fetchall()
    else:
        products = conn.execute("SELECT * FROM products WHERE is_active=1 ORDER BY id DESC").fetchall()
    conn.close()

    return render_template(
        "admin/inventory.html",
        products=products,
        total_products=total_products,
        low_stock_count=low_stock_count
    )

@app.post("/admin/api/stock-adjust")
@admin_required
@permission_required("inventory_manage")
def admin_api_stock_adjust():
    data = request.get_json() or {}
    pid = data.get("product_id")
    delta = int(data.get("delta", 0))

    if not pid:
        return jsonify({"success": False, "message": "Missing product ID"}), 400

    conn = get_db()
    p = conn.execute("SELECT id, name_bn, stock FROM products WHERE id=?", (pid,)).fetchone()
    if not p:
        conn.close()
        return jsonify({"success": False, "message": "Product not found"}), 404

    new_stock = max(0, p["stock"] + delta)
    conn.execute("UPDATE products SET stock=? WHERE id=?", (new_stock, pid))
    conn.execute("""
        INSERT INTO stock_logs (product_id, change_amount, new_stock, reason, created_by)
        VALUES (?, ?, ?, 'Manual Stock Adjustment', ?)
    """, (pid, delta, new_stock, session.get("admin_user", "Admin")))
    conn.commit()
    conn.close()

    log_audit(session.get("admin_user_id"), session.get("admin_user"), "STOCK_ADJUST", "products", str(pid), f"Adjusted stock by {delta} (New: {new_stock})")

    return jsonify({"success": True, "new_stock": new_stock})

# 5. Orders Management
@app.route("/admin/orders")
@admin_required
@permission_required("orders_manage")
def admin_orders():
    status = request.args.get("status", "").strip()
    q = request.args.get("q", "").strip()

    conn = get_db()
    counts = {
        "all": conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0],
        "pending": conn.execute("SELECT COUNT(*) FROM orders WHERE status='Pending'").fetchone()[0],
        "confirmed": conn.execute("SELECT COUNT(*) FROM orders WHERE status='Confirmed'").fetchone()[0],
        "processing": conn.execute("SELECT COUNT(*) FROM orders WHERE status='Processing'").fetchone()[0],
        "shipped": conn.execute("SELECT COUNT(*) FROM orders WHERE status='Shipped'").fetchone()[0],
        "delivered": conn.execute("SELECT COUNT(*) FROM orders WHERE status='Delivered'").fetchone()[0],
        "cancelled": conn.execute("SELECT COUNT(*) FROM orders WHERE status='Cancelled'").fetchone()[0]
    }

    query = "SELECT * FROM orders WHERE 1=1"
    params = []
    if status:
        query += " AND status=?"
        params.append(status)
    if q:
        query += " AND (order_number LIKE ? OR phone LIKE ? OR customer_name LIKE ?)"
        term = f"%{q}%"
        params.extend([term, term, term])

    query += " ORDER BY id DESC"
    orders_list = conn.execute(query, params).fetchall()
    conn.close()

    return render_template(
        "admin/orders.html",
        orders=orders_list,
        counts=counts,
        status_filter=status,
        search_query=q
    )

@app.route("/admin/orders/<int:order_id>", methods=["GET", "POST"])
@admin_required
@permission_required("orders_manage")
def admin_order_detail(order_id):
    conn = get_db()
    order = conn.execute("SELECT * FROM orders WHERE id=?", (order_id,)).fetchone()
    if not order:
        conn.close()
        abort(404)

    if request.method == "POST":
        new_status = request.form.get("status", order["status"])
        payment_status = request.form.get("payment_status", order["payment_status"])
        payment_trx_id = request.form.get("payment_trx_id", "").strip()
        courier_name = request.form.get("courier_name", "").strip()
        tracking_code = request.form.get("tracking_code", "").strip()
        admin_notes = request.form.get("admin_notes", "").strip()

        conn.execute("""
            UPDATE orders SET
                status=?, payment_status=?, payment_trx_id=?,
                courier_name=?, tracking_code=?, admin_notes=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
        """, (new_status, payment_status, payment_trx_id, courier_name, tracking_code, admin_notes, order_id))
        conn.commit()

        log_audit(session.get("admin_user_id"), session.get("admin_user"), "ORDER_UPDATE", "orders", str(order_id), f"Status: {new_status}, Payment: {payment_status}")
        flash(f"অর্ডার {order['order_number']} এর তথ্য সফলভাবে আপডেট হয়েছে।", "success")
        conn.close()
        return redirect(url_for("admin_order_detail", order_id=order_id))

    items = conn.execute("SELECT * FROM order_items WHERE order_id=?", (order_id,)).fetchall()
    conn.close()

    return render_template("admin/order_detail.html", order=order, items=items)

# 6. Customers Directory
@app.route("/admin/customers")
@admin_required
@permission_required("customers_manage")
def admin_customers():
    q = request.args.get("q", "").strip()
    conn = get_db()
    query = """
        SELECT u.*, COUNT(o.id) AS order_count, COALESCE(SUM(o.total), 0) AS total_spent
        FROM users u
        LEFT JOIN orders o ON u.id = o.customer_id OR u.phone = o.phone
        WHERE u.role='customer'
    """
    params = []
    if q:
        query += " AND (u.name LIKE ? OR u.phone LIKE ? OR u.email LIKE ?)"
        term = f"%{q}%"
        params.extend([term, term, term])

    query += " GROUP BY u.id ORDER BY total_spent DESC, u.id DESC"
    customers = conn.execute(query, params).fetchall()
    conn.close()

    return render_template("admin/customers.html", customers=customers)

# 7. Staff & RBAC
@app.route("/admin/staff")
@admin_required
@super_admin_required
def admin_staff():
    conn = get_db()
    staff_members = conn.execute("SELECT * FROM users WHERE role!='customer' ORDER BY id ASC").fetchall()
    conn.close()
    return render_template("admin/staff.html", staff_members=staff_members)

@app.route("/admin/staff/new", methods=["GET", "POST"])
@app.route("/admin/staff/<int:user_id>/edit", methods=["GET", "POST"])
@admin_required
@super_admin_required
def admin_staff_form_handler(user_id=None):
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone() if user_id else None
    if user_id and not user:
        conn.close()
        abort(404)

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        phone = request.form.get("phone", "").strip()
        role = request.form.get("role", "admin").strip()
        password = request.form.get("password", "")
        perms = request.form.getlist("permissions")

        perms_json = json.dumps(perms)

        if user:
            if password:
                pwd_hash = generate_password_hash(password)
                conn.execute("""
                    UPDATE users SET name=?, username=?, email=?, phone=?, role=?, permissions=?, password_hash=?
                    WHERE id=?
                """, (name, username, email, phone, role, perms_json, pwd_hash, user_id))
            else:
                conn.execute("""
                    UPDATE users SET name=?, username=?, email=?, phone=?, role=?, permissions=?
                    WHERE id=?
                """, (name, username, email, phone, role, perms_json, user_id))
            conn.commit()
            log_audit(session.get("admin_user_id"), session.get("admin_user"), "STAFF_UPDATE", "users", str(user_id), f"Updated staff {username}")
            flash(f"স্টাফ একাউন্ট '{name}' সফলভাবে আপডেট হয়েছে।", "success")
        else:
            if not password:
                flash("পাসওয়ার্ড প্রদান করুন।", "error")
                conn.close()
                return redirect(request.url)
            pwd_hash = generate_password_hash(password)
            cur = conn.execute("""
                INSERT INTO users (name, username, email, phone, role, permissions, password_hash)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, username, email, phone, role, perms_json, pwd_hash))
            new_id = cur.lastrowid
            conn.commit()
            log_audit(session.get("admin_user_id"), session.get("admin_user"), "STAFF_CREATE", "users", str(new_id), f"Created staff {username} with role {role}")
            flash(f"নতুন স্টাফ একাউন্ট '{name}' সফলভাবে তৈরি হয়েছে।", "success")

        conn.close()
        return redirect(url_for("admin_staff"))

    conn.close()
    return render_template("admin/staff_form.html", user=user)

@app.route("/admin/staff/new", endpoint="admin_staff_new")
@app.route("/admin/staff/<int:user_id>/edit", endpoint="admin_staff_edit")
def _staff_form_bridge(user_id=None):
    return admin_staff_form_handler(user_id)

@app.post("/admin/staff/<int:user_id>/toggle")
@admin_required
@super_admin_required
def admin_staff_toggle(user_id):
    conn = get_db()
    conn.execute("UPDATE users SET is_active = CASE is_active WHEN 1 THEN 0 ELSE 1 END WHERE id=?", (user_id,))
    conn.commit()
    conn.close()
    flash("স্টাফ একাউন্টের স্ট্যাটাস পরিবর্তন হয়েছে।", "success")
    return redirect(url_for("admin_staff"))

# 8. Coupons Management
@app.route("/admin/coupons")
@admin_required
@permission_required("coupons_manage")
def admin_coupons():
    conn = get_db()
    coupons = conn.execute("SELECT * FROM coupons ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("admin/coupons.html", coupons=coupons)

@app.post("/admin/coupons/add")
@admin_required
@permission_required("coupons_manage")
def admin_coupon_add():
    code = request.form.get("code", "").strip().upper()
    discount_type = request.form.get("discount_type", "fixed")
    try:
        discount_value = float(request.form.get("discount_value", 0))
        min_order_value = float(request.form.get("min_order_value", 0))
        max_disc_raw = request.form.get("max_discount", "").strip()
        max_discount = float(max_disc_raw) if max_disc_raw else None
        usage_limit = int(request.form.get("usage_limit", 500))
    except ValueError:
        flash("সঠিক সংখ্যা প্রদান করুন।", "error")
        return redirect(url_for("admin_coupons"))

    if code and discount_value > 0:
        conn = get_db()
        try:
            conn.execute("""
                INSERT INTO coupons (code, discount_type, discount_value, min_order_value, max_discount, usage_limit)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (code, discount_type, discount_value, min_order_value, max_discount, usage_limit))
            conn.commit()
            log_audit(session.get("admin_user_id"), session.get("admin_user"), "COUPON_CREATE", "coupons", code, f"Created coupon {code}")
            flash(f"কুপন '{code}' সফলভাবে তৈরি হয়েছে।", "success")
        except sqlite3.IntegrityError:
            flash("এই কোডটি ইতোমধ্যে বিদ্যমান।", "error")
        finally:
            conn.close()

    return redirect(url_for("admin_coupons"))

@app.post("/admin/coupons/<int:coupon_id>/delete")
@admin_required
@permission_required("coupons_manage")
def admin_coupon_delete(coupon_id):
    conn = get_db()
    conn.execute("DELETE FROM coupons WHERE id=?", (coupon_id,))
    conn.commit()
    conn.close()
    flash("কুপনটি মুছে ফেলা হয়েছে।", "success")
    return redirect(url_for("admin_coupons"))

# 9. Delivery Zones
@app.route("/admin/delivery")
@admin_required
def admin_delivery_zones():
    conn = get_db()
    zones = conn.execute("SELECT * FROM delivery_zones ORDER BY id ASC").fetchall()
    conn.close()
    return render_template("admin/delivery_zones.html", zones=zones)

@app.post("/admin/delivery/add")
@admin_required
def admin_delivery_zone_add():
    name = request.form.get("name", "").strip()
    fee = float(request.form.get("delivery_fee", 70))
    free_thresh = float(request.form.get("free_delivery_threshold", 2000))
    est_days = request.form.get("estimated_days", "২-৩ কার্যদিবস").strip()

    if name:
        conn = get_db()
        conn.execute("""
            INSERT INTO delivery_zones (name, delivery_fee, free_delivery_threshold, estimated_days)
            VALUES (?, ?, ?, ?)
        """, (name, fee, free_thresh, est_days))
        conn.commit()
        conn.close()
        flash(f"ডেলিভারি জোন '{name}' যুক্ত হয়েছে।", "success")

    return redirect(url_for("admin_delivery_zones"))

@app.post("/admin/delivery/<int:zone_id>/delete")
@admin_required
def admin_delivery_zone_delete(zone_id):
    conn = get_db()
    conn.execute("DELETE FROM delivery_zones WHERE id=?", (zone_id,))
    conn.commit()
    conn.close()
    flash("ডেলিভারি জোন মুছে ফেলা হয়েছে।", "success")
    return redirect(url_for("admin_delivery_zones"))

# 10. Payment Methods Configuration
@app.route("/admin/payment-methods", methods=["GET", "POST"])
@admin_required
def admin_payment_methods():
    conn = get_db()
    if request.method == "POST":
        cod_enabled = "1" if request.form.get("cod_enabled") else "0"
        bkash_enabled = "1" if request.form.get("bkash_enabled") else "0"
        bkash_number = request.form.get("bkash_number", "").strip()
        bkash_type = request.form.get("bkash_type", "Merchant").strip()
        bkash_instructions = request.form.get("bkash_instructions", "").strip()

        nagad_enabled = "1" if request.form.get("nagad_enabled") else "0"
        nagad_number = request.form.get("nagad_number", "").strip()
        nagad_type = request.form.get("nagad_type", "Merchant").strip()
        nagad_instructions = request.form.get("nagad_instructions", "").strip()

        updates = [
            ("cod_enabled", cod_enabled),
            ("bkash_enabled", bkash_enabled),
            ("bkash_number", bkash_number),
            ("bkash_type", bkash_type),
            ("bkash_instructions", bkash_instructions),
            ("nagad_enabled", nagad_enabled),
            ("nagad_number", nagad_number),
            ("nagad_type", nagad_type),
            ("nagad_instructions", nagad_instructions),
        ]
        for k, v in updates:
            conn.execute("INSERT OR REPLACE INTO site_settings (key, value, group_name) VALUES (?, ?, 'payment')", (k, v))
        conn.commit()
        log_audit(session.get("admin_user_id"), session.get("admin_user"), "PAYMENT_SETTINGS_UPDATE", "settings", "payment", "Updated payment gateways")
        flash("পেমেন্ট মেথড কনফিগারেশন সংরক্ষিত হয়েছে।", "success")

    settings = get_settings()
    conn.close()
    return render_template("admin/payment_methods.html", settings=settings)

# 11. Homepage & CMS Customizer
@app.route("/admin/cms/homepage", methods=["GET", "POST"])
@admin_required
@permission_required("cms_manage")
def admin_cms_homepage():
    conn = get_db()
    if request.method == "POST":
        keys = [
            "announcement_enabled", "announcement_text", "announcement_link",
            "hero_badge", "hero_headline", "hero_subtitle",
            "hero_primary_btn_text", "hero_primary_btn_link",
            "hero_secondary_btn_text", "hero_secondary_btn_link", "hero_image",
            "trust_item_1_title", "trust_item_1_desc",
            "trust_item_2_title", "trust_item_2_desc",
            "trust_item_3_title", "trust_item_3_desc",
            "trust_item_4_title", "trust_item_4_desc",
            "story_title", "story_content", "story_image"
        ]
        for k in keys:
            val = request.form.get(k, "")
            if k == "announcement_enabled":
                val = "1" if val else "0"
            conn.execute("INSERT OR REPLACE INTO site_settings (key, value, group_name) VALUES (?, ?, 'homepage')", (k, val))

        conn.commit()
        log_audit(session.get("admin_user_id"), session.get("admin_user"), "CMS_HOMEPAGE_UPDATE", "cms", "homepage", "Updated homepage hero & copy")
        flash("হোমপেজ কনটেন্ট সফলভাবে সংরক্ষিত হয়েছে। স্টোরফ্রন্টে দেখুন।", "success")

    settings = get_settings()
    conn.close()
    return render_template("admin/cms_homepage.html", settings=settings)

# 12. Blog & Recipes CMS
@app.route("/admin/cms/blog")
@admin_required
@permission_required("cms_manage")
def admin_cms_blog():
    conn = get_db()
    posts = conn.execute("SELECT * FROM blog_posts ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("admin/cms_blog.html", posts=posts)

@app.route("/admin/cms/blog/new", methods=["GET", "POST"])
@app.route("/admin/cms/blog/<int:post_id>/edit", methods=["GET", "POST"])
@admin_required
@permission_required("cms_manage")
def admin_blog_form_handler(post_id=None):
    conn = get_db()
    post = conn.execute("SELECT * FROM blog_posts WHERE id=?", (post_id,)).fetchone() if post_id else None
    if post_id and not post:
        conn.close()
        abort(404)

    if request.method == "POST":
        title = request.form.get("title", "").strip()
        slug = request.form.get("slug", "").strip()
        category = request.form.get("category", "স্বাস্থ্য ও পুষ্টি").strip()
        author_name = request.form.get("author_name", "Pure Drop টিম").strip()
        cover_image = request.form.get("cover_image", "").strip()
        excerpt = request.form.get("excerpt", "").strip()
        content = request.form.get("content", "").strip()
        is_published = 1 if request.form.get("is_published") else 0

        if title and content and slug:
            if post:
                conn.execute("""
                    UPDATE blog_posts SET
                        title=?, slug=?, category=?, author_name=?, cover_image=?, excerpt=?, content=?, is_published=?
                    WHERE id=?
                """, (title, slug, category, author_name, cover_image, excerpt, content, is_published, post_id))
                log_audit(session.get("admin_user_id"), session.get("admin_user"), "BLOG_UPDATE", "blog", str(post_id), f"Updated {title}")
                flash("প্রবন্ধটি আপডেট হয়েছে।", "success")
            else:
                cur = conn.execute("""
                    INSERT INTO blog_posts (title, slug, category, author_name, cover_image, excerpt, content, is_published)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (title, slug, category, author_name, cover_image, excerpt, content, is_published))
                log_audit(session.get("admin_user_id"), session.get("admin_user"), "BLOG_CREATE", "blog", str(cur.lastrowid), f"Created {title}")
                flash("নতুন প্রবন্ধ প্রকাশিত হয়েছে।", "success")
            conn.commit()
            conn.close()
            return redirect(url_for("admin_cms_blog"))

    conn.close()
    return render_template("admin/blog_form.html", post=post)

@app.route("/admin/cms/blog/new", endpoint="admin_blog_new")
@app.route("/admin/cms/blog/<int:post_id>/edit", endpoint="admin_blog_edit")
def _blog_form_bridge(post_id=None):
    return admin_blog_form_handler(post_id)

@app.post("/admin/cms/blog/<int:post_id>/delete")
@admin_required
@permission_required("cms_manage")
def admin_blog_delete(post_id):
    conn = get_db()
    conn.execute("DELETE FROM blog_posts WHERE id=?", (post_id,))
    conn.commit()
    conn.close()
    flash("প্রবন্ধটি মুছে ফেলা হয়েছে।", "success")
    return redirect(url_for("admin_cms_blog"))

# 13. Customer Reviews Moderation
@app.route("/admin/cms/reviews")
@admin_required
@permission_required("reviews_manage")
def admin_cms_reviews():
    conn = get_db()
    reviews = conn.execute("""
        SELECT r.*, p.name_bn AS product_name
        FROM reviews r
        JOIN products p ON r.product_id = p.id
        ORDER BY r.id DESC
    """).fetchall()
    conn.close()
    return render_template("admin/cms_reviews.html", reviews=reviews)

@app.post("/admin/cms/reviews/<int:review_id>/status")
@admin_required
@permission_required("reviews_manage")
def admin_review_status(review_id):
    status = request.args.get("status", "approved")
    conn = get_db()
    conn.execute("UPDATE reviews SET status=? WHERE id=?", (status, review_id))
    conn.commit()
    conn.close()
    flash(f"রিভিউ স্ট্যাটাস '{status}' করা হয়েছে।", "success")
    return redirect(url_for("admin_cms_reviews"))

@app.post("/admin/cms/reviews/<int:review_id>/delete")
@admin_required
@permission_required("reviews_manage")
def admin_review_delete(review_id):
    conn = get_db()
    conn.execute("DELETE FROM reviews WHERE id=?", (review_id,))
    conn.commit()
    conn.close()
    flash("রিভিউটি মুছে ফেলা হয়েছে।", "success")
    return redirect(url_for("admin_cms_reviews"))

# 14. Subscribers List
@app.route("/admin/subscribers")
@admin_required
def admin_subscribers():
    conn = get_db()
    subscribers = conn.execute("SELECT * FROM subscribers ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("admin/subscribers.html", subscribers=subscribers)

@app.post("/admin/subscribers/<int:sub_id>/delete")
@admin_required
def admin_subscriber_delete(sub_id):
    conn = get_db()
    conn.execute("DELETE FROM subscribers WHERE id=?", (sub_id,))
    conn.commit()
    conn.close()
    flash("সাবস্ক্রাইবার মুছে ফেলা হয়েছে।", "success")
    return redirect(url_for("admin_subscribers"))

# 15. Store Settings
@app.route("/admin/settings", methods=["GET", "POST"])
@admin_required
@super_admin_required
def admin_settings():
    conn = get_db()
    if request.method == "POST":
        fields = [
            "site_name", "site_tagline_bn", "site_tagline_en",
            "contact_phone", "contact_whatsapp", "contact_email", "store_address",
            "facebook_url", "instagram_url", "youtube_url"
        ]
        for f in fields:
            val = request.form.get(f, "").strip()
            conn.execute("INSERT OR REPLACE INTO site_settings (key, value, group_name) VALUES (?, ?, 'general')", (f, val))
        conn.commit()
        log_audit(session.get("admin_user_id"), session.get("admin_user"), "SETTINGS_UPDATE", "settings", "general", "Updated site branding & contact")
        flash("সাইট সেটিংস সফলভাবে সংরক্ষিত হয়েছে।", "success")

    settings = get_settings()
    conn.close()
    return render_template("admin/settings.html", settings=settings)

# 16. Security Audit Logs
@app.route("/admin/audit-logs")
@admin_required
@super_admin_required
def admin_audit_logs():
    conn = get_db()
    logs = conn.execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 100").fetchall()
    conn.close()
    return render_template("admin/audit_logs.html", logs=logs)

# 17. Reports & CSV Data Exports
@app.route("/admin/export/orders")
@admin_required
@permission_required("reports_export")
def admin_export_orders():
    conn = get_db()
    orders = conn.execute("SELECT * FROM orders ORDER BY id DESC").fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Order ID", "Customer Name", "Phone", "District", "Thana/Area", "Address",
        "Payment Method", "Payment Status", "TrxID", "Subtotal", "Delivery Fee",
        "Discount", "Total", "Status", "Courier", "Tracking Code", "Date"
    ])
    for o in orders:
        writer.writerow([
            o["order_number"], o["customer_name"], o["phone"], o["district"],
            o["thana_area"], o["full_address"], o["payment_method"], o["payment_status"],
            o["payment_trx_id"], o["subtotal"], o["delivery_fee"], o["discount_amount"],
            o["total"], o["status"], o["courier_name"], o["tracking_code"], o["created_at"]
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=pure_drop_orders_{datetime.now().strftime('%Y%m%d')}.csv"}
    )

@app.route("/admin/export/products")
@admin_required
@permission_required("reports_export")
def admin_export_products():
    conn = get_db()
    products = conn.execute("SELECT * FROM products ORDER BY id ASC").fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Name (BN)", "Name (EN)", "SKU", "Category", "Regular Price", "Discount Price", "Cost Price", "Stock", "Unit", "Active"])
    for p in products:
        writer.writerow([
            p["id"], p["name_bn"], p["name_en"], p["sku"], p["category_name"],
            p["regular_price"], p["discount_price"], p["cost_price"], p["stock"], p["unit"], p["is_active"]
        ])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=pure_drop_products_{datetime.now().strftime('%Y%m%d')}.csv"}
    )

@app.route("/admin/export/customers")
@admin_required
@permission_required("reports_export")
def admin_export_customers():
    conn = get_db()
    users = conn.execute("SELECT id, name, username, email, phone, created_at FROM users WHERE role='customer'").fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Name", "Username", "Email", "Phone", "Joined Date"])
    for u in users:
        writer.writerow([u["id"], u["name"], u["username"], u["email"], u["phone"], u["created_at"]])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=pure_drop_customers_{datetime.now().strftime('%Y%m%d')}.csv"}
    )

@app.route("/admin/export/subscribers")
@admin_required
def admin_export_subscribers():
    conn = get_db()
    subs = conn.execute("SELECT id, email, created_at FROM subscribers ORDER BY id ASC").fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Email", "Date Subscribed"])
    for s in subs:
        writer.writerow([s["id"], s["email"], s["created_at"]])

    output.seek(0)
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=pure_drop_newsletter_subscribers.csv"}
    )

# ==============================================================================
# ERROR HANDLERS
# ==============================================================================
@app.errorhandler(404)
def not_found(e):
    return render_template("404.html"), 404

@app.errorhandler(500)
def server_error(e):
    app.logger.exception("Internal server error")
    return "<h2 style='text-align:center;padding:50px;font-family:sans-serif;'>সার্ভারে সাময়িক ত্রুটি ঘটেছে। অনুগ্রহ করে কিছুক্ষণ পর আবার চেষ্টা করুন।</h2>", 500

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=True)
