/**
 * API Client — authenticated HTTP requests with automatic token refresh.
 *
 * All requests include the Authorization header.
 * On 401, attempts token refresh before redirecting to login.
 */

import { getAccessToken, isTokenExpiringSoon, refreshAccessToken, logout } from './auth.js';

class ApiClient {
  constructor(baseUrl = '/api/v1') {
    this.baseUrl = baseUrl;
  }

  async _getHeaders() {
    let token = getAccessToken();

    // Proactively refresh if expiring soon
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
      // Try refresh once
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

    // Handle 204 No Content
    if (res.status === 204) return null;
    return res.json();
  }

  // ── Merchant ──────────────────────────────────────

  getMerchantProfile() {
    return this._request('GET', '/merchants/me');
  }

  updateMerchantProfile(data) {
    return this._request('PUT', '/merchants/me', data);
  }

  // ── Analytics ─────────────────────────────────────

  getDashboardSummary(period = 30) {
    return this._request('GET', '/analytics/dashboard', null, { period });
  }

  getSalesData(days = 30, granularity = 'day') {
    return this._request('GET', '/analytics/sales', null, { days, granularity });
  }

  getTrafficData(days = 30) {
    return this._request('GET', '/analytics/traffic', null, { days });
  }

  getTopProducts(limit = 10, days = 30) {
    return this._request('GET', '/analytics/top-products', null, { limit, days });
  }

  // ── Orders ────────────────────────────────────────

  getOrders(page = 1, pageSize = 20, status = null) {
    return this._request('GET', '/orders', null, {
      page,
      page_size: pageSize,
      ...(status ? { status } : {}),
    });
  }

  getOrder(orderId) {
    return this._request('GET', `/orders/${orderId}`);
  }

  cancelOrder(orderId) {
    return this._request('POST', `/orders/${orderId}/cancel`);
  }

  // ── Listings ──────────────────────────────────────

  getListings(page = 1, pageSize = 20) {
    return this._request('GET', '/listings', null, { page, page_size: pageSize });
  }

  createListing(data) {
    return this._request('POST', '/listings', data);
  }
}

export const api = new ApiClient();
