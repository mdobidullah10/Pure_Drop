/**
 * PURE DROP — Storefront Interactive Engine
 */

document.addEventListener('DOMContentLoaded', function () {
  initCartDrawer();
  initSearchSuggestions();
  initCheckoutDistrictLogic();
  initPaymentMethodSwitcher();
  initQuantityControls();
  initProductGallery();
  initWishlist();
});

// Toast notification helper
function showToast(message, type = 'success') {
  let toastContainer = document.getElementById('toast-container');
  if (!toastContainer) {
    toastContainer = document.createElement('div');
    toastContainer.id = 'toast-container';
    toastContainer.style.cssText = `
      position: fixed;
      top: 24px;
      right: 24px;
      z-index: 9999;
      display: flex;
      flex-direction: column;
      gap: 10px;
      max-width: 360px;
    `;
    document.body.appendChild(toastContainer);
  }

  const toast = document.createElement('div');
  toast.style.cssText = `
    background: ${type === 'error' ? '#991b1b' : '#0d3826'};
    color: #fff;
    padding: 12px 18px;
    border-radius: 8px;
    box-shadow: 0 4px 16px rgba(0,0,0,0.2);
    font-size: 0.92rem;
    font-family: inherit;
    display: flex;
    align-items: center;
    gap: 10px;
    opacity: 0;
    transform: translateY(-10px);
    transition: all 0.3s ease;
  `;
  toast.innerHTML = `<span>${type === 'error' ? '⚠️' : '🌿'}</span> <span>${message}</span>`;
  toastContainer.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = '1';
    toast.style.transform = 'translateY(0)';
  }, 10);

  setTimeout(() => {
    toast.style.opacity = '0';
    toast.style.transform = 'translateY(-10px)';
    setTimeout(() => toast.remove(), 300);
  }, 3500);
}

// Cart Drawer
function initCartDrawer() {
  const drawer = document.getElementById('cartDrawer');
  const overlay = document.getElementById('cartDrawerOverlay');
  const openButtons = document.querySelectorAll('.cart-open-btn');
  const closeButton = document.getElementById('cartDrawerClose');

  if (!drawer || !overlay) return;

  function openDrawer() {
    drawer.classList.add('active');
    overlay.classList.add('active');
    document.body.style.overflow = 'hidden';
    loadCartItems();
  }

  function closeDrawer() {
    drawer.classList.remove('active');
    overlay.classList.remove('active');
    document.body.style.overflow = '';
  }

  openButtons.forEach(btn => {
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      openDrawer();
    });
  });

  if (closeButton) closeButton.addEventListener('click', closeDrawer);
  overlay.addEventListener('click', closeDrawer);
}

// Fetch Cart Data for Drawer
async function loadCartItems() {
  const container = document.getElementById('cartDrawerItems');
  const subtotalElem = document.getElementById('cartDrawerSubtotal');
  if (!container) return;

  try {
    const res = await fetch('/api/cart');
    const data = await res.json();

    if (!data.items || data.items.length === 0) {
      container.innerHTML = `
        <div style="text-align: center; padding: 40px 10px; color: #64748b;">
          <div style="font-size: 3rem; margin-bottom: 12px;">🛒</div>
          <p style="font-weight: 600;">আপনার কার্ট বর্তমানে খালি আছে।</p>
          <a href="/products" class="btn btn-outline btn-sm" style="margin-top: 16px;">পণ্য দেখতে এখানে ক্লিক করুন</a>
        </div>
      `;
      if (subtotalElem) subtotalElem.textContent = '৳০';
      return;
    }

    let html = '';
    data.items.forEach(item => {
      html += `
        <div class="cart-drawer-item">
          <img src="${item.image || '/static/images/logo.png'}" class="cart-item-thumb" alt="${item.name}">
          <div class="cart-item-details">
            <h4 class="cart-item-title">${item.name}</h4>
            <div style="font-size: 0.8rem; color: #64748b; margin-bottom: 4px;">${item.variant || ''}</div>
            <div style="display: flex; align-items: center; justify-content: space-between;">
              <span class="cart-item-price">৳${item.price.toLocaleString()} × ${item.quantity}</span>
              <button onclick="removeCartItem(${item.id})" style="background: none; border: none; color: #ef4444; cursor: pointer; font-size: 0.82rem; font-weight: 600;">মুছুন</button>
            </div>
          </div>
        </div>
      `;
    });

    container.innerHTML = html;
    if (subtotalElem) subtotalElem.textContent = `৳${data.subtotal.toLocaleString()}`;

    // Update global cart badge
    document.querySelectorAll('.cart-count-badge').forEach(badge => {
      badge.textContent = data.count;
    });

  } catch (err) {
    console.error('Failed to load cart', err);
  }
}

