import '../../merchant-dashboard/src/styles/dashboard.css';
import { login, redirectIfAuthenticated } from './auth.js';

// Redirect if already authenticated
redirectIfAuthenticated();

const loginCard = document.getElementById('login-card');
requestAnimationFrame(() => {
  loginCard.classList.add('visible');
});

const form = document.getElementById('login-form');
const emailInput = document.getElementById('login-email');
const passwordInput = document.getElementById('login-password');
const errorDiv = document.getElementById('login-error');
const errorText = document.getElementById('login-error-text');
const loginBtn = document.getElementById('login-btn');
const btnText = document.getElementById('login-btn-text');
const btnLoading = document.getElementById('login-btn-loading');

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = emailInput.value.trim();
  const password = passwordInput.value;

  loginBtn.disabled = true;
  btnText.style.display = 'none';
  btnLoading.style.display = 'flex';
  errorDiv.style.display = 'none';

  try {
    await login(email, password);
    window.location.href = '/dashboard.html';
  } catch (err) {
    errorText.textContent = err.message || 'Authentication failed';
    errorDiv.style.display = 'flex';
  } finally {
    loginBtn.disabled = false;
    btnText.style.display = 'inline';
    btnLoading.style.display = 'none';
  }
});
