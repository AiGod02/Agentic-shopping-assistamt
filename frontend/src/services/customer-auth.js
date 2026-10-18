/**
 * Customer Auth Service — manages customer sign-in, registration, and guest cart claiming.
 */

import { ensureAuthToken } from '../mcp/agent-orchestrator.js';
import { claimGuestCart, fetchCart } from './cart-api.js';

const MERCHANT_API = '/api/merchant';

export function isCustomerLoggedIn() {
    const isGuest = localStorage.getItem('acp_is_guest');
    const token = localStorage.getItem('acp_jwt_token');
    return token && isGuest === 'false';
}

export function getCurrentCustomer() {
    if (!isCustomerLoggedIn()) return null;
    return {
        id: localStorage.getItem('acp_user_id') || '',
        name: localStorage.getItem('acp_user_name') || 'Customer',
        email: localStorage.getItem('acp_user_email') || '',
    };
}

export async function loginCustomer(email, password) {
    const oldGuestUserId = localStorage.getItem('acp_user_id');

    try {
        const resp = await fetch(`${MERCHANT_API}/merchants/login`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password }),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            return { success: false, error: err.detail || 'Invalid email or password' };
        }

        const data = await resp.json();
        localStorage.setItem('acp_jwt_token', data.access_token);
        localStorage.setItem('acp_user_id', data.user_id);
        localStorage.setItem('acp_user_name', data.full_name || data.business_name || email.split('@')[0]);
        localStorage.setItem('acp_user_email', email);
        localStorage.setItem('acp_is_guest', 'false');

        // Claim and merge any items added during guest session
        if (oldGuestUserId && oldGuestUserId !== data.user_id) {
            await claimGuestCart(oldGuestUserId);
        } else {
            await fetchCart();
        }

        window.dispatchEvent(new CustomEvent('acp_auth_changed', { detail: { loggedIn: true, user: data } }));
        return { success: true, user: data };
    } catch (e) {
        return { success: false, error: e.message || 'Connection error' };
    }
}

export async function registerCustomer(email, password, fullName, phone = null) {
    const oldGuestUserId = localStorage.getItem('acp_user_id');

    try {
        const resp = await fetch(`${MERCHANT_API}/merchants/customer/register`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                email,
                password,
                full_name: fullName,
                phone: phone || null,
            }),
        });

        if (!resp.ok) {
            const err = await resp.json().catch(() => ({}));
            return { success: false, error: err.detail || 'Registration failed' };
        }

        const data = await resp.json();
        localStorage.setItem('acp_jwt_token', data.access_token);
        localStorage.setItem('acp_user_id', data.user_id);
        localStorage.setItem('acp_user_name', data.full_name || fullName);
        localStorage.setItem('acp_user_email', email);
        localStorage.setItem('acp_is_guest', 'false');

        // Claim and merge any items added during guest session
        if (oldGuestUserId && oldGuestUserId !== data.user_id) {
            await claimGuestCart(oldGuestUserId);
        } else {
            await fetchCart();
        }

        window.dispatchEvent(new CustomEvent('acp_auth_changed', { detail: { loggedIn: true, user: data } }));
        return { success: true, user: data };
    } catch (e) {
        return { success: false, error: e.message || 'Connection error' };
    }
}

export async function logoutCustomer() {
    localStorage.removeItem('acp_jwt_token');
    localStorage.removeItem('acp_user_id');
    localStorage.removeItem('acp_user_name');
    localStorage.removeItem('acp_user_email');
    localStorage.setItem('acp_is_guest', 'true');

    // Re-initialize guest token for seamless shopping continuation
    await ensureAuthToken();
    await fetchCart();

    window.dispatchEvent(new CustomEvent('acp_auth_changed', { detail: { loggedIn: false } }));
}
