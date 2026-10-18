/**
 * Cart Component — renders and updates the cart sidebar.
 */
import { getCartState, fetchCart, removeFromCart } from '../services/cart-api.js';

/**
 * Refresh the entire cart sidebar UI from current cart state.
 */
export async function updateCartUI() {
    const cart = await fetchCart();
    const cartItemsEl = document.getElementById('cart-items');
    const cartCountEl = document.getElementById('cart-count');
    const cartFooterEl = document.getElementById('cart-footer');
    const cartSubtotalEl = document.getElementById('cart-subtotal');
    const cartTaxEl = document.getElementById('cart-tax');
    const cartTotalEl = document.getElementById('cart-total');

    if (!cartItemsEl || !cartCountEl) return;

    cartCountEl.textContent = cart.item_count;

    if (cart.items.length === 0) {
        cartItemsEl.innerHTML = `
      <div class="cart-empty">
        <span class="cart-empty-icon">🛒</span>
        <p>Your cart is empty</p>
        <p style="font-size: 0.8rem; color: var(--text-muted);">Ask the assistant to find something!</p>
      </div>
    `;
        if (cartFooterEl) cartFooterEl.style.display = 'none';
        return;
    }

    if (cartFooterEl) cartFooterEl.style.display = 'block';
    if (cartSubtotalEl) cartSubtotalEl.textContent = `$${cart.subtotal.toFixed(2)}`;
    if (cartTaxEl) cartTaxEl.textContent = `$${cart.tax.toFixed(2)}`;
    if (cartTotalEl) cartTotalEl.textContent = `$${cart.total.toFixed(2)}`;

    cartItemsEl.innerHTML = cart.items
        .map(
            (item) => `
      <div class="cart-item" data-item-id="${item.id}">
        <div class="cart-item-emoji">${item.image || '📦'}</div>
        <div class="cart-item-info">
          <div class="cart-item-name">${item.name}</div>
          ${item.variant_name ? `<div class="cart-item-variant">${item.variant_name}</div>` : ''}
          <div class="cart-item-price">$${(item.price * item.quantity).toFixed(2)} ${item.quantity > 1 ? `(×${item.quantity})` : ''}</div>
        </div>
        <button class="cart-item-remove" data-remove-id="${item.id}" title="Remove item">✕</button>
      </div>
    `
        )
        .join('');

    // Attach remove handlers
    cartItemsEl.querySelectorAll('.cart-item-remove').forEach((btn) => {
        btn.addEventListener('click', async (e) => {
            const itemId = e.currentTarget.getAttribute('data-remove-id');
            await removeFromCart(itemId);
            await updateCartUI();
        });
    });
}

export function renderCart() {
    updateCartUI();
}
