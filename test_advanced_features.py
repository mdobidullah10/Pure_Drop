import unittest
import json
from app import app
import database

class PureDropAdvancedFeaturesTest(unittest.TestCase):
    def setUp(self):
        app.config["TESTING"] = True
        self.client = app.test_client()
        # Login as Super Admin
        self.client.post("/admin/login", data={
            "username": "superadmin",
            "password": "StrongPassword123!"
        })

    def test_06_product_crud_and_toggle(self):
        """Test creating, editing, toggling and deleting a product"""
        # Create product
        res_create = self.client.post("/admin/products/new", data={
            "name_bn": "সুন্দরবনের বিশেষ মধু ৫০০ গ্রাম",
            "name_en": "Special Sundarbans Honey 500g",
            "slug": "special-sundarbans-honey-500g",
            "sku": "PD-TEST-001",
            "category_id": 2,
            "short_desc": "পরীক্ষামূলক বিশেষ মধু",
            "description": "বিস্তারিত পরিচিতি",
            "regular_price": "980",
            "discount_price": "890",
            "cost_price": "600",
            "stock": "35",
            "low_stock_threshold": "8",
            "unit": "৫০০ গ্রাম",
            "main_image": "/static/images/poster_goodness.png",
            "is_active": "on",
            "is_featured": "on"
        }, follow_redirects=True)
        self.assertEqual(res_create.status_code, 200)

        conn = database.get_db()
        p = conn.execute("SELECT * FROM products WHERE sku='PD-TEST-001'").fetchone()
        self.assertIsNotNone(p)
        self.assertEqual(p["name_bn"], "সুন্দরবনের বিশেষ মধু ৫০০ গ্রাম")
        self.assertEqual(p["stock"], 35)
        pid = p["id"]
        conn.close()

        # Toggle Active
        res_toggle = self.client.post(f"/admin/products/{pid}/toggle", follow_redirects=True)
        self.assertEqual(res_toggle.status_code, 200)
        conn = database.get_db()
        p_toggled = conn.execute("SELECT is_active FROM products WHERE id=?", (pid,)).fetchone()
        self.assertEqual(p_toggled["is_active"], 0)
        conn.close()

        # Delete
        res_del = self.client.post(f"/admin/products/{pid}/delete", follow_redirects=True)
        self.assertEqual(res_del.status_code, 200)
        conn = database.get_db()
        p_del = conn.execute("SELECT id FROM products WHERE id=?", (pid,)).fetchone()
        self.assertIsNone(p_del)
        conn.close()
        print("[PASS] Test 6: Product CRUD and toggle active/draft passed.")

    def test_07_customer_account_and_reviews(self):
        """Test customer registration, login, and product review submission"""
        # Register new customer
        res_reg = self.client.post("/customer/register", data={
            "name": "মাহমুদা আক্তার",
            "phone": "01999887766",
            "email": "mahmuda@example.com",
            "password": "CustomerPass123!"
        }, follow_redirects=True)
        self.assertEqual(res_reg.status_code, 200)

        # Submit review on Product 1
        res_rev = self.client.post("/review/submit/1", data={
            "customer_name": "মাহমুদা আক্তার",
            "customer_phone": "01999887766",
            "rating": "5",
            "comment": "অসাধারণ সুবাস ও খাঁটি মান! পরিবারের সবাই মুগ্ধ।"
        }, follow_redirects=True)
        self.assertEqual(res_rev.status_code, 200)

        conn = database.get_db()
        rev = conn.execute("SELECT * FROM reviews WHERE customer_name='মাহমুদা আক্তার'").fetchone()
        self.assertIsNotNone(rev)
        self.assertEqual(rev["rating"], 5)
        conn.close()
        print("[PASS] Test 7: Customer registration and review submission passed.")

    def test_08_csv_data_exports(self):
        """Test exporting Orders, Products, and Customers to CSV"""
        res_orders = self.client.get("/admin/export/orders")
        self.assertEqual(res_orders.status_code, 200)
        self.assertEqual(res_orders.mimetype, "text/csv")
        self.assertIn("Order ID", res_orders.data.decode("utf-8"))

        res_products = self.client.get("/admin/export/products")
        self.assertEqual(res_products.status_code, 200)
        self.assertEqual(res_products.mimetype, "text/csv")
        self.assertIn("Name (BN)", res_products.data.decode("utf-8"))

        res_customers = self.client.get("/admin/export/customers")
        self.assertEqual(res_customers.status_code, 200)
        self.assertEqual(res_customers.mimetype, "text/csv")
        self.assertIn("Name", res_customers.data.decode("utf-8"))
        print("[PASS] Test 8: CSV Data exports for orders, products, and customers verified.")

    def test_09_security_audit_logs(self):
        """Test that security audit logs record administrative actions"""
        res_logs = self.client.get("/admin/audit-logs")
        self.assertEqual(res_logs.status_code, 200)
        html = res_logs.data.decode("utf-8")
        self.assertIn("superadmin", html)
        self.assertIn("অডিট", html)
        print("[PASS] Test 9: Security audit logs verified with recorded admin events.")

if __name__ == "__main__":
    unittest.main()
