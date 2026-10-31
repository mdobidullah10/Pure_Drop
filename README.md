# 🌿 Pure Drop — Premium Bangladeshi E-Commerce Platform
> “প্রকৃতির বিশুদ্ধতা, পরিবারের সুস্থতা” | Pure Nature. Healthy Living.

Pure Drop is an award-winning, production-oriented e-commerce platform and complete Super Admin CMS engineered specifically for premium Bangladeshi natural and organic food products (Ghee, Raw Honey, Mustard Oil, Organic Chia Seeds, and Combos).

---

## 💎 Key Highlights

1. **Brand Identity & Creative Direction:**
   - **Colors:** Deep forest green (`#0d3826`), natural leaf green (`#276749`), warm ivory (`#faf7f2`), clean white, restrained gold accents (`#c99738`).
   - **Typography:** Elegant Bengali font *Hind Siliguri* paired with *Inter / DM Sans*.
   - **Assets:** Official Pure Drop drop-and-leaf logo, high-resolution product photography, curated campaign posters, and promotional banners.

2. **Storefront Features:**
   - **Announcement Bar:** Dynamic banner with live promotion notice & direct WhatsApp link.
   - **Premium Header:** Live search with instant product suggestions, customer account link, wishlist badge counter, and cart drawer.
   - **Signature Hero Section:** Warm natural food visual art direction with editable headline, badge, CTA buttons, and trust stamps.
   - **Shop by Category & Best Sellers:** Live database-driven product catalog with weight/unit badges, discount percentages, and AJAX Add to Cart.
   - **Product Detail Experience:** Multi-image gallery with thumbnail switcher, weight/size variations, nutrition & ingredients tabs, usage instructions, customer review submission, and related products.
   - **Live Shopping Cart Drawer & Full Cart:** Real-time subtotal, quantity updates, coupon code discounts, and free delivery progress tracker.
   - **Bangladeshi Checkout:** District-aware delivery calculations (Inside Dhaka ৳70, Outside Dhaka ৳130, Free over ৳2,000), 11-digit phone validation, Cash on Delivery, bKash (with TrxID input), and Nagad (with TrxID input).
   - **Live Order Tracking:** 4-step visual stepper (Order Placed -> Processing -> In Transit -> Delivered) with courier partner name and tracking number.
   - **Editorial Blog & Recipes:** Authentic articles on purity testing, health benefits of honey, and cold-pressed mustard oil.

3. **Super Admin Control Center (18+ Modules):**
   - **One-Time Secure Setup:** Locks automatically once the primary Super Admin account is established. No hardcoded default passwords.
   - **Executive Dashboard:** Live metrics for total sales revenue (৳), total orders, pending orders, and low-stock alerts.
   - **Product Management:** Full CRUD, image uploads/URLs, variations, selling price, cost price, and stock levels.
   - **Inventory Control:** Low-stock threshold warnings (< 10 units), fast inline stock adjustments (+/-), and stock change audit logs.
   - **Order Lifecycle:** Filter by status (Pending, Confirmed, Processing, Shipped, Delivered, Cancelled), courier assignment (Steadfast, Pathao, RedX), admin internal notes, and printable invoices.
   - **Role-Based Access Control (RBAC):** Super Admin can create Admins, Order Managers, Product Managers, Moderators, and Customer Support with granular permissions.
   - **Coupons & Campaigns:** Fixed or percentage discounts, minimum order value, max cap, and usage limits.
   - **Delivery Zones & Charges:** Dynamic zones and free delivery threshold configuration.
   - **Payment Configuration:** Merchant / Personal bKash & Nagad numbers and customer payment instructions.
   - **Homepage CMS:** Change announcement text, hero headlines, CTA links, trust highlights, and brand story without touching code.
   - **Customer Reviews & Blog CMS:** Approve/reject customer reviews, write and publish recipe articles.
   - **Data Exports (CSV):** One-click CSV export for Orders, Products, Customers, and Newsletter Subscribers.
   - **Security Audit Logs:** Complete audit trail tracking administrative actions with timestamps and IP addresses.

