/**
 * Login Page — handles authentication form and redirect.
 */
import './styles/dashboard.css';
import { login, redirectIfAuthenticated } from './auth.js';

// ── Redirect if already authenticated ────────────────
redirectIfAuthenticated();

// ── DOM References ───────────────────────────────────
const form = document.getElementById('login-form');
const emailInput = document.getElementById('login-email');
const passwordInput = document.getElementById('login-password');
const errorDiv = document.getElementById('login-error');
const errorText = document.getElementById('login-error-text');
const btnText = document.getElementById('login-btn-text');
const btnLoading = document.getElementById('login-btn-loading');
const loginBtn = document.getElementById('login-btn');
const togglePassword = document.getElementById('toggle-password');
const loginCard = document.getElementById('login-card');

// ── Animate In ───────────────────────────────────────
requestAnimationFrame(() => {
  loginCard.classList.add('visible');
});

// ── Toggle Password Visibility ───────────────────────
togglePassword.addEventListener('click', () => {
  const isPassword = passwordInput.type === 'password';
  passwordInput.type = isPassword ? 'text' : 'password';
  togglePassword.textContent = isPassword ? '🙈' : '👁';
});

// ── Form Submit ──────────────────────────────────────
form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = emailInput.value.trim();
  const password = passwordInput.value;

  if (!email || !password) {
    showError('Please enter both email and password');
    return;
  }

  setLoading(true);
  hideError();

  try {
    await login(email, password);
    // Redirect on success
    window.location.href = '/dashboard.html';
  } catch (err) {
    showError(err.message || 'Login failed. Please check your credentials.');
    // Shake animation
    loginCard.classList.add('shake');
    setTimeout(() => loginCard.classList.remove('shake'), 500);
  } finally {
    setLoading(false);
  }
});

// ── Helpers ──────────────────────────────────────────
function showError(message) {
  errorText.textContent = message;
  errorDiv.style.display = 'flex';
}

function hideError() {
  errorDiv.style.display = 'none';
}

function setLoading(isLoading) {
  loginBtn.disabled = isLoading;
  btnText.style.display = isLoading ? 'none' : 'inline';
  btnLoading.style.display = isLoading ? 'flex' : 'none';
}

// ── Clear errors on input ────────────────────────────
emailInput.addEventListener('input', hideError);
passwordInput.addEventListener('input', hideError);
