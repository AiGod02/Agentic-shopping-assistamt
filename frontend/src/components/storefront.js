/**
 * Storefront Catalog Component — visual shop catalog.
 */
import { addToCart } from '../services/cart-api.js';
import { updateCartUI } from './cart.js';

export async function initStorefront() {
  const tabChat = document.getElementById('tab-chat');
  const tabCatalog = document.getElementById('tab-catalog');
  const chatContainer = document.getElementById('chat-container');
  const inputArea = document.querySelector('.input-area');
  const catalogContainer = document.getElementById('catalog-container');

  if (!tabChat || !tabCatalog) return;

  // Toggle view
  tabChat.addEventListener('click', () => {
    tabChat.classList.add('active');
    tabCatalog.classList.remove('active');
    chatContainer.style.display = 'block';
    if (inputArea) inputArea.style.display = 'block';
    catalogContainer.style.display = 'none';
  });

  tabCatalog.addEventListener('click', () => {
    tabCatalog.classList.add('active');
    tabChat.classList.remove('active');
    chatContainer.style.display = 'none';
    if (inputArea) inputArea.style.display = 'none';
    catalogContainer.style.display = 'block';
    loadCatalog();
  });
}

async function loadCatalog() {
  const grid = document.getElementById('catalog-grid');
  grid.innerHTML = '<div class="empty-state">Fetching catalog...</div>';

  try {
    const urlParams = new URLSearchParams(window.location.search);
    const merchantId = urlParams.get('merchant_id');
    let fetchUrl = '/api/merchant/listings';
    if (merchantId) {
      fetchUrl += `?merchant_id=${merchantId}`;
    }

    const res = await fetch(fetchUrl);
    if (!res.ok) throw new Error('Failed to fetch listings');
    const data = await res.json();
    const items = data.items || [];

    if (items.length === 0) {
      grid.innerHTML = '<div class="empty-state">No listings active in storefront.</div>';
      return;
    }

    grid.innerHTML = items.map((item) => `
      <div class="product-card" data-id="${item.id}">
        <div class="product-card-emoji">${getTypeEmoji(item.type)}</div>
        <div class="product-card-name" title="${item.title}">${item.title}</div>
        <div class="product-card-price">$${(Number(item.base_price) || 0).toFixed(2)}</div>
        <div class="product-card-rating">⭐ ${(Number(item.rating_avg) || 0).toFixed(1)} (${item.rating_count || 0} reviews)</div>
        <div class="product-card-actions">
          <button class="product-card-btn primary add-to-cart-btn" data-id="${item.id}">🛒 Add to Cart</button>
        </div>
      </div>
    `).join('');

    // Add to Cart click handlers
    grid.querySelectorAll('.add-to-cart-btn').forEach((btn) => {
      btn.addEventListener('click', async (e) => {
        const id = e.currentTarget.getAttribute('data-id');
        btn.disabled = true;
        btn.textContent = 'Adding...';

        try {
          const result = await addToCart({ listing_id: id, quantity: 1 });
          if (result.error) {
            alert(result.error);
          } else {
            updateCartUI();
            btn.textContent = 'Added! ✓';
            setTimeout(() => {
              btn.disabled = false;
              btn.textContent = '🛒 Add to Cart';
            }, 1500);
          }
        } catch (err) {
          alert('Error adding item: ' + err.message);
          btn.disabled = false;
          btn.textContent = '🛒 Add to Cart';
        }
      });
    });

  } catch (err) {
    grid.innerHTML = `<div class="empty-state">Error loading catalog: ${err.message}</div>`;
  }
}

function getTypeEmoji(type) {
  const map = {
    product: '📦', hotel: '🏨', rental: '🏠', service: '🧰',
    electronics: '💻', real_estate: '🏗️',
  };
  return map[type] || '🛍️';
}
