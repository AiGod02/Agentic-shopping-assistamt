/**
 * Admin Auth Module — manages admin session storage and guards.
 */

const AUTH_KEYS = {
  ACCESS_TOKEN: 'ad_access_token',
  REFRESH_TOKEN: 'ad_refresh_token',
  USER_ID: 'ad_user_id',
  ROLE: 'ad_role',
  USER_NAME: 'ad_user_name',
  EXPIRES_AT: 'ad_expires_at',
};

export function saveAuth(loginResponse) {
  if (loginResponse.role !== 'admin') {
    throw new Error('Access denied — Admin role required');
  }
  const expiresAt = Date.now() + loginResponse.expires_in * 1000;
  sessionStorage.setItem(AUTH_KEYS.ACCESS_TOKEN, loginResponse.access_token);
  sessionStorage.setItem(AUTH_KEYS.REFRESH_TOKEN, loginResponse.refresh_token);
  sessionStorage.setItem(AUTH_KEYS.USER_ID, loginResponse.user_id);
  sessionStorage.setItem(AUTH_KEYS.ROLE, loginResponse.role);
  sessionStorage.setItem(AUTH_KEYS.USER_NAME, 'System Administrator');
  sessionStorage.setItem(AUTH_KEYS.EXPIRES_AT, expiresAt.toString());
}

export function getAccessToken() {
  return sessionStorage.getItem(AUTH_KEYS.ACCESS_TOKEN);
}

export function getRefreshToken() {
  return sessionStorage.getItem(AUTH_KEYS.REFRESH_TOKEN);
}

export function getRole() {
  return sessionStorage.getItem(AUTH_KEYS.ROLE);
}

export function getAdminName() {
  return sessionStorage.getItem(AUTH_KEYS.USER_NAME);
}

export function clearAuth() {
  Object.values(AUTH_KEYS).forEach((key) => sessionStorage.removeItem(key));
}

export function isAuthenticated() {
  const token = getAccessToken();
  const expiresAt = sessionStorage.getItem(AUTH_KEYS.EXPIRES_AT);
  if (!token || !expiresAt) return false;
  return Date.now() < parseInt(expiresAt) - 60000;
}

export function isTokenExpiringSoon() {
  const expiresAt = sessionStorage.getItem(AUTH_KEYS.EXPIRES_AT);
  if (!expiresAt) return true;
  return Date.now() > parseInt(expiresAt) - 300000;
}

export async function refreshAccessToken() {
  const refreshToken = getRefreshToken();
  if (!refreshToken) {
    logout();
    return null;
  }
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
  }
}

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
  if (data.role !== 'admin') {
    throw new Error('Access denied — Admin credentials required');
  }
  saveAuth(data);
  return data;
}

export function logout() {
  clearAuth();
  window.location.href = '/';
}

export function requireAuth() {
  if (!isAuthenticated() || getRole() !== 'admin') {
    window.location.href = '/';
    return false;
  }
  return true;
}

export function redirectIfAuthenticated() {
  if (isAuthenticated() && getRole() === 'admin') {
    window.location.href = '/dashboard.html';
    return true;
  }
  return false;
}
