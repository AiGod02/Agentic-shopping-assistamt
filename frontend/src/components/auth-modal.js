/**
 * Auth Modal Component — Elegant Customer Sign In & Registration Modal.
 *
 * Can be opened anywhere (Top bar, Save Cart button, Checkout button, or Chat prompt).
 */

import { loginCustomer, registerCustomer, isCustomerLoggedIn, getCurrentCustomer, logoutCustomer } from '../services/customer-auth.js';
import { updateCartUI } from './cart.js';

let modalOverlay = null;

export function initAuthUI(onAuthSuccess = null) {
    createAuthModalDOM(onAuthSuccess);
    updateTopBarUserUI();

    window.addEventListener('acp_auth_changed', () => {
        updateTopBarUserUI();
        updateCartUI();
    });
}

function updateTopBarUserUI() {
    const accountBtn = document.getElementById('account-btn');
    if (!accountBtn) return;

    if (isCustomerLoggedIn()) {
        const customer = getCurrentCustomer();
        accountBtn.innerHTML = `
            <span class="user-avatar-pill">👤</span>
            <span class="user-name-text">${escapeHtml(customer?.name || 'My Account')}</span>
            <span class="sign-out-badge" title="Sign Out">Sign Out</span>
        `;
        accountBtn.className = 'top-bar-btn account-btn logged-in';
    } else {
        accountBtn.innerHTML = `
            <span>👤</span>
            <span>Sign In</span>
        `;
        accountBtn.className = 'top-bar-btn account-btn guest';
    }
}

export function openAuthModal(mode = 'login', customTitle = null, onSuccessCallback = null) {
    if (!modalOverlay) {
        createAuthModalDOM(onSuccessCallback);
    }
    const overlay = document.getElementById('auth-modal-overlay');
    if (!overlay) return;

    overlay.style.display = 'flex';
    requestAnimationFrame(() => overlay.classList.add('visible'));

    switchAuthTab(mode);

    if (customTitle) {
        const titleEl = document.getElementById('auth-modal-title');
        if (titleEl) titleEl.textContent = customTitle;
    }

    const emailInput = mode === 'login' ? document.getElementById('customer-login-email') : document.getElementById('customer-reg-email');
    if (emailInput) setTimeout(() => emailInput.focus(), 100);
}

export function closeAuthModal() {
    const overlay = document.getElementById('auth-modal-overlay');
    if (!overlay) return;
    overlay.classList.remove('visible');
    setTimeout(() => {
        overlay.style.display = 'none';
        hideAuthError();
    }, 200);
}

function switchAuthTab(tab) {
    const loginTab = document.getElementById('auth-tab-login');
    const regTab = document.getElementById('auth-tab-register');
    const loginForm = document.getElementById('customer-login-form');
    const regForm = document.getElementById('customer-register-form');
    const titleEl = document.getElementById('auth-modal-title');
    const subtitleEl = document.getElementById('auth-modal-subtitle');

    hideAuthError();

    if (tab === 'register') {
        if (loginTab) loginTab.classList.remove('active');
        if (regTab) regTab.classList.add('active');
        if (loginForm) loginForm.style.display = 'none';
        if (regForm) regForm.style.display = 'flex';
        if (titleEl) titleEl.textContent = 'Create Customer Account';
        if (subtitleEl) subtitleEl.textContent = 'Save your cart, track orders, and enjoy faster checkout';
    } else {
        if (regTab) regTab.classList.remove('active');
        if (loginTab) loginTab.classList.add('active');
        if (regForm) regForm.style.display = 'none';
        if (loginForm) loginForm.style.display = 'flex';
        if (titleEl) titleEl.textContent = 'Welcome Back';
        if (subtitleEl) subtitleEl.textContent = 'Sign in to access your saved cart and orders';
    }
}

function showAuthError(msg) {
    const errEl = document.getElementById('auth-modal-error');
    if (errEl) {
        errEl.textContent = msg;
        errEl.style.display = 'block';
    }
}

function hideAuthError() {
    const errEl = document.getElementById('auth-modal-error');
    if (errEl) errEl.style.display = 'none';
}

