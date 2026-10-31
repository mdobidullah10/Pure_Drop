from functools import wraps
from flask import session, redirect, url_for, flash, request, abort
import json
from database import get_db

ROLE_PERMISSIONS = {
    'super_admin': [
        'all', 'dashboard_view', 'products_manage', 'inventory_manage', 'orders_manage',
        'customers_manage', 'staff_manage', 'settings_manage', 'coupons_manage',
        'cms_manage', 'reviews_manage', 'reports_export', 'audit_logs_view'
    ],
    'admin': [
        'dashboard_view', 'products_manage', 'inventory_manage', 'orders_manage',
        'customers_manage', 'coupons_manage', 'cms_manage', 'reviews_manage', 'reports_export'
    ],
    'order_manager': [
        'dashboard_view', 'orders_manage', 'reports_export'
    ],
    'product_manager': [
        'dashboard_view', 'products_manage', 'inventory_manage'
    ],
    'moderator': [
        'dashboard_view', 'reviews_manage', 'cms_manage'
    ],
    'customer_support': [
        'dashboard_view', 'orders_manage', 'customers_manage'
    ]
}

def is_setup_required():
    """Returns True if no super_admin exists in the database."""
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM users WHERE role='super_admin' AND is_active=1").fetchone()[0]
    conn.close()
    return count == 0

def get_current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE id=? AND is_active=1", (user_id,)).fetchone()
    conn.close()
    return user

def user_has_permission(user, permission):
    if not user:
        return False
    role = user["role"]
    if role == "super_admin":
        return True
    
    # Check default role permissions
    allowed = ROLE_PERMISSIONS.get(role, [])
    if 'all' in allowed or permission in allowed:
        return True
    
    # Check custom granted permissions JSON in user record
    try:
        custom_perms = json.loads(user["permissions"] or "[]")
        if permission in custom_perms:
            return True
    except Exception:
        pass

    return False

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            flash("অনুগ্রহ করে প্রথমে লগইন করুন।", "error")
            return redirect(url_for("customer_login", next=request.path))
        return fn(*args, **kwargs)
    return wrapper

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if is_setup_required():
            return redirect(url_for("admin_setup"))

        user_id = session.get("admin_user_id")
        if not user_id:
            return redirect(url_for("admin_login", next=request.path))
        
        user = get_db().execute("SELECT * FROM users WHERE id=? AND is_active=1", (user_id,)).fetchone()
        if not user or user["role"] == "customer":
            session.pop("admin_user_id", None)
            flash("আপনার প্রশাসনিক একাউন্টে প্রবেশাধিকার নেই।", "error")
            return redirect(url_for("admin_login"))
        
        return fn(*args, **kwargs)
    return wrapper

def super_admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if is_setup_required():
            return redirect(url_for("admin_setup"))

        user_id = session.get("admin_user_id")
        if not user_id:
            return redirect(url_for("admin_login", next=request.path))
        
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE id=? AND is_active=1", (user_id,)).fetchone()
        conn.close()
        
        if not user or user["role"] != "super_admin":
            flash("এই কার্যটির জন্য শুধুমাত্র সুপার অ্যাডমিনের অনুমতি রয়েছে।", "error")
            return redirect(url_for("admin_dashboard"))
        
        return fn(*args, **kwargs)
    return wrapper

def permission_required(permission):
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if is_setup_required():
                return redirect(url_for("admin_setup"))

            user_id = session.get("admin_user_id")
            if not user_id:
                return redirect(url_for("admin_login", next=request.path))
            
            conn = get_db()
            user = conn.execute("SELECT * FROM users WHERE id=? AND is_active=1", (user_id,)).fetchone()
            conn.close()

            if not user or not user_has_permission(user, permission):
                flash("এই পেজে প্রবেশের জন্য আপনার প্রয়োজনীয় পারমিশন নেই।", "error")
                return redirect(url_for("admin_dashboard"))
            
            return fn(*args, **kwargs)
        return wrapper
    return decorator
