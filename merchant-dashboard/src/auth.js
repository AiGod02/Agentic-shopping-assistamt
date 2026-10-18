/**
 * Auth Module — JWT authentication management.
 *
 * Tokens are stored in sessionStorage (cleared on tab close)
 * for better XSS resistance compared to localStorage.
 */

const AUTH_KEYS = {
  ACCESS_TOKEN: 'mc_access_token',
  REFRESH_TOKEN: 'mc_refresh_token',
  USER_ID: 'mc_user_id',
  MERCHANT_ID: 'mc_merchant_id',
  ROLE: 'mc_role',
  BUSINESS_NAME: 'mc_business_name',
  EXPIRES_AT: 'mc_expires_at',
};

// ── Token Storage ────────────────────────────────────

export function saveAuth(loginResponse) {
  const expiresAt = Date.now() + loginResponse.expires_in * 1000;
  sessionStorage.setItem(AUTH_KEYS.ACCESS_TOKEN, loginResponse.access_token);
  sessionStorage.setItem(AUTH_KEYS.REFRESH_TOKEN, loginResponse.refresh_token);
  sessionStorage.setItem(AUTH_KEYS.USER_ID, loginResponse.user_id);
  sessionStorage.setItem(AUTH_KEYS.MERCHANT_ID, loginResponse.merchant_id || '');
  sessionStorage.setItem(AUTH_KEYS.ROLE, loginResponse.role);
  sessionStorage.setItem(AUTH_KEYS.BUSINESS_NAME, loginResponse.business_name || '');
  sessionStorage.setItem(AUTH_KEYS.EXPIRES_AT, expiresAt.toString());
}

export function getAccessToken() {
  return sessionStorage.getItem(AUTH_KEYS.ACCESS_TOKEN);
}

export function getRefreshToken() {
  return sessionStorage.getItem(AUTH_KEYS.REFRESH_TOKEN);
}

export function getMerchantId() {
  return sessionStorage.getItem(AUTH_KEYS.MERCHANT_ID);
}

export function getBusinessName() {
  return sessionStorage.getItem(AUTH_KEYS.BUSINESS_NAME);
}

export function getUserId() {
  return sessionStorage.getItem(AUTH_KEYS.USER_ID);
}

export function getRole() {
  return sessionStorage.getItem(AUTH_KEYS.ROLE);
}

export function clearAuth() {
  Object.values(AUTH_KEYS).forEach((key) => sessionStorage.removeItem(key));
}

// ── Auth Checks ──────────────────────────────────────

export function isAuthenticated() {
  const token = getAccessToken();
  const expiresAt = sessionStorage.getItem(AUTH_KEYS.EXPIRES_AT);
  if (!token || !expiresAt) return false;
  // Consider expired if within 60s of expiry
  return Date.now() < parseInt(expiresAt) - 60000;
}

export function isTokenExpiringSoon() {
  const expiresAt = sessionStorage.getItem(AUTH_KEYS.EXPIRES_AT);
  if (!expiresAt) return true;
  // Expiring within 5 minutes
  return Date.now() > parseInt(expiresAt) - 300000;
}

// ── Token Refresh ────────────────────────────────────

let refreshPromise = null;

export async function refreshAccessToken() {
  // Prevent concurrent refresh calls
  if (refreshPromise) return refreshPromise;

  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    logout();
    return null;
  }

  refreshPromise = (async () => {
    try {
      const res = await fetch('/api/v1/merchants/refresh', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ refresh_token: refreshToken }),
      });

      if (!res.ok) {
        logout();
        return null;
      }

      const data = await res.json();
      sessionStorage.setItem(AUTH_KEYS.ACCESS_TOKEN, data.access_token);
      const expiresAt = Date.now() + data.expires_in * 1000;
      sessionStorage.setItem(AUTH_KEYS.EXPIRES_AT, expiresAt.toString());
      return data.access_token;
    } catch {
      logout();
      return null;
    } finally {
      refreshPromise = null;
    }
  })();

  return refreshPromise;
}

// ── Login / Logout ───────────────────────────────────

export async function login(email, password) {
  const res = await fetch('/api/v1/merchants/login', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Login failed');
  }

  const data = await res.json();
  saveAuth(data);
  return data;
}

export async function registerMerchant(formData) {
  const res = await fetch('/api/v1/merchants/register', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(formData),
  });

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || 'Registration failed');
  }

  // Automatically log in after registration
  return login(formData.email, formData.password);
}

export async function logout() {
  const token = getAccessToken();
  if (token) {
    try {
      await fetch('/api/v1/merchants/logout', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
      });
    } catch {
      // Best-effort — clear locally regardless
    }
  }
  clearAuth();
  window.location.href = '/';
}

// ── Navigation Guard ─────────────────────────────────

export function requireAuth() {
  if (!isAuthenticated()) {
    window.location.href = '/';
    return false;
  }
  return true;
}

export function redirectIfAuthenticated() {
  if (isAuthenticated()) {
    window.location.href = '/dashboard.html';
    return true;
  }
  return false;
}
