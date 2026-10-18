import { ensureAuthToken, getSessionId } from '../mcp/agent-orchestrator.js';

const MERCHANT_API = '/api/merchant';

let cachedCart = {
    id: '',
    status: 'empty',
    items: [],
    subtotal: 0,
    tax: 0,
    total: 0,
    item_count: 0,
};

async function getAuthHeaders() {
    let token = localStorage.getItem('acp_jwt_token');
    if (!token) {
        token = await ensureAuthToken();
    }
    const headers = { 'Content-Type': 'application/json' };
    if (token) {
        headers['Authorization'] = `Bearer ${token}`;
    }
    const sid = getSessionId();
    if (sid) {
        headers['X-Session-ID'] = sid;
    }
    return headers;
}

function normalizeCart(data) {
    if (!data) return cachedCart;
    const subtotal = Number(data.subtotal) || 0;
    const tax = subtotal * 0.08;
    const total = subtotal + tax;

    const items = (data.items || []).map((item) => ({
        id: item.id,
        listing_id: item.listing_id,
        name: item.listing_title || item.title || 'Product',
        variant_name: item.variant_name || '',
        price: Number(item.unit_price) || 0,
        quantity: Number(item.quantity) || 1,
        image: item.image || item.emoji || '🛍️',
    }));

    cachedCart = {
        id: data.id || '',
        status: data.status || 'active',
        items,
        subtotal,
        tax,
        total,
        item_count: items.reduce((sum, it) => sum + it.quantity, 0),
    };
    return cachedCart;
}

export function getCartState() {
    return cachedCart;
}

export async function fetchCart() {
    try {
        const headers = await getAuthHeaders();
        const resp = await fetch(`${MERCHANT_API}/cart`, {
            method: 'GET',
            headers,
        });
        if (resp.ok) {
            const data = await resp.json();
            return normalizeCart(data);
        }
    } catch (err) {
        console.error('[CartAPI] Failed to fetch cart:', err);
    }
    return cachedCart;
}

export async function addToCart(listingIdOrObj, quantity = 1, variantId = null) {
    try {
        let listingId = listingIdOrObj;
        let qty = quantity;
        let vId = variantId;
        if (typeof listingIdOrObj === 'object' && listingIdOrObj !== null) {
            listingId = listingIdOrObj.listing_id || listingIdOrObj.id;
            qty = listingIdOrObj.quantity || 1;
            vId = listingIdOrObj.variant_id || null;
        }
        const payload = {
            listing_id: listingId,
            quantity: Number(qty) || 1,
        };
        if (vId) payload.variant_id = vId;

        const headers = await getAuthHeaders();
        const resp = await fetch(`${MERCHANT_API}/cart/items`, {
            method: 'POST',
            headers,
            body: JSON.stringify(payload),
        });
        if (resp.ok) {
            const data = await resp.json();
            return normalizeCart(data);
        } else {
            const err = await resp.json();
            console.error('[CartAPI] Add to cart failed:', err);
            return { error: err.detail || 'Add to cart failed' };
        }
    } catch (err) {
        console.error('[CartAPI] Error adding to cart:', err);
        return { error: err.message };
    }
    return cachedCart;
}

export async function removeFromCart(itemId) {
    try {
        const headers = await getAuthHeaders();
        const resp = await fetch(`${MERCHANT_API}/cart/items/${itemId}`, {
            method: 'DELETE',
            headers,
        });
        if (resp.ok) {
            const data = await resp.json();
            return normalizeCart(data);
        }
    } catch (err) {
        console.error('[CartAPI] Error removing cart item:', err);
    }
    return cachedCart;
}
