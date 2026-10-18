/**
 * Customer Login Page Logic — manages form toggling, validation, and auth submission.
 */

import './styles/index.css';
import { loginCustomer, registerCustomer, isCustomerLoggedIn } from './services/customer-auth.js';

// Redirect if already authenticated
if (isCustomerLoggedIn()) {
    const params = new URLSearchParams(window.location.search);
    const redirectUrl = params.get('redirect') || '/';
    window.location.href = redirectUrl;
}

// ── DOM References ────────────────────────────────────────────────────────
const tabLogin = document.getElementById('tab-login');
const tabRegister = document.getElementById('tab-register');
const loginForm = document.getElementById('login-form');
const registerForm = document.getElementById('register-form');
const authHeading = document.getElementById('auth-heading');
const authSubheading = document.getElementById('auth-subheading');

const authError = document.getElementById('auth-error');
const authErrorText = document.getElementById('auth-error-text');
const authSuccess = document.getElementById('auth-success');
const authSuccessText = document.getElementById('auth-success-text');

const loginEmail = document.getElementById('login-email');
const loginPassword = document.getElementById('login-password');
const loginSubmitBtn = document.getElementById('login-submit-btn');

const regName = document.getElementById('reg-name');
const regEmail = document.getElementById('reg-email');
const regPassword = document.getElementById('reg-password');
const regPhone = document.getElementById('reg-phone');
const regSubmitBtn = document.getElementById('reg-submit-btn');

const toggleLoginPass = document.getElementById('toggle-login-pass');
const toggleRegPass = document.getElementById('toggle-reg-pass');

// ── Tab Switching ─────────────────────────────────────────────────────────
tabLogin.addEventListener('click', () => switchTab('login'));
tabRegister.addEventListener('click', () => switchTab('register'));

function switchTab(mode) {
    hideAlerts();
    if (mode === 'register') {
        tabLogin.classList.remove('active');
        tabRegister.classList.add('active');
        loginForm.style.display = 'none';
        registerForm.style.display = 'flex';
        authHeading.textContent = 'Create Customer Account';
        authSubheading.textContent = 'Save your cart, track deliveries, and speed up checkout';
        regName.focus();
    } else {
        tabRegister.classList.remove('active');
        tabLogin.classList.add('active');
        registerForm.style.display = 'none';
        loginForm.style.display = 'flex';
        authHeading.textContent = 'Welcome Back';
        authSubheading.textContent = 'Sign in to access your saved shopping cart and order history';
        loginEmail.focus();
    }
}

// ── Password Visibility Toggles ───────────────────────────────────────────
if (toggleLoginPass) {
    toggleLoginPass.addEventListener('click', () => {
        const isPass = loginPassword.type === 'password';
        loginPassword.type = isPass ? 'text' : 'password';
        toggleLoginPass.textContent = isPass ? '🙈' : '👁️';
    });
}

if (toggleRegPass) {
    toggleRegPass.addEventListener('click', () => {
        const isPass = regPassword.type === 'password';
        regPassword.type = isPass ? 'text' : 'password';
        toggleRegPass.textContent = isPass ? '🙈' : '👁️';
    });
}

// ── Form Submissions ──────────────────────────────────────────────────────
loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    hideAlerts();

    const email = loginEmail.value.trim();
    const password = loginPassword.value;

    if (!email || !password) {
        showError('Please enter both email and password.');
        return;
    }

    setBtnLoading(loginSubmitBtn, true);

    const result = await loginCustomer(email, password);
    setBtnLoading(loginSubmitBtn, false);

    if (result.success) {
        showSuccess('Signed in successfully! Redirecting back to assistant...');
        setTimeout(() => {
            const params = new URLSearchParams(window.location.search);
            window.location.href = params.get('redirect') || '/';
        }, 900);
    } else {
        showError(result.error || 'Invalid credentials. Please try again.');
    }
});

registerForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    hideAlerts();

    const name = regName.value.trim();
    const email = regEmail.value.trim();
    const password = regPassword.value;
    const phone = regPhone.value.trim();

    if (!name || !email || !password) {
        showError('Please complete all required fields.');
        return;
    }

    if (password.length < 8) {
        showError('Password must be at least 8 characters long.');
        return;
    }

    setBtnLoading(regSubmitBtn, true);

    const result = await registerCustomer(email, password, name, phone);
    setBtnLoading(regSubmitBtn, false);

    if (result.success) {
        showSuccess('Account created! Your cart has been saved. Redirecting...');
        setTimeout(() => {
            const params = new URLSearchParams(window.location.search);
            window.location.href = params.get('redirect') || '/';
        }, 900);
    } else {
        showError(result.error || 'Registration failed. Please try a different email.');
    }
});

// ── UI Helpers ────────────────────────────────────────────────────────────
function showError(msg) {
    authErrorText.textContent = msg;
    authError.style.display = 'flex';
}

function showSuccess(msg) {
    authSuccessText.textContent = msg;
    authSuccess.style.display = 'flex';
}

function hideAlerts() {
    authError.style.display = 'none';
    authSuccess.style.display = 'none';
}

function setBtnLoading(btn, isLoading) {
    const textSpan = btn.querySelector('.btn-text');
    const loaderSpan = btn.querySelector('.btn-loader');
    btn.disabled = isLoading;
    if (textSpan) textSpan.style.display = isLoading ? 'none' : 'inline';
    if (loaderSpan) loaderSpan.style.display = isLoading ? 'inline-flex' : 'none';
}