// Add to cart via AJAX
async function addToCart(productId, quantity = 1, variantId = null) {
  try {
    const formData = new FormData();
    formData.append('product_id', productId);
    formData.append('quantity', quantity);
    if (variantId) formData.append('variant_id', variantId);

    const res = await fetch('/api/cart/add', {
      method: 'POST',
      body: formData
    });

    const data = await res.json();
    if (data.success) {
      showToast(data.message || 'পণ্যটি সফলভাবে কার্টে যোগ হয়েছে!');
      document.querySelectorAll('.cart-count-badge').forEach(badge => {
        badge.textContent = data.count;
      });
      // Optionally open drawer
      const drawer = document.getElementById('cartDrawer');
      const overlay = document.getElementById('cartDrawerOverlay');
      if (drawer && overlay) {
        drawer.classList.add('active');
        overlay.classList.add('active');
        loadCartItems();
      }
    } else {
      showToast(data.message || 'পণ্যটি যোগ করা সম্ভব হয়নি।', 'error');
    }
  } catch (err) {
    console.error(err);
    showToast('নেটওয়ার্ক ত্রুটি। আবার চেষ্টা করুন।', 'error');
  }
}

// Remove from cart
async function removeCartItem(productId) {
  try {
    const formData = new FormData();
    formData.append('product_id', productId);

    const res = await fetch('/api/cart/remove', {
      method: 'POST',
      body: formData
    });

    const data = await res.json();
    if (data.success) {
      showToast('পণ্যটি কার্ট থেকে সরানো হয়েছে।');
      loadCartItems();
    }
  } catch (err) {
    console.error(err);
  }
}

// Search suggestions
function initSearchSuggestions() {
  const searchInput = document.querySelector('.search-input-wrap input');
  if (!searchInput) return;

  let timeout = null;
  const dropdown = document.createElement('div');
  dropdown.className = 'search-suggestions-dropdown';
  dropdown.style.cssText = `
    position: absolute;
    top: 100%;
    left: 0;
    right: 0;
    background: #ffffff;
    border: 1px solid var(--pd-border);
    border-radius: 10px;
    box-shadow: 0 10px 25px rgba(0,0,0,0.1);
    z-index: 1000;
    margin-top: 6px;
    overflow: hidden;
    display: none;
  `;
  searchInput.closest('.header-search').appendChild(dropdown);

  searchInput.addEventListener('input', function () {
    clearTimeout(timeout);
    const q = this.value.trim();
    if (q.length < 2) {
      dropdown.style.display = 'none';
      return;
    }

    timeout = setTimeout(async () => {
      try {
        const res = await fetch(`/api/search-suggestions?q=${encodeURIComponent(q)}`);
        const results = await res.json();

        if (results && results.length > 0) {
          dropdown.innerHTML = results.map(p => `
            <a href="/product/${p.slug || p.id}" style="display: flex; align-items: center; gap: 12px; padding: 10px 14px; border-bottom: 1px solid #f1f5f9; text-decoration: none; color: inherit;">
              <img src="${p.main_image || '/static/images/logo.png'}" style="width: 40px; height: 40px; object-fit: cover; border-radius: 4px;">
              <div>
                <div style="font-weight: 600; font-size: 0.92rem; color: #0d3826;">${p.name_bn}</div>
                <div style="font-size: 0.8rem; color: #64748b;">${p.unit || ''} — ৳${(p.discount_price || p.regular_price).toLocaleString()}</div>
              </div>
            </a>
          `).join('');
          dropdown.style.display = 'block';
        } else {
          dropdown.innerHTML = `<div style="padding: 12px; font-size: 0.88rem; color: #64748b; text-align: center;">কোনো পণ্য খুঁজে পাওয়া যায়নি।</div>`;
          dropdown.style.display = 'block';
        }
      } catch (e) {
        console.error(e);
      }
    }, 250);
  });

  document.addEventListener('click', function (e) {
    if (!searchInput.contains(e.target) && !dropdown.contains(e.target)) {
      dropdown.style.display = 'none';
    }
  });
}

