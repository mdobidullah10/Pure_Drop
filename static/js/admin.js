/**
 * PURE DROP — Super Admin JS
 */

document.addEventListener('DOMContentLoaded', function () {
  initConfirmDialogs();
  initImagePreviews();
});

function initConfirmDialogs() {
  document.querySelectorAll('[data-confirm]').forEach(el => {
    el.addEventListener('click', function (e) {
      const msg = this.dataset.confirm || 'আপনি কি নিশ্চিত?';
      if (!confirm(msg)) {
        e.preventDefault();
      }
    });
  });
}

function initImagePreviews() {
  const urlInputs = document.querySelectorAll('.image-url-preview-input');
  urlInputs.forEach(input => {
    const targetImgId = input.dataset.previewTarget;
    const targetImg = document.getElementById(targetImgId);
    if (targetImg) {
      input.addEventListener('input', function () {
        if (this.value.trim().length > 5) {
          targetImg.src = this.value.trim();
        }
      });
    }
  });
}

// Quick inline stock adjustment
async function adjustStock(productId, delta) {
  try {
    const res = await fetch('/admin/api/stock-adjust', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ product_id: productId, delta: delta })
    });
    const data = await res.json();
    if (data.success) {
      const el = document.getElementById(`stockVal_${productId}`);
      if (el) el.textContent = data.new_stock;
    } else {
      alert(data.message || 'স্টক আপডেট করা যায়নি।');
    }
  } catch (err) {
    console.error(err);
  }
}
