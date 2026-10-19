/**
 * Agent Orchestrator — clean API client for backend Agent Server (8001).
 * Eliminates duplicate mock tools; coordinates signed guest JWT and checkout gating.
 */

import { updateCartUI } from '../components/cart.js';

const AGENT_API = '/api/agent';
const MERCHANT_API = '/api/merchant';

/**
 * Check if a JWT token is missing or expired.
 */
function isTokenExpired(token) {
    if (!token) return true;
    try {
        const parts = token.split('.');
        if (parts.length !== 3) return true;
        const payload = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
        return !payload.exp || (payload.exp * 1000) <= (Date.now() + 30000); // 30s buffer
    } catch {
        return true;
    }
}

/**
 * Ensure a cryptographically signed guest JWT exists in localStorage.
 * If missing or expired, requests a new guest token.
 */
export async function ensureAuthToken() {
    let token = localStorage.getItem('acp_jwt_token');
    if (token && !isTokenExpired(token)) return token;

    localStorage.removeItem('acp_jwt_token');

    try {
        let resp = await fetch(`${AGENT_API}/agent/guest-token`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
        });
        if (!resp.ok) {
            resp = await fetch(`${MERCHANT_API}/merchants/guest-token`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
        }
        if (resp.ok) {
            const data = await resp.json();
            token = data.access_token;
            localStorage.setItem('acp_jwt_token', token);
            localStorage.setItem('acp_user_id', data.user_id);
            localStorage.setItem('acp_is_guest', 'true');
            console.log('[Agentic Commerce] Signed guest JWT initialized:', data.user_id);
            return token;
        }
    } catch (e) {
        console.error('[Agentic Commerce] Failed to obtain guest JWT from agent server, trying merchant server:', e);
        try {
            const resp = await fetch(`${MERCHANT_API}/merchants/guest-token`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
            });
            if (resp.ok) {
                const data = await resp.json();
                token = data.access_token;
                localStorage.setItem('acp_jwt_token', token);
                localStorage.setItem('acp_user_id', data.user_id);
                localStorage.setItem('acp_is_guest', 'true');
                return token;
            }
        } catch (e2) {
            console.error('[Agentic Commerce] Failed to obtain guest JWT:', e2);
        }
    }
    return null;
}

/**
 * Get or initialize session ID for multi-turn conversational context.
 */
export function getSessionId() {
    const SESSION_EXPIRY_MS = 60 * 60 * 1000; // 60 minutes TTL
    const lastActive = parseInt(localStorage.getItem('agent_session_time') || '0', 10);
    const now = Date.now();
    let sid = localStorage.getItem('agent_session_id');

    // Automatically rotate session if missing or inactive for over 1 hour
    if (!sid || (now - lastActive > SESSION_EXPIRY_MS)) {
        sid = (typeof crypto !== 'undefined' && crypto.randomUUID)
            ? crypto.randomUUID()
            : 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function (c) {
                  const r = (Math.random() * 16) | 0,
                      v = c === 'x' ? r : (r & 0x3) | 0x8;
                  return v.toString(16);
              });
        localStorage.setItem('agent_session_id', sid);
    }
    localStorage.setItem('agent_session_time', String(now));
    return sid;
}

/**
 * Reset conversation session so the user starts with a clean slate.
 */
export function resetSession() {
    localStorage.removeItem('agent_session_id');
    localStorage.removeItem('agent_session_time');
    return getSessionId();
}

/**
 * Log in as a registered user (e.g. at checkout).
 * Replaces guest JWT with verified customer JWT.
 */