// Checkout District & Dynamic Delivery Fee
function initCheckoutDistrictLogic() {
  const districtSelect = document.getElementById('checkoutDistrict');
  const deliveryFeeDisplay = document.getElementById('checkoutDeliveryFee');
  const totalDisplay = document.getElementById('checkoutGrandTotal');
  const subtotalHidden = document.getElementById('checkoutSubtotalVal');
  const discountHidden = document.getElementById('checkoutDiscountVal');
  const deliveryHidden = document.getElementById('deliveryFeeInput');

  if (!districtSelect || !deliveryFeeDisplay || !totalDisplay) return;

  districtSelect.addEventListener('change', function () {
    const selected = this.value;
    const isDhaka = selected.toLowerCase().includes('dhaka') || selected.includes('ঢাকা');
    const fee = isDhaka ? 70 : 130;

    const subtotal = parseFloat(subtotalHidden ? subtotalHidden.value : 0) || 0;
    const discount = parseFloat(discountHidden ? discountHidden.value : 0) || 0;

    // Free delivery check (e.g. >= 2000)
    let actualFee = fee;
    if (subtotal >= 2000) {
      actualFee = 0;
      deliveryFeeDisplay.innerHTML = `<span style="color: #10b981; font-weight: 700;">ফ্রি ডেলিভারি</span>`;
    } else {
      deliveryFeeDisplay.textContent = `৳${actualFee}`;
    }

    if (deliveryHidden) deliveryHidden.value = actualFee;
    const finalTotal = Math.max(0, subtotal - discount + actualFee);
    totalDisplay.textContent = `৳${finalTotal.toLocaleString()}`;
  });
}

// Payment method tab switcher on checkout
function initPaymentMethodSwitcher() {
  const cards = document.querySelectorAll('.payment-option-card');
  const inputs = document.querySelectorAll('input[name="payment_method"]');
  const bkashBox = document.getElementById('bkashPaymentDetails');
  const nagadBox = document.getElementById('nagadPaymentDetails');

  if (!cards.length) return;

  cards.forEach(card => {
    card.addEventListener('click', function () {
      cards.forEach(c => c.classList.remove('active'));
      this.classList.add('active');

      const radio = this.querySelector('input[type="radio"]');
      if (radio) radio.checked = true;

      const method = this.dataset.method;
      if (bkashBox) bkashBox.style.display = method === 'bKash' ? 'block' : 'none';
      if (nagadBox) nagadBox.style.display = method === 'Nagad' ? 'block' : 'none';
    });
  });
}

// Quantity controls
function initQuantityControls() {
  document.querySelectorAll('.qty-control-wrap').forEach(wrap => {
    const minus = wrap.querySelector('.qty-btn-minus');
    const plus = wrap.querySelector('.qty-btn-plus');
    const input = wrap.querySelector('.qty-input');

    if (minus && plus && input) {
      minus.addEventListener('click', () => {
        let val = parseInt(input.value) || 1;
        if (val > 1) input.value = val - 1;
      });
      plus.addEventListener('click', () => {
        let val = parseInt(input.value) || 1;
        let max = parseInt(input.max) || 99;
        if (val < max) input.value = val + 1;
      });
    }
  });
}

// Product detail gallery
function initProductGallery() {
  const mainImg = document.getElementById('productDetailMainImage');
  const thumbs = document.querySelectorAll('.gallery-thumb-item');

  if (!mainImg || !thumbs.length) return;

  thumbs.forEach(thumb => {
    thumb.addEventListener('click', function () {
      thumbs.forEach(t => t.style.borderColor = 'var(--pd-border)');
      this.style.borderColor = 'var(--pd-forest)';
      const targetSrc = this.dataset.imgSrc;
      if (targetSrc) mainImg.src = targetSrc;
    });
  });
}

// Wishlist
function initWishlist() {
  const wishlistButtons = document.querySelectorAll('.wishlist-toggle-btn');
  let wishlist = JSON.parse(localStorage.getItem('pd_wishlist') || '[]');

  function updateWishlistBadge() {
    document.querySelectorAll('.wishlist-count-badge').forEach(b => {
      b.textContent = wishlist.length;
    });
  }

  wishlistButtons.forEach(btn => {
    const pid = btn.dataset.productId;
    if (wishlist.includes(pid)) {
      btn.classList.add('active');
      btn.style.color = '#ef4444';
    }

    btn.addEventListener('click', function (e) {
      e.preventDefault();
      const id = this.dataset.productId;
      if (wishlist.includes(id)) {
        wishlist = wishlist.filter(x => x !== id);
        this.classList.remove('active');
        this.style.color = '';
        showToast('পণ্যটি পছন্দের তালিকা থেকে সরানো হয়েছে।');
      } else {
        wishlist.push(id);
        this.classList.add('active');
        this.style.color = '#ef4444';
        showToast('পণ্যটি পছন্দের তালিকায় যোগ করা হয়েছে! ❤️');
      }
      localStorage.setItem('pd_wishlist', JSON.stringify(wishlist));
      updateWishlistBadge();
    });
  });

  updateWishlistBadge();
}