---

## 🚀 Quick Start Guide

### 1. Requirements
- Python 3.10+ (Python 3.12 recommended)
- SQLite3 (built into Python)

### 2. Installation
```bash
# Clone or navigate to the project folder
cd C:\Users\ELE\.gemini\antigravity\scratch\pure_drop

# Activate virtual environment
.\.venv\Scripts\activate

# Install dependencies (if needed)
pip install -r requirements.txt
```

### 3. Run Development Server
```bash
python app.py
```
Open your browser and navigate to:
- **Storefront:** [http://127.0.0.1:5000](http://127.0.0.1:5000)
- **Super Admin Setup / Login:** [http://127.0.0.1:5000/admin](http://127.0.0.1:5000/admin)

---

## 🛡️ Super Admin Initial Setup
1. On the very first visit to `/admin`, you will be greeted by the **One-Time Super Admin Setup Wizard**.
2. Enter your Name, Username, Email, Bangladeshi Mobile Number, and a secure Password (8+ characters).
3. Once submitted, the setup route `/admin/setup` is **permanently locked**.
4. Future logins take place at `/admin/login`.

---

## 🧪 Testing & Verification
A complete automated test suite is provided to verify all core workflows:
```bash
python test_suite.py
python test_advanced_features.py
```
Both test suites test:
- Storefront rendering & Bengali typography.
- Super Admin setup & password hashing verification.
- Cart drawer AJAX, coupon application, and Cash on Delivery order creation.
- Atomic stock decrements in the SQLite database.
- Live order tracking with progress timeline.
- Order status updates, courier tracking assignments, and staff RBAC.
- Dynamic CMS homepage customization reflecting on the storefront.
- Product CRUD, active/draft toggle, customer review moderation, and CSV exports.

---

## 📁 Project Structure
```
pure_drop/
├── app.py                      # Application core & route handlers
├── database.py                 # Schema, migrations & seed data
├── auth_helpers.py             # RBAC & authentication guards
├── requirements.txt            # Python dependencies
├── pure_drop.db                # SQLite database with WAL mode
├── static/
│   ├── css/
│   │   ├── pure-drop.css       # Customer storefront design system
│   │   └── admin.css           # Super Admin Control Center styling
│   ├── js/
│   │   ├── main.js             # Cart drawer, live search, district logic
│   │   └── admin.js            # Stock adjustments & admin controls
│   ├── images/                 # Pure Drop logo & brand posters
│   └── uploads/                # Product image uploads
└── templates/
    ├── base.html               # Storefront master template
    ├── home.html               # Premium homepage
    ├── products.html           # Catalog & category filters
    ├── product_detail.html     # Product page with tabs & reviews
    ├── cart.html               # Full cart & coupon discounts
    ├── checkout.html           # Bangladeshi checkout (COD, bKash, Nagad)
    ├── order_success.html      # Receipt & printable invoice
    ├── track.html              # Live 4-step order tracking
    ├── wishlist.html           # Customer wishlist
    ├── blog.html               # Recipe & nutrition articles
    ├── blog_detail.html        # Article reader
    ├── about.html, contact.html, policy.html
    ├── customer/               # Login, register, profile
    └── admin/                  # 18+ Super Admin modules
```

---

## 🔒 Security Standards
- Passwords hashed using PBKDF2 with SHA-256 (`generate_password_hash`).
- Role-based server-side checks on all administrative endpoints.
- Atomic transactions (`BEGIN IMMEDIATE`) on checkout to prevent race conditions or stock overselling.
- Uploaded image filenames sanitized using `secure_filename`.
- Granular administrative audit logging for sensitive actions.

---
© 2026 Pure Drop. “প্রকৃতির বিশুদ্ধতা, পরিবারের সুস্থতা” — Pure Nature. Healthy Living.