export async function loginUser(email = 'customer@example.com', password = 'password') {
    try {
        const resp = await fetch(`${MERCHANT_API}/merchants/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password }),
        });
        if (resp.ok) {
            const data = await resp.json();
            localStorage.setItem('acp_jwt_token', data.access_token);
            localStorage.setItem('acp_user_id', data.user_id || '');
            localStorage.setItem('acp_is_guest', 'false');
            console.log('[Agentic Commerce] User authenticated successfully');
            await updateCartUI();
            return { success: true, data };
        } else {
            const err = await resp.json();
            return { success: false, error: err.detail || 'Login failed' };
        }
    } catch (e) {
        return { success: false, error: e.message };
    }
}

function mapListingToProduct(listing) {
    const rawPrice = listing.base_price ?? listing.price ?? 0;
    const price = typeof rawPrice === 'number' ? rawPrice : parseFloat(rawPrice) || 0;
    const rawRating = listing.rating_avg ?? listing.rating ?? 0;
    const rating = typeof rawRating === 'number' ? rawRating : parseFloat(rawRating) || 0;

    return {
        id: listing.id,
        name: listing.title || 'Product',
        description: listing.description || '',
        price: price,
        currency: listing.currency || 'USD',
        image: (listing.media && listing.media[0] && listing.media[0].url) || '📦',
        rating: rating,
        reviews_count: listing.rating_count || 0,
        in_stock: true,
    };
}

/**
 * Main message handler — calls the backend Agent Server with the signed guest JWT.
 */
export async function processMessage(userMessage) {
    const token = await ensureAuthToken();
    const sessionId = getSessionId();

    // Check for guest checkout attempt
    const isGuest = localStorage.getItem('acp_is_guest') === 'true';
    const isCheckoutQuery = /^(?:checkout|pay|place\s+order|buy\s+now|complete\s+order|proceed\s+to\s+checkout.*|checkout\s+.*)/i.test(userMessage.trim());

    if (isCheckoutQuery && isGuest) {
        return {
            text: `You have items ready in your cart! Since you are shopping as a guest, please sign in below to link your customer account and proceed with secure checkout.`,
            toolCalls: [{ tool: 'checkout', status: 'waiting', params: { auth: 'required' } }],
            requiresSignIn: true,
            type: 'checkout_auth_required',
        };
    }

    try {
        const response = await fetch(`${AGENT_API}/agent/chat`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`,
            },
            body: JSON.stringify({
                session_id: sessionId,
                message: userMessage,
                merchant_id: new URLSearchParams(window.location.search).get('merchant_id') || null,
            }),
        });

        if (!response.ok) {
            throw new Error(`Agent server responded with status: ${response.status}`);
        }

        const data = await response.json();

        // Synchronize authoritative session_id from server
        if (data.session_id) {
            localStorage.setItem('agent_session_id', data.session_id);
        }

        // Extract products from any search tool calls
        let products = [];
        const searchCall = (data.tool_calls || []).find((tc) => tc.tool === 'search_listings');
        if (searchCall && searchCall.result && searchCall.result.results) {
            products = searchCall.result.results.map(mapListingToProduct);
        }

        // Extract payment object from response or checkout tool call
        let payment = data.payment || null;
        if (!payment) {
            const checkoutCall = (data.tool_calls || []).find((tc) => tc.tool === 'checkout' && tc.success !== false);
            if (checkoutCall && checkoutCall.result && (checkoutCall.result.order_id || checkoutCall.result.payment_id)) {
                payment = checkoutCall.result;
            }
        }

        // Format tool calls for Scira-style ToolInvocation rendering
        const toolCalls = (data.tool_calls || []).map((tc) => ({
            tool: tc.tool,
            params: tc.args || tc.params || {},
            result: tc.result || {},
            status: tc.success !== false ? 'completed' : 'error',
        }));

        // Refresh cart if any cart tools executed
        const hasCartCall = (data.tool_calls || []).some((tc) =>
            ['add_to_cart', 'remove_from_cart', 'clear_cart', 'checkout'].includes(tc.tool)
        );
        if (hasCartCall) {
            await updateCartUI();
        }

        return {
            text: data.response,
            toolCalls: toolCalls,
            products: products,
            payment: payment,
            type: payment ? 'checkout' : hasCartCall ? 'cart_update' : searchCall ? 'search' : 'chat',
        };
    } catch (err) {
        console.error('[Agent Orchestrator] Agent request failed:', err);
        return {
            text: `I had trouble communicating with the commerce server. Please ensure services are active. (Error: ${err.message})`,
            toolCalls: [{ tool: 'agent_chat', status: 'error', params: { error: err.message } }],
            type: 'error',
        };
    }
}

// Auto-initialize guest token on load
ensureAuthToken();
