/**
 * Admin API Client — fetches customer lists, active subscriptions, and allows user toggles.
 */

import { getAccessToken, isTokenExpiringSoon, refreshAccessToken, logout } from './auth.js';

class AdminApiClient {
  constructor(baseUrl = '/api/v1') {
    this.baseUrl = baseUrl;
  }

  async _getHeaders() {
    let token = getAccessToken();
    if (isTokenExpiringSoon() && token) {
      const newToken = await refreshAccessToken();
      if (newToken) token = newToken;
    }
    return {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    };
  }

  async _request(method, path, body = null, queryParams = null) {
    const headers = await this._getHeaders();
    let url = `${this.baseUrl}${path}`;

    if (queryParams) {
      const params = new URLSearchParams();
      Object.entries(queryParams).forEach(([k, v]) => {
        if (v !== null && v !== undefined) params.append(k, v);
      });
      const qs = params.toString();
      if (qs) url += `?${qs}`;
    }

    const options = { method, headers };
    if (body) options.body = JSON.stringify(body);

    const res = await fetch(url, options);

    if (res.status === 401) {
      const newToken = await refreshAccessToken();
      if (newToken) {
        headers.Authorization = `Bearer ${newToken}`;
        const retryRes = await fetch(url, { ...options, headers });
        if (retryRes.status === 401) {
          logout();
          throw new Error('Session expired');
        }
        return retryRes.json();
      }
      logout();
      throw new Error('Session expired');
    }

    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Request failed: ${res.status}`);
    }

    if (res.status === 204) return null;
    return res.json();
  }

  // Users management
  getUsers(page = 1, pageSize = 20, role = null) {
    return this._request('GET', '/admin/users', null, { page, page_size: pageSize, role });
  }

  toggleUserActive(userId) {
    return this._request('POST', `/admin/users/${userId}/toggle-active`);
  }

  // Merchants management
  getMerchants(page = 1, pageSize = 20) {
    return this._request('GET', '/admin/merchants', null, { page, page_size: pageSize });
  }

  verifyMerchant(merchantId) {
    return this._request('POST', `/merchants/${merchantId}/verify`);
  }

  // Subscriptions tracking
  getSubscriptions(page = 1, pageSize = 20) {
    return this._request('GET', '/admin/subscriptions', null, { page, page_size: pageSize });
  }
}

export const api = new AdminApiClient();