function createAuthModalDOM(globalOnSuccess) {
    if (document.getElementById('auth-modal-overlay')) return;

    modalOverlay = document.createElement('div');
    modalOverlay.id = 'auth-modal-overlay';
    modalOverlay.className = 'auth-modal-overlay';
    modalOverlay.style.display = 'none';

    modalOverlay.innerHTML = `
        <div class="auth-modal-card">
            <button class="auth-modal-close" id="auth-modal-close-btn" title="Close">✕</button>
            <div class="auth-modal-header">
                <div class="auth-brand-icon">🛍️</div>
                <h3 id="auth-modal-title">Customer Sign In</h3>
                <p id="auth-modal-subtitle">Sign in to save your cart and proceed to checkout</p>
            </div>

            <div class="auth-tabs">
                <button type="button" class="auth-tab active" id="auth-tab-login">Sign In</button>
                <button type="button" class="auth-tab" id="auth-tab-register">New Account</button>
            </div>

            <div class="auth-error-banner" id="auth-modal-error" style="display: none;"></div>

            <!-- Login Form -->
            <form id="customer-login-form" class="auth-form" style="display: flex;">
                <div class="auth-field">
                    <label for="customer-login-email">Email Address</label>
                    <input type="email" id="customer-login-email" placeholder="customer@example.com" required autocomplete="email" />
                </div>
                <div class="auth-field">
                    <label for="customer-login-password">Password</label>
                    <input type="password" id="customer-login-password" placeholder="••••••••" required autocomplete="current-password" />
                </div>
                <button type="submit" class="auth-submit-btn" id="customer-login-submit">
                    <span>Sign In</span>
                </button>
            </form>

            <!-- Register Form -->
            <form id="customer-register-form" class="auth-form" style="display: none;">
                <div class="auth-field">
                    <label for="customer-reg-name">Full Name</label>
                    <input type="text" id="customer-reg-name" placeholder="Sarah Connor" required autocomplete="name" />
                </div>
                <div class="auth-field">
                    <label for="customer-reg-email">Email Address</label>
                    <input type="email" id="customer-reg-email" placeholder="sarah@example.com" required autocomplete="email" />
                </div>
                <div class="auth-field">
                    <label for="customer-reg-password">Password (min 8 characters)</label>
                    <input type="password" id="customer-reg-password" placeholder="Create a secure password" minlength="8" required autocomplete="new-password" />
                </div>
                <div class="auth-field">
                    <label for="customer-reg-phone">Phone Number (optional)</label>
                    <input type="tel" id="customer-reg-phone" placeholder="+1 (555) 000-0000" autocomplete="tel" />
                </div>
                <button type="submit" class="auth-submit-btn" id="customer-reg-submit">
                    <span>Create Account & Save Cart</span>
                </button>
            </form>

            <div class="auth-modal-footer">
                <span>🔒 Secure 256-bit encrypted checkout</span>
            </div>
        </div>
    `;

    document.body.appendChild(modalOverlay);

    // Event listeners
    modalOverlay.querySelector('#auth-modal-close-btn').addEventListener('click', closeAuthModal);
    modalOverlay.addEventListener('click', (e) => {
        if (e.target === modalOverlay) closeAuthModal();
    });

    modalOverlay.querySelector('#auth-tab-login').addEventListener('click', () => switchAuthTab('login'));
    modalOverlay.querySelector('#auth-tab-register').addEventListener('click', () => switchAuthTab('register'));

    // Handle Login Submit
    modalOverlay.querySelector('#customer-login-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const email = document.getElementById('customer-login-email').value.trim();
        const pass = document.getElementById('customer-login-password').value;
        const btn = document.getElementById('customer-login-submit');

        btn.disabled = true;
        btn.innerHTML = '<span>Signing in...</span>';
        hideAuthError();

        const res = await loginCustomer(email, pass);
        btn.disabled = false;
        btn.innerHTML = '<span>Sign In</span>';

        if (res.success) {
            closeAuthModal();
            if (globalOnSuccess) globalOnSuccess(res.user);
        } else {
            showAuthError(res.error);
        }
    });

    // Handle Register Submit
    modalOverlay.querySelector('#customer-register-form').addEventListener('submit', async (e) => {
        e.preventDefault();
        const name = document.getElementById('customer-reg-name').value.trim();
        const email = document.getElementById('customer-reg-email').value.trim();
        const pass = document.getElementById('customer-reg-password').value;
        const phone = document.getElementById('customer-reg-phone').value.trim();
        const btn = document.getElementById('customer-reg-submit');

        btn.disabled = true;
        btn.innerHTML = '<span>Creating account...</span>';
        hideAuthError();

        const res = await registerCustomer(email, pass, name, phone);
        btn.disabled = false;
        btn.innerHTML = '<span>Create Account & Save Cart</span>';

        if (res.success) {
            closeAuthModal();
            if (globalOnSuccess) globalOnSuccess(res.user);
        } else {
            showAuthError(res.error);
        }
    });
}

function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/[&<>"']/g, (m) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[m]);
}
