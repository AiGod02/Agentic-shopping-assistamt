/**
 * Login & Registration Page — handles merchant sign-in, onboarding registration, and redirects.
 */
import './styles/dashboard.css';
import { login, registerMerchant, redirectIfAuthenticated } from './auth.js';

// ── Redirect if already authenticated ────────────────
redirectIfAuthenticated();

// ── DOM References ───────────────────────────────────
const loginForm = document.getElementById('login-form');
const registerForm = document.getElementById('register-form');
const tabLogin = document.getElementById('tab-login');
const tabRegister = document.getElementById('tab-register');
const registerLink = document.getElementById('register-link');
const authSwitchPrompt = document.getElementById('auth-switch-prompt');

const emailInput = document.getElementById('login-email');
const passwordInput = document.getElementById('login-password');
const loginErrorDiv = document.getElementById('login-error');
const loginErrorText = document.getElementById('login-error-text');
const btnText = document.getElementById('login-btn-text');
const btnLoading = document.getElementById('login-btn-loading');
const loginBtn = document.getElementById('login-btn');
const togglePassword = document.getElementById('toggle-password');
const loginCard = document.getElementById('login-card');

// Registration inputs
const regBizName = document.getElementById('reg-biz-name');
const regBizType = document.getElementById('reg-biz-type');
const regFullName = document.getElementById('reg-full-name');
const regEmail = document.getElementById('reg-email');
const regPassword = document.getElementById('reg-password');
const regTaxId = document.getElementById('reg-tax-id');
const regErrorDiv = document.getElementById('reg-error');
const regErrorText = document.getElementById('reg-error-text');
const regBtn = document.getElementById('reg-btn');
const regBtnText = document.getElementById('reg-btn-text');
const regBtnLoading = document.getElementById('reg-btn-loading');

// ── Animate In ───────────────────────────────────────
requestAnimationFrame(() => {
  loginCard.classList.add('visible');
});

// ── Toggle Tabs ──────────────────────────────────────
function setAuthMode(mode) {
  hideErrors();
  if (mode === 'register') {
    tabLogin.style.background = 'transparent';
    tabLogin.style.color = '#a0a0cc';
    tabRegister.style.background = 'var(--accent-gradient, #6366f1)';
    tabRegister.style.color = '#fff';

    loginForm.style.display = 'none';
    registerForm.style.display = 'flex';
    authSwitchPrompt.innerHTML = 'Already have an account? <a href="#" id="signin-link" style="color: #818cf8; font-weight: 600;">Sign in here</a>';
    document.getElementById('signin-link')?.addEventListener('click', (e) => {
      e.preventDefault();
      setAuthMode('login');
    });
    regBizName?.focus();
  } else {
    tabRegister.style.background = 'transparent';
    tabRegister.style.color = '#a0a0cc';
    tabLogin.style.background = 'var(--accent-gradient, #6366f1)';
    tabLogin.style.color = '#fff';

    registerForm.style.display = 'none';
    loginForm.style.display = 'block';
    authSwitchPrompt.innerHTML = 'Don\'t have an account? <a href="#" id="register-link" style="color: #818cf8; font-weight: 600;">Register your business</a>';
    document.getElementById('register-link')?.addEventListener('click', (e) => {
      e.preventDefault();
      setAuthMode('register');
    });
    emailInput?.focus();
  }
}

tabLogin?.addEventListener('click', () => setAuthMode('login'));
tabRegister?.addEventListener('click', () => setAuthMode('register'));
registerLink?.addEventListener('click', (e) => {
  e.preventDefault();
  setAuthMode('register');
});

// ── Toggle Password Visibility ───────────────────────
togglePassword?.addEventListener('click', () => {
  const isPassword = passwordInput.type === 'password';
  passwordInput.type = isPassword ? 'text' : 'password';
  togglePassword.textContent = isPassword ? '🙈' : '👁';
});

// ── Login Form Submit ────────────────────────────────
loginForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = emailInput.value.trim();
  const password = passwordInput.value;

  if (!email || !password) {
    showLoginError('Please enter both email and password');
    return;
  }

  setLoginLoading(true);
  hideErrors();

  try {
    await login(email, password);
    window.location.href = '/dashboard.html';
  } catch (err) {
    showLoginError(err.message || 'Login failed. Please check your credentials.');
    shakeCard();
  } finally {
    setLoginLoading(false);
  }
});

// ── Register Form Submit ─────────────────────────────
registerForm?.addEventListener('submit', async (e) => {
  e.preventDefault();
  const bizName = regBizName.value.trim();
  const bizType = regBizType.value;
  const fullName = regFullName.value.trim();
  const email = regEmail.value.trim();
  const password = regPassword.value;
  const taxId = regTaxId.value.trim();

  if (!bizName || !fullName || !email || !password) {
    showRegError('Please fill in all required fields.');
    return;
  }

  if (password.length < 8) {
    showRegError('Password must be at least 8 characters long.');
    return;
  }

  setRegLoading(true);
  hideErrors();

  try {
    await registerMerchant({
      business_name: bizName,
      business_type: bizType,
      full_name: fullName,
      email: email,
      password: password,
      tax_id: taxId || null,
    });
    window.location.href = '/dashboard.html';
  } catch (err) {
    showRegError(err.message || 'Registration failed. Email might already be taken.');
    shakeCard();
  } finally {
    setRegLoading(false);
  }
});

// ── Helpers ──────────────────────────────────────────
function showLoginError(msg) {
  loginErrorText.textContent = msg;
  loginErrorDiv.style.display = 'flex';
}

function showRegError(msg) {
  regErrorText.textContent = msg;
  regErrorDiv.style.display = 'flex';
}

function hideErrors() {
  if (loginErrorDiv) loginErrorDiv.style.display = 'none';
  if (regErrorDiv) regErrorDiv.style.display = 'none';
}

function shakeCard() {
  loginCard.classList.add('shake');
  setTimeout(() => loginCard.classList.remove('shake'), 500);
}

function setLoginLoading(isLoading) {
  loginBtn.disabled = isLoading;
  btnText.style.display = isLoading ? 'none' : 'inline';
  btnLoading.style.display = isLoading ? 'flex' : 'none';
}

function setRegLoading(isLoading) {
  regBtn.disabled = isLoading;
  regBtnText.style.display = isLoading ? 'none' : 'inline';
  regBtnLoading.style.display = isLoading ? 'flex' : 'none';
}

emailInput?.addEventListener('input', hideErrors);
passwordInput?.addEventListener('input', hideErrors);
regEmail?.addEventListener('input', hideErrors);
