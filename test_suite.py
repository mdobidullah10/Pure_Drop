import unittest
import json
from app import app
import database

class PureDropFullStackTestCase(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        app.config["WTF_CSRF_ENABLED"] = False
        self.client = app.test_client()

    def test_01_storefront_homepage(self):
        """Test homepage renders properly with brand elements"""
        res = self.client.get("/")
        self.assertEqual(res.status_code, 200)
        html = res.data.decode("utf-8")
        self.assertIn("Pure", html)
        self.assertIn("Drop", html)
        self.assertIn("ঘি", html)
        self.assertIn("মধু", html)
        self.assertIn("সরিষার তেল", html)
        print("[PASS] Test 1: Storefront homepage renders with brand identity and categories.")

    def test_02_super_admin_setup_and_login(self):
        """Test one-time Super Admin setup and authentication"""
        # 1. Post setup
        res = self.client.post("/admin/setup", data={
            "name": "সুপার অ্যাডমিন",
            "username": "superadmin",
            "email": "superadmin@puredropbd.com",
            "phone": "01711000000",
            "password": "StrongPassword123!",
            "confirm_password": "StrongPassword123!"
        }, follow_redirects=True)
        self.assertEqual(res.status_code, 200)

        # 2. Setup should now be locked
        res_locked = self.client.get("/admin/setup", follow_redirects=False)
        self.assertEqual(res_locked.status_code, 302)

        # 3. Test admin login
        res_login = self.client.post("/admin/login", data={
            "username": "superadmin",
            "password": "StrongPassword123!"
        }, follow_redirects=True)
        self.assertEqual(res_login.status_code, 200)
        html = res_login.data.decode("utf-8")
        self.assertIn("ড্যাশবোর্ড", html)
        print("[PASS] Test 2: One-time Super Admin setup completed, setup page locked, login authenticated.")

    def test_03_cart_and_checkout_workflow(self):
        """Test adding to cart, applying coupon, and completing Cash on Delivery order"""
        conn = database.get_db()
        product = conn.execute("SELECT id, stock FROM products WHERE id=1").fetchone()
        initial_stock = product["stock"]
        conn.close()

        # 1. Add to cart via AJAX
        res_add = self.client.post("/api/cart/add", data={
            "product_id": 1,
            "quantity": 2
        })
        self.assertEqual(res_add.status_code, 200)
        data = json.loads(res_add.data)
        self.assertTrue(data["success"])
        self.assertEqual(data["count"], 2)

        # 2. Check cart drawer API
        res_cart = self.client.get("/api/cart")
        self.assertEqual(res_cart.status_code, 200)
        cart_json = json.loads(res_cart.data)
        self.assertEqual(len(cart_json["items"]), 1)
        self.assertGreater(cart_json["subtotal"], 0)

        # 3. Apply Coupon
        res_coupon = self.client.post("/coupon/apply", data={
            "coupon_code": "PURE10"
        }, follow_redirects=True)
        self.assertEqual(res_coupon.status_code, 200)

        # 4. Submit Checkout
        res_checkout = self.client.post("/checkout/submit", data={
            "customer_name": "আরিফুল ইসলাম",
            "phone": "01755123456",
            "email": "ariful@example.com",
            "district": "Dhaka",
            "thana_area": "ধানমন্ডি",
            "full_address": "বাড়ি #৭, রোড #৪, ধানমন্ডি, ঢাকা",
            "order_notes": "অফিস সময়ে ফোন করবেন",
            "payment_method": "Cash on Delivery"
        }, follow_redirects=True)
        self.assertEqual(res_checkout.status_code, 200)
        html = res_checkout.data.decode("utf-8")
        self.assertIn("অর্ডারটি সফলভাবে সম্পন্ন হয়েছে", html)
        self.assertIn("PD-", html)

        # 5. Check stock reduction
        conn = database.get_db()
        updated_product = conn.execute("SELECT stock FROM products WHERE id=1").fetchone()
        self.assertEqual(updated_product["stock"], initial_stock - 2)
        
        # Verify order in DB
        last_order = conn.execute("SELECT * FROM orders ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(last_order["customer_name"], "আরিফুল ইসলাম")
        self.assertEqual(last_order["status"], "Pending")
        conn.close()

        print(f"[PASS] Test 3: Cart added, coupon applied, Order {last_order['order_number']} placed, stock decremented by 2.")

    def test_04_order_tracking(self):
        """Test order tracking with order number and phone"""
        conn = database.get_db()
        last_order = conn.execute("SELECT order_number, phone FROM orders ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()

        res_track = self.client.post("/track", data={
            "order_number": last_order["order_number"],
            "phone": last_order["phone"]
        })
        self.assertEqual(res_track.status_code, 200)
        html = res_track.data.decode("utf-8")
        self.assertIn(last_order["order_number"], html)
        self.assertIn("অর্ডার গৃহীত", html)
        print("[PASS] Test 4: Live order tracking verified with progress timeline.")

    def test_05_admin_management_and_cms_customization(self):
        """Test admin order processing, new staff creation, and CMS homepage editing"""
        # Login
        self.client.post("/admin/login", data={
            "username": "superadmin",
            "password": "StrongPassword123!"
        })

        # 1. Update order status
        conn = database.get_db()
        last_order = conn.execute("SELECT id FROM orders ORDER BY id DESC LIMIT 1").fetchone()
        conn.close()

        res_update = self.client.post(f"/admin/orders/{last_order['id']}", data={
            "status": "Shipped",
            "payment_status": "Paid",
            "payment_trx_id": "BKASH7788",
            "courier_name": "Steadfast Courier",
            "tracking_code": "SF-991234",
            "admin_notes": "অর্ডার কুরিয়ারে বুকিং সম্পন্ন"
        }, follow_redirects=True)
        self.assertEqual(res_update.status_code, 200)

        # Verify DB
        conn = database.get_db()
        order_row = conn.execute("SELECT status, courier_name, tracking_code FROM orders WHERE id=?", (last_order["id"],)).fetchone()
        self.assertEqual(order_row["status"], "Shipped")
        self.assertEqual(order_row["courier_name"], "Steadfast Courier")
        conn.close()

        # 2. Create Staff member (Order Manager)
        res_staff = self.client.post("/admin/staff/new", data={
            "name": "কামাল উদ্দিন",
            "username": "kamal_order",
            "email": "kamal@puredropbd.com",
            "phone": "01811223399",
            "role": "order_manager",
            "password": "ManagerPass123!",
            "permissions": ["orders_manage", "dashboard_view"]
        }, follow_redirects=True)
        self.assertEqual(res_staff.status_code, 200)

        # 3. Dynamic Homepage CMS Customization
        new_headline = "প্রকৃতির শ্রেষ্ঠ খাঁটি উপহার — Pure Drop"
        res_cms = self.client.post("/admin/cms/homepage", data={
            "announcement_enabled": "1",
            "announcement_text": "বৈশাখী বিশেষ অফার! সকল পণ্যে আকর্ষণীয় ছাড়!",
            "announcement_link": "/products",
            "hero_badge": "১০০% খাঁটি ও পরীক্ষিত",
            "hero_headline": new_headline,
            "hero_subtitle": "আমাদের লক্ষ্য আপনার প্রতিটি খাবারকে খাঁটি ও পুষ্টিকর রাখা।",
            "hero_primary_btn_text": "পণ্য কিনুন",
            "hero_primary_btn_link": "/products",
            "hero_secondary_btn_text": "আমাদের গল্প",
            "hero_secondary_btn_link": "/about",
            "hero_image": "/static/images/homepage_reference.png",
            "trust_item_1_title": "সহজ অর্ডার",
            "trust_item_1_desc": "১ মিনিটে অর্ডার",
            "trust_item_2_title": "২৪/৭ কাস্টমার সাপোর্ট",
            "trust_item_2_desc": "সরাসরি সহায়তা",
            "trust_item_3_title": "দ্রুত ডেলিভারি",
            "trust_item_3_desc": "২৪-৪৮ ঘণ্টায় ঘরে",
            "trust_item_4_title": "ক্যাশ অন ডেলিভারি",
            "trust_item_4_desc": "পণ্য দেখে টাকা দিন",
            "story_title": "খাঁটি পণ্যের নিশ্চয়তা",
            "story_content": "আমরা কোনো আপোষ করি না মানের বিষয়ে।",
            "story_image": "/static/images/poster_natural.png"
        }, follow_redirects=True)
        self.assertEqual(res_cms.status_code, 200)

        # 4. Verify storefront reflects CMS changes dynamically!
        res_home = self.client.get("/")
        html_home = res_home.data.decode("utf-8")
        self.assertIn(new_headline, html_home)
        self.assertIn("বৈশাখী বিশেষ অফার", html_home)
        print("[PASS] Test 5: Order status updated to Shipped with courier tracking, staff created, and CMS homepage dynamically changed and reflected on storefront!")

if __name__ == "__main__":
    unittest.main()
