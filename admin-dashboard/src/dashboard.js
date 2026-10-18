import '../../merchant-dashboard/src/styles/dashboard.css';
import { requireAuth, logout as doLogout } from './auth.js';
import { api } from './api.js';

// Enforce authentication guards
if (!requireAuth()) throw new Error('Not authenticated');

let currentSection = 'users';
let usersPage = 1;
let usersRole = '';
let merchantsPage = 1;
let subscriptionsPage = 1;

const loadingEl = document.getElementById('dash-loading');
const pageTitleEl = document.getElementById('page-title');
const pageSubtitleEl = document.getElementById('page-subtitle');
const userRoleFilter = document.getElementById('user-role-filter');

const SECTION_META = {
  users: { title: 'Manage Clients', subtitle: 'Enable/disable customer and merchant accounts.' },
  merchants: { title: 'Merchants Directory', subtitle: 'Review and verify registered businesses.' },
  billing: { title: 'Platform Subscriptions', subtitle: 'Monitor active billing plans and fees.' },
};

function init() {
  setupNavigation();
  setupEventListeners();
  loadSection(currentSection);
}

function setupNavigation() {
  document.querySelectorAll('.dash-nav-item').forEach((item) => {
    item.addEventListener('click', (e) => {
      e.preventDefault();
      const section = item.dataset.section;
      navigateTo(section);
    });
  });
}

function navigateTo(section) {
  if (section === currentSection) return;
  currentSection = section;

  document.querySelectorAll('.dash-nav-item').forEach((item) => {
    item.classList.toggle('active', item.dataset.section === section);
  });

  document.querySelectorAll('.dash-section').forEach((el) => {
    el.style.display = 'none';
  });

  const target = document.getElementById(`section-${section}`);
  if (target) target.style.display = 'block';

  const meta = SECTION_META[section] || {};
  pageTitleEl.textContent = meta.title || section;
  pageSubtitleEl.textContent = meta.subtitle || '';

  loadSection(section);
}

function setupEventListeners() {
  document.getElementById('logout-btn').addEventListener('click', doLogout);

  if (userRoleFilter) {
    userRoleFilter.addEventListener('change', (e) => {
      usersRole = e.target.value;
      usersPage = 1;
      loadUsers();
    });
  }
}

async function loadSection(section) {
  switch (section) {
    case 'users': return loadUsers();
    case 'merchants': return loadMerchants();
    case 'billing': return loadSubscriptions();
  }
}

// ── Users Management ─────────────────────────────────
async function loadUsers() {
  showLoading();
  try {
    const data = await api.getUsers(usersPage, 10, usersRole || null);
    renderUsers(data);
  } catch (err) {
    console.error('Failed to load users:', err);
    document.getElementById('users-table-body').innerHTML = '<div class="empty-state">Failed to load system users.</div>';
  } finally {
    hideLoading();
  }
}

function renderUsers(data) {
  const container = document.getElementById('users-table-body');
  const items = data?.items || [];

  if (items.length === 0) {
    container.innerHTML = '<div class="empty-state">No users registered yet.</div>';
    return;
  }

  container.innerHTML = `
    <table class="dash-table">
      <thead>
        <tr>
          <th>User ID</th>
          <th>Name</th>
          <th>Email</th>
          <th>Role</th>
          <th>Status</th>
          <th>Created</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        ${items.map((u) => `
          <tr>
            <td style="font-family: monospace; font-size: 0.75rem;">${u.id}</td>
            <td style="font-weight: 600;">${u.full_name}</td>
            <td>${u.email}</td>
            <td><span class="status-badge ${u.role === 'admin' ? 'shipped' : 'pending'}">${u.role}</span></td>
            <td>
              <span class="status-badge ${u.is_active ? 'confirmed' : 'cancelled'}">
                ${u.is_active ? 'Active' : 'Suspended'}
              </span>
            </td>
            <td class="order-date">${new Date(u.created_at).toLocaleDateString()}</td>
            <td>
              <button class="pagination-btn toggle-active-btn" data-id="${u.id}">
                ${u.is_active ? '🚫 Suspend' : '✅ Activate'}
              </button>
            </td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;

  // Bind active toggles
  container.querySelectorAll('.toggle-active-btn').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      const id = e.currentTarget.dataset.id;
      showLoading();
      try {
        await api.toggleUserActive(id);
        showToast('User status updated successfully');
        loadUsers();
      } catch (err) {
        showToast('Error modifying status: ' + err.message, 'error');
        hideLoading();
      }
    });
  });

  renderPagination('users-pagination', data, usersPage, (p) => {
    usersPage = p;
    loadUsers();
  });
}

// ── Merchants Directory ──────────────────────────────
async function loadMerchants() {
  showLoading();
  try {
    const data = await api.getMerchants(merchantsPage, 10);
    renderMerchants(data);
  } catch (err) {
    console.error('Failed to load merchants:', err);
    document.getElementById('merchants-table-body').innerHTML = '<div class="empty-state">Failed to load merchants.</div>';
  } finally {
    hideLoading();
  }
}

function renderMerchants(data) {
  const container = document.getElementById('merchants-table-body');
  const items = data?.items || [];

  if (items.length === 0) {
    container.innerHTML = '<div class="empty-state">No merchants found.</div>';
    return;
  }

  container.innerHTML = `
    <table class="dash-table">
      <thead>
        <tr>
          <th>ID</th>
          <th>Business Name</th>
          <th>Type</th>
          <th>Email</th>
          <th>Verification</th>
          <th>Action</th>
        </tr>
      </thead>
      <tbody>
        ${items.map((m) => `
          <tr>
            <td style="font-family: monospace; font-size: 0.75rem;">${m.id}</td>
            <td style="font-weight: 600;">${m.business_name}</td>
            <td>${m.business_type}</td>
            <td>${m.email}</td>
            <td>
              <span class="status-badge ${m.verification_status === 'verified' ? 'confirmed' : 'pending'}">
                ${m.verification_status}
              </span>
            </td>
            <td>
              ${m.verification_status !== 'verified' ? `
                <button class="pagination-btn verify-merchant-btn" data-id="${m.id}">
                  🛡️ Verify Business
                </button>
              ` : '<span class="status-badge confirmed">Verified</span>'}
            </td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;

  container.querySelectorAll('.verify-merchant-btn').forEach((btn) => {
    btn.addEventListener('click', async (e) => {
      const id = e.currentTarget.dataset.id;
      showLoading();
      try {
        await api.verifyMerchant(id);
        showToast('Merchant business verified successfully');
        loadMerchants();
      } catch (err) {
        showToast('Verification failed: ' + err.message, 'error');
        hideLoading();
      }
    });
  });

  renderPagination('merchants-pagination', data, merchantsPage, (p) => {
    merchantsPage = p;
    loadMerchants();
  });
}

// ── Subscriptions & Billing ─────────────────────────
async function loadSubscriptions() {
  showLoading();
  try {
    const data = await api.getSubscriptions(subscriptionsPage, 10);
    renderSubscriptions(data);
  } catch (err) {
    console.error('Failed to load subscriptions:', err);
    document.getElementById('subscriptions-table-body').innerHTML = '<div class="empty-state">Failed to load platform subscription logs.</div>';
  } finally {
    hideLoading();
  }
}

function renderSubscriptions(data) {
  const container = document.getElementById('subscriptions-table-body');
  const items = data?.items || [];

  if (items.length === 0) {
    container.innerHTML = '<div class="empty-state">No subscription plan records found.</div>';
    return;
  }

  container.innerHTML = `
    <table class="dash-table">
      <thead>
        <tr>
          <th>Plan Name</th>
          <th>Client Email</th>
          <th>Price</th>
          <th>Billing Status</th>
          <th>End Date</th>
        </tr>
      </thead>
      <tbody>
        ${items.map((s) => `
          <tr>
            <td style="font-weight: 600; text-transform: uppercase;">${s.plan_name}</td>
            <td>${s.user_email}</td>
            <td style="font-weight: 700; color: var(--success);">$${s.price.toFixed(2)}</td>
            <td><span class="status-badge ${s.status === 'active' ? 'confirmed' : 'cancelled'}">${s.status}</span></td>
            <td class="order-date">${new Date(s.current_period_end).toLocaleDateString()}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;

  renderPagination('subscriptions-pagination', data, subscriptionsPage, (p) => {
    subscriptionsPage = p;
    loadSubscriptions();
  });
}

// ── UI Utilities ─────────────────────────────────────
function renderPagination(containerId, data, currentPage, onPageSelect) {
  const pagination = document.getElementById(containerId);
  if (!pagination) return;

  if (!data || data.total_pages <= 1) {
    pagination.innerHTML = '';
    return;
  }

  pagination.innerHTML = `
    <div class="pagination">
      <button class="pagination-btn" ${currentPage <= 1 ? 'disabled' : ''} id="${containerId}-prev">← Previous</button>
      <span class="pagination-info">Page ${data.page} of ${data.total_pages}</span>
      <button class="pagination-btn" ${currentPage >= data.total_pages ? 'disabled' : ''} id="${containerId}-next">Next →</button>
    </div>
  `;

  document.getElementById(`${containerId}-prev`)?.addEventListener('click', () => onPageSelect(currentPage - 1));
  document.getElementById(`${containerId}-next`)?.addEventListener('click', () => onPageSelect(currentPage + 1));
}

function showLoading() {
  loadingEl.style.display = 'flex';
}

function hideLoading() {
  loadingEl.style.display = 'none';
}

function showToast(message, type = 'success') {
  const toast = document.createElement('div');
  toast.className = `toast toast-${type}`;
  toast.textContent = message;
  document.body.appendChild(toast);
  requestAnimationFrame(() => toast.classList.add('visible'));
  setTimeout(() => {
    toast.classList.remove('visible');
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}

init();
