/**
 * Dashboard — main application logic.
 * Protected page: requires authentication.
 */
import './styles/dashboard.css';
import { requireAuth, getBusinessName, logout as doLogout, getUserId } from './auth.js';
import { api } from './api.js';

// ── Auth Guard ───────────────────────────────────────
if (!requireAuth()) throw new Error('Not authenticated');

// ── State ────────────────────────────────────────────
let currentSection = 'overview';
let currentPeriod = 30;
let salesGranularity = 'day';
let ordersPage = 1;
let ordersStatus = '';

// Catalog state
let cachedListings = [];
let selectedBulkFile = null;
let catalogSearchTerm = '';
let catalogTypeFilter = '';
let catalogSortBy = 'newest';

// ── DOM References ───────────────────────────────────
const loading = document.getElementById('dash-loading');
const sidebar = document.getElementById('dash-sidebar');
const mobileToggle = document.getElementById('mobile-toggle');
const logoutBtn = document.getElementById('logout-btn');
const periodSelect = document.getElementById('period-select');
const businessNameEl = document.getElementById('sidebar-business-name');
const userNameEl = document.getElementById('user-name');
const userAvatarEl = document.getElementById('user-avatar');
const pageTitleEl = document.getElementById('page-title');
const pageSubtitleEl = document.getElementById('page-subtitle');

// ── Initialize ───────────────────────────────────────
async function init() {
  setupNavigation();
  setupEventListeners();

  const name = getBusinessName() || 'Merchant';
  businessNameEl.textContent = name;
  userNameEl.textContent = name;
  userAvatarEl.textContent = name.charAt(0).toUpperCase();

  await loadOverview();
}

// ── Navigation ───────────────────────────────────────
const SECTION_META = {
  overview: { title: 'Overview', subtitle: "Welcome back! Here's your store performance." },
  orders: { title: 'Orders', subtitle: 'Track and manage all incoming orders.' },
  analytics: { title: 'Analytics', subtitle: 'Deep dive into your sales and traffic data.' },
  products: { title: 'Products', subtitle: 'Manage your product catalog.' },
  settings: { title: 'Settings', subtitle: 'Update your business profile.' },
};

function setupNavigation() {
  document.querySelectorAll('.dash-nav-item').forEach((item) => {
    item.addEventListener('click', (e) => {
      e.preventDefault();
      const section = item.dataset.section;
      navigateTo(section);
    });
  });

  const viewAllOrders = document.getElementById('view-all-orders');
  if (viewAllOrders) {
    viewAllOrders.addEventListener('click', (e) => {
      e.preventDefault();
      navigateTo('orders');
    });
  }
}

function navigateTo(section) {
  if (section === currentSection) return;
  currentSection = section;

  // Update nav
  document.querySelectorAll('.dash-nav-item').forEach((item) => {
    item.classList.toggle('active', item.dataset.section === section);
  });

  // Update sections
  document.querySelectorAll('.dash-section').forEach((el) => {
    el.style.display = 'none';
  });
  const target = document.getElementById(`section-${section}`);
  if (target) target.style.display = 'block';

  // Update header
  const meta = SECTION_META[section] || {};
  pageTitleEl.textContent = meta.title || section;
  pageSubtitleEl.textContent = meta.subtitle || '';

  // Close mobile sidebar
  sidebar.classList.remove('open');

  // Load section data
  loadSection(section);
}

async function loadSection(section) {
  switch (section) {
    case 'overview': return loadOverview();
    case 'orders': return loadOrders();
    case 'analytics': return loadAnalytics();
    case 'products': return loadProducts();
    case 'settings': return loadSettings();
  }
}

// ── Event Listeners ──────────────────────────────────
function setupEventListeners() {
  logoutBtn.addEventListener('click', doLogout);

  mobileToggle.addEventListener('click', () => {
    sidebar.classList.toggle('open');
  });

  periodSelect.addEventListener('change', (e) => {
    currentPeriod = parseInt(e.target.value);
    loadSection(currentSection);
  });

  // Sales chart granularity
  document.querySelectorAll('.chart-granularity-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.chart-granularity-btn').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      salesGranularity = btn.dataset.granularity;
      loadSalesChart();
    });
  });

  // Order status filter
  const statusFilter = document.getElementById('order-status-filter');
  if (statusFilter) {
    statusFilter.addEventListener('change', (e) => {
      ordersStatus = e.target.value;
      ordersPage = 1;
      loadOrders();
    });
  }

  // Settings form
  const settingsForm = document.getElementById('settings-form');
  if (settingsForm) {
    settingsForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const data = {
          business_name: document.getElementById('settings-business-name').value,
          business_type: document.getElementById('settings-business-type').value,
          tax_id: document.getElementById('settings-tax-id').value || null,
          payout_account: {
            stripe_account_id: document.getElementById('settings-stripe-account').value || null,
            razorpay_account_id: document.getElementById('settings-razorpay-account').value || null,
          }
        };
        await api.updateMerchantProfile(data);
        businessNameEl.textContent = data.business_name;
        userNameEl.textContent = data.business_name;
        showToast('Settings saved successfully!');
      } catch (err) {
        showToast('Failed to save settings: ' + err.message, 'error');
      }
    });
  }

  // Toggle Add Product Form
  const toggleAddProdBtn = document.getElementById('toggle-add-product-btn');
  const cancelAddProdBtn = document.getElementById('cancel-add-product-btn');
  const addProdCard = document.getElementById('add-product-card');

  if (toggleAddProdBtn && addProdCard) {
    toggleAddProdBtn.addEventListener('click', () => {
      const isHidden = addProdCard.style.display === 'none';
      addProdCard.style.display = isHidden ? 'block' : 'none';
    });
  }

  if (cancelAddProdBtn && addProdCard) {
    cancelAddProdBtn.addEventListener('click', () => {
      addProdCard.style.display = 'none';
      document.getElementById('add-product-form')?.reset();
    });
  }

  // Submit Product Form
  const addProdForm = document.getElementById('add-product-form');
  if (addProdForm) {
    addProdForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      try {
        const tagsInput = document.getElementById('prod-tags').value;
        const tags = tagsInput ? tagsInput.split(',').map(t => t.trim()).filter(Boolean) : [];
        
        const data = {
          title: document.getElementById('prod-title').value,
          type: document.getElementById('prod-type').value,
          base_price: parseFloat(document.getElementById('prod-price').value),
          description: document.getElementById('prod-desc').value,
          tags: tags,
          currency: 'USD',
          variants: [],
          metadata: {},
          media: [],
        };
        
        await api.createListing(data);
        showToast('Product catalog listing created!');
        addProdCard.style.display = 'none';
        addProdForm.reset();
        loadProducts(); // Reload product list grid
      } catch (err) {
        showToast('Failed to create listing: ' + err.message, 'error');
      }
    });
  }

  // ── Bulk Upload Catalog Handlers ──
  const openBulkUploadBtn = document.getElementById('open-bulk-upload-btn');
  const closeBulkUploadX = document.getElementById('close-bulk-upload-x');
  const cancelBulkUploadBtn = document.getElementById('cancel-bulk-upload-btn');
  const bulkUploadCard = document.getElementById('bulk-upload-card');
  const bulkFileInput = document.getElementById('bulk-file-input');
  const bulkDropzone = document.getElementById('bulk-dropzone');
  const submitBulkUploadBtn = document.getElementById('submit-bulk-upload-btn');
  const bulkSelectedFile = document.getElementById('bulk-selected-file');
  const bulkSelectedName = document.getElementById('bulk-selected-name');
  const bulkSelectedSize = document.getElementById('bulk-selected-size');
  const bulkUploadResult = document.getElementById('bulk-upload-result');

  function resetBulkUploadUI() {
    selectedBulkFile = null;
    if (bulkFileInput) bulkFileInput.value = '';
    if (bulkUploadCard) bulkUploadCard.style.display = 'none';
    if (bulkSelectedFile) bulkSelectedFile.style.display = 'none';
    if (submitBulkUploadBtn) {
      submitBulkUploadBtn.disabled = true;
      submitBulkUploadBtn.style.opacity = '0.5';
      submitBulkUploadBtn.style.cursor = 'not-allowed';
      submitBulkUploadBtn.textContent = 'Upload & Import Catalog';
    }
    if (bulkUploadResult) bulkUploadResult.style.display = 'none';
  }

  if (openBulkUploadBtn && bulkUploadCard) {
    openBulkUploadBtn.addEventListener('click', () => {
      const isHidden = bulkUploadCard.style.display === 'none';
      bulkUploadCard.style.display = isHidden ? 'block' : 'none';
      if (!isHidden) resetBulkUploadUI();
    });
  }

  if (closeBulkUploadX) closeBulkUploadX.addEventListener('click', resetBulkUploadUI);
  if (cancelBulkUploadBtn) cancelBulkUploadBtn.addEventListener('click', resetBulkUploadUI);

  function handleBulkFileSelected(file) {
    if (!file) return;
    const name = file.name.toLowerCase();
    if (!name.endsWith('.csv') && !name.endsWith('.json')) {
      showToast('Please select a valid .csv or .json catalog file', 'error');
      return;
    }
    selectedBulkFile = file;
    if (bulkSelectedName) bulkSelectedName.textContent = file.name;
    if (bulkSelectedSize) bulkSelectedSize.textContent = `(${(file.size / 1024).toFixed(1)} KB)`;
    if (bulkSelectedFile) bulkSelectedFile.style.display = 'inline-flex';
    if (submitBulkUploadBtn) {
      submitBulkUploadBtn.disabled = false;
      submitBulkUploadBtn.style.opacity = '1';
      submitBulkUploadBtn.style.cursor = 'pointer';
    }
  }

  if (bulkDropzone && bulkFileInput) {
    bulkDropzone.addEventListener('click', (e) => {
      if (e.target !== bulkFileInput) bulkFileInput.click();
    });
    bulkFileInput.addEventListener('change', (e) => {
      if (e.target.files && e.target.files[0]) {
        handleBulkFileSelected(e.target.files[0]);
      }
    });

    bulkDropzone.addEventListener('dragover', (e) => {
      e.preventDefault();
      bulkDropzone.classList.add('dragover');
    });
    bulkDropzone.addEventListener('dragleave', () => {
      bulkDropzone.classList.remove('dragover');
    });
    bulkDropzone.addEventListener('drop', (e) => {
      e.preventDefault();
      bulkDropzone.classList.remove('dragover');
      if (e.dataTransfer?.files?.length) {
        handleBulkFileSelected(e.dataTransfer.files[0]);
      }
    });
  }

  // Sample templates downloads
  const sampleCsvBtn = document.getElementById('download-sample-csv-btn');
  if (sampleCsvBtn) {
    sampleCsvBtn.addEventListener('click', () => {
      const csvContent = [
        'title,type,base_price,currency,description,tags',
        '"Aura Wireless Noise Cancelling Headphones",electronics,199.99,USD,"Premium over-ear audio with 40h battery life and ambient mode","wireless,headphones,audio,anc"',
        '"Ergonomic Mechanical Keyboard",electronics,89.50,USD,"Custom RGB mechanical keyboard with tactile switches","keyboard,ergonomic,office,tech"',
        '"Organic Bamboo Sheet Set (Queen)",product,59.99,USD,"Silky smooth breathable 100% bamboo viscose sheets","bedding,organic,home,sheets"',
        '"Oceanfront Deluxe Suite",hotel,240.00,USD,"Panoramic sea view suite with king bed, jacuzzi, and breakfast","hotel,resort,luxury,beach"',
        '"Downtown High-Rise Studio",rental,1400.00,USD,"Modern furnished loft with floor-to-ceiling city views","rental,apartment,housing"',
        '"Full-Stack System Architecture Audit",service,150.00,USD,"1-hour direct system design and scalability evaluation","consulting,service,tech"'
      ].join('\n');
      downloadFile(csvContent, 'sample_catalog.csv', 'text/csv;charset=utf-8;');
      showToast('Sample CSV template downloaded!');
    });
  }

  const sampleJsonBtn = document.getElementById('download-sample-json-btn');
  if (sampleJsonBtn) {
    sampleJsonBtn.addEventListener('click', () => {
      const jsonContent = JSON.stringify([
        {
          title: "Aura Wireless Noise Cancelling Headphones",
          type: "electronics",
          base_price: 199.99,
          currency: "USD",
          description: "Premium over-ear audio with 40h battery life and ambient mode",
          tags: ["wireless", "headphones", "audio", "anc"]
        },
        {
          title: "Organic Bamboo Sheet Set (Queen)",
          type: "product",
          base_price: 59.99,
          currency: "USD",
          description: "Silky smooth breathable 100% bamboo viscose sheets",
          tags: ["bedding", "organic", "home", "sheets"]
        },
        {
          title: "Oceanfront Deluxe Suite",
          type: "hotel",
          base_price: 240.00,
          currency: "USD",
          description: "Panoramic sea view suite with king bed, jacuzzi, and breakfast",
          tags: ["hotel", "resort", "luxury", "beach"]
        }
      ], null, 2);
      downloadFile(jsonContent, 'sample_catalog.json', 'application/json;charset=utf-8;');
      showToast('Sample JSON template downloaded!');
    });
  }

  // Bulk Upload Submit
  if (submitBulkUploadBtn) {
    submitBulkUploadBtn.addEventListener('click', async () => {
      if (!selectedBulkFile) return;
      try {
        submitBulkUploadBtn.disabled = true;
        submitBulkUploadBtn.textContent = 'Uploading & Importing...';
        const res = await api.bulkUploadCatalog(selectedBulkFile);

        if (bulkUploadResult) {
          bulkUploadResult.style.display = 'block';
          bulkUploadResult.style.background = res.failed_count > 0 ? 'rgba(251, 191, 36, 0.1)' : 'rgba(52, 211, 153, 0.1)';
          bulkUploadResult.style.border = res.failed_count > 0 ? '1px solid rgba(251, 191, 36, 0.3)' : '1px solid rgba(52, 211, 153, 0.3)';
          bulkUploadResult.style.color = res.failed_count > 0 ? '#fde68a' : '#a7f3d0';
          
          let errText = '';
          if (res.errors && res.errors.length) {
            errText = `<br><span style="font-size: 0.8rem; opacity: 0.85;">Errors: ${res.errors.map(e => `Row ${e.row}: ${e.error}`).join(', ')}</span>`;
          }
          bulkUploadResult.innerHTML = `<strong>Catalog Import Completed!</strong><br>Imported: ${res.imported_count} listings | Failed: ${res.failed_count}${errText}`;
        }

        showToast(`Imported ${res.imported_count} catalog items successfully!`);
        submitBulkUploadBtn.textContent = 'Upload & Import Catalog';
        await loadProducts();
      } catch (err) {
        if (bulkUploadResult) {
          bulkUploadResult.style.display = 'block';
          bulkUploadResult.style.background = 'rgba(248, 113, 113, 0.15)';
          bulkUploadResult.style.border = '1px solid rgba(248, 113, 113, 0.3)';
          bulkUploadResult.style.color = '#fca5a5';
          bulkUploadResult.textContent = `Upload failed: ${err.message}`;
        }
        showToast('Bulk upload failed: ' + err.message, 'error');
        submitBulkUploadBtn.disabled = false;
        submitBulkUploadBtn.textContent = 'Upload & Import Catalog';
      }
    });
  }

  // Catalog Toolbar: Search, Filter, Sort, Refresh
  const catalogSearchInput = document.getElementById('catalog-search-input');
  if (catalogSearchInput) {
    catalogSearchInput.addEventListener('input', (e) => {
      catalogSearchTerm = e.target.value.toLowerCase().trim();
      renderFilteredProducts();
    });
  }

  const catalogTypeFilterSelect = document.getElementById('catalog-type-filter');
  if (catalogTypeFilterSelect) {
    catalogTypeFilterSelect.addEventListener('change', (e) => {
      catalogTypeFilter = e.target.value;
      renderFilteredProducts();
    });
  }

  const catalogSortSelect = document.getElementById('catalog-sort-select');
  if (catalogSortSelect) {
    catalogSortSelect.addEventListener('change', (e) => {
      catalogSortBy = e.target.value;
      renderFilteredProducts();
    });
  }

  const catalogRefreshBtn = document.getElementById('catalog-refresh-btn');
  if (catalogRefreshBtn) {
    catalogRefreshBtn.addEventListener('click', () => {
      loadProducts();
      showToast('Catalog refreshed');
    });
  }
}

// ── Overview Section ─────────────────────────────────
async function loadOverview() {
  showLoading();
  try {
    const [summary, sales, traffic, topProducts, orders] = await Promise.all([
      api.getDashboardSummary(currentPeriod),
      api.getSalesData(currentPeriod, salesGranularity),
      api.getTrafficData(currentPeriod),
      api.getTopProducts(5, currentPeriod),
      api.getOrders(1, 5),
    ]);

    renderOnboarding(summary);
    renderKPICards(summary);
    renderSalesChart(sales);
    renderTrafficChart(traffic);
    renderRecentOrders(orders);
    renderTopProducts(topProducts);

    showSection('overview');
  } catch (err) {
    console.error('Failed to load overview:', err);
    renderEmptyState('section-overview', 'Failed to load dashboard data. Please try again.');
    showSection('overview');
  }
}

// ── Onboarding ───────────────────────────────────────
function renderOnboarding(summary) {
  const card = document.getElementById('onboarding-card');
  const steps = [
    { id: 'profile', label: 'Complete business profile', icon: '🏪', done: true },
    { id: 'listings', label: 'Add your first product', icon: '📦', done: summary.active_listings > 0 },
    { id: 'orders', label: 'Receive your first order', icon: '🛒', done: summary.orders.count > 0 },
    { id: 'analytics', label: 'View your analytics', icon: '📊', done: true },
  ];

  const completed = steps.filter((s) => s.done).length;
  const progressFill = document.getElementById('onboarding-progress-fill');
  const progressText = document.getElementById('onboarding-progress-text');
  progressFill.style.width = `${(completed / steps.length) * 100}%`;
  progressText.textContent = `${completed}/${steps.length} complete`;

  if (completed >= steps.length) {
    card.style.display = 'none';
    return;
  }

  card.style.display = 'block';
  const stepsContainer = document.getElementById('onboarding-steps');
  stepsContainer.innerHTML = steps.map((step) => `
    <div class="onboarding-step ${step.done ? 'done' : ''}">
      <div class="onboarding-step-check">${step.done ? '✅' : '⬜'}</div>
      <span class="onboarding-step-icon">${step.icon}</span>
      <span class="onboarding-step-label">${step.label}</span>
    </div>
  `).join('');
}

// ── KPI Cards ────────────────────────────────────────
function renderKPICards(summary) {
  const grid = document.getElementById('kpi-grid');
  const cards = [
    {
      title: 'Total Revenue',
      value: formatCurrency(summary.revenue.total),
      change: summary.revenue.change_pct,
      icon: '💰',
      color: 'emerald',
    },
    {
      title: 'Orders',
      value: summary.orders.count.toLocaleString(),
      change: summary.orders.change_pct,
      icon: '📦',
      color: 'blue',
    },
    {
      title: 'Active Listings',
      value: summary.active_listings.toLocaleString(),
      change: null,
      icon: '🛍️',
      color: 'purple',
    },
    {
      title: 'Page Views',
      value: summary.traffic.page_views.toLocaleString(),
      change: summary.traffic.change_pct,
      icon: '👁️',
      color: 'amber',
    },
  ];

  grid.innerHTML = cards.map((card) => `
    <div class="kpi-card kpi-${card.color}">
      <div class="kpi-header">
        <span class="kpi-icon">${card.icon}</span>
        <span class="kpi-title">${card.title}</span>
      </div>
      <div class="kpi-value">${card.value}</div>
      ${card.change !== null ? `
        <div class="kpi-change ${card.change >= 0 ? 'positive' : 'negative'}">
          <span>${card.change >= 0 ? '↑' : '↓'}</span>
          <span>${Math.abs(card.change)}%</span>
          <span class="kpi-change-period">vs prev ${currentPeriod}d</span>
        </div>
      ` : '<div class="kpi-change neutral">—</div>'}
    </div>
  `).join('');
}

// ── Charts ───────────────────────────────────────────

function renderSalesChart(salesData) {
  const canvas = document.getElementById('sales-chart');
  drawBarChart(canvas, salesData.data, 'revenue', {
    color: '#6366f1',
    gradientStart: 'rgba(99, 102, 241, 0.3)',
    gradientEnd: 'rgba(99, 102, 241, 0.02)',
    label: 'Revenue',
    formatValue: formatCurrency,
  });
}

async function loadSalesChart() {
  try {
    const sales = await api.getSalesData(currentPeriod, salesGranularity);
    renderSalesChart(sales);
  } catch (err) {
    console.error('Failed to load sales chart:', err);
  }
}

function renderTrafficChart(trafficData) {
  const canvas = document.getElementById('traffic-chart');
  drawBarChart(canvas, trafficData.data, 'views', {
    color: '#a78bfa',
    gradientStart: 'rgba(167, 139, 250, 0.3)',
    gradientEnd: 'rgba(167, 139, 250, 0.02)',
    label: 'Page Views',
    formatValue: (v) => v.toLocaleString(),
  });
}

function drawBarChart(canvas, data, valueKey, options) {
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  const w = rect.width || 600;
  const h = rect.height || 280;

  canvas.width = w * dpr;
  canvas.height = h * dpr;
  canvas.style.width = w + 'px';
  canvas.style.height = h + 'px';
  ctx.scale(dpr, dpr);
  ctx.clearRect(0, 0, w, h);

  if (!data || data.length === 0) {
    ctx.fillStyle = '#6b6b99';
    ctx.font = '14px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('No data available for this period', w / 2, h / 2);
    return;
  }

  const padding = { top: 20, right: 20, bottom: 40, left: 60 };
  const chartW = w - padding.left - padding.right;
  const chartH = h - padding.top - padding.bottom;

  const values = data.map((d) => d[valueKey] || 0);
  const maxVal = Math.max(...values, 1);

  // Grid lines
  ctx.strokeStyle = 'rgba(255, 255, 255, 0.06)';
  ctx.lineWidth = 1;
  const gridLines = 5;
  for (let i = 0; i <= gridLines; i++) {
    const y = padding.top + (chartH / gridLines) * i;
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(w - padding.right, y);
    ctx.stroke();

    // Y-axis labels
    const val = maxVal - (maxVal / gridLines) * i;
    ctx.fillStyle = '#6b6b99';
    ctx.font = '11px Inter, sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText(options.formatValue(val), padding.left - 8, y + 4);
  }

  // Bars
  const barGap = 4;
  const barWidth = Math.max(2, (chartW / data.length) - barGap);

  const gradient = ctx.createLinearGradient(0, padding.top, 0, h - padding.bottom);
  gradient.addColorStop(0, options.gradientStart);
  gradient.addColorStop(1, options.gradientEnd);

  data.forEach((d, i) => {
    const val = d[valueKey] || 0;
    const barH = (val / maxVal) * chartH;
    const x = padding.left + i * (barWidth + barGap) + barGap / 2;
    const y = padding.top + chartH - barH;

    // Bar fill
    ctx.fillStyle = gradient;
    ctx.beginPath();
    const radius = Math.min(3, barWidth / 2);
    ctx.roundRect(x, y, barWidth, barH, [radius, radius, 0, 0]);
    ctx.fill();

    // Bar top highlight
    ctx.fillStyle = options.color;
    ctx.beginPath();
    ctx.roundRect(x, y, barWidth, Math.min(3, barH), [radius, radius, 0, 0]);
    ctx.fill();

    // X-axis labels (every Nth)
    const labelEvery = Math.max(1, Math.floor(data.length / 8));
    if (i % labelEvery === 0) {
      ctx.fillStyle = '#6b6b99';
      ctx.font = '10px Inter, sans-serif';
      ctx.textAlign = 'center';
      const label = formatDateLabel(d.period);
      ctx.fillText(label, x + barWidth / 2, h - padding.bottom + 18);
    }
  });
}

function formatDateLabel(isoStr) {
  if (!isoStr) return '';
  const d = new Date(isoStr);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

// ── Recent Orders ────────────────────────────────────
function renderRecentOrders(ordersData) {
  const body = document.getElementById('recent-orders-body');
  const orders = ordersData?.items || [];

  if (!orders.length) {
    body.innerHTML = '<div class="empty-state">No orders yet. Your first order will appear here!</div>';
    return;
  }

  body.innerHTML = `
    <table class="dash-table">
      <thead>
        <tr>
          <th>Order</th>
          <th>Status</th>
          <th>Items</th>
          <th>Total</th>
          <th>Date</th>
        </tr>
      </thead>
      <tbody>
        ${orders.map((o) => `
          <tr>
            <td class="order-number">${o.order_number}</td>
            <td><span class="status-badge ${o.status}">${o.status}</span></td>
            <td>${o.items?.length || 0}</td>
            <td class="order-amount">${formatCurrency(o.total_amount)}</td>
            <td class="order-date">${formatDate(o.created_at)}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;
}

// ── Top Products ─────────────────────────────────────
function renderTopProducts(data) {
  const body = document.getElementById('top-products-body');
  const products = data?.data || [];

  if (!products.length) {
    body.innerHTML = '<div class="empty-state">No sales data yet.</div>';
    return;
  }

  body.innerHTML = products.map((p, idx) => `
    <div class="top-product-item">
      <div class="top-product-rank">${idx + 1}</div>
      <div class="top-product-info">
        <div class="top-product-name">${p.title}</div>
        <div class="top-product-meta">${p.total_sold} sold · ${p.order_count} orders</div>
      </div>
      <div class="top-product-revenue">${formatCurrency(p.total_revenue)}</div>
    </div>
  `).join('');
}

// ── Orders Section ───────────────────────────────────
async function loadOrders() {
  try {
    const data = await api.getOrders(ordersPage, 20, ordersStatus || null);
    renderFullOrders(data);
  } catch (err) {
    console.error('Failed to load orders:', err);
    const el = document.getElementById('full-orders-table');
    el.innerHTML = '<div class="empty-state">Failed to load orders.</div>';
  }
}

function renderFullOrders(data) {
  const container = document.getElementById('full-orders-table');
  const orders = data?.items || [];

  if (!orders.length) {
    container.innerHTML = '<div class="empty-state">No orders found.</div>';
    return;
  }

  container.innerHTML = `
    <table class="dash-table">
      <thead>
        <tr>
          <th>Order #</th>
          <th>Status</th>
          <th>Items</th>
          <th>Subtotal</th>
          <th>Tax</th>
          <th>Total</th>
          <th>Date</th>
        </tr>
      </thead>
      <tbody>
        ${orders.map((o) => `
          <tr>
            <td class="order-number">${o.order_number}</td>
            <td><span class="status-badge ${o.status}">${o.status}</span></td>
            <td>${o.items?.length || 0}</td>
            <td>${formatCurrency(o.subtotal)}</td>
            <td>${formatCurrency(o.tax_amount)}</td>
            <td class="order-amount">${formatCurrency(o.total_amount)}</td>
            <td class="order-date">${formatDate(o.created_at)}</td>
          </tr>
        `).join('')}
      </tbody>
    </table>
  `;

  // Pagination
  const pagination = document.getElementById('orders-pagination');
  if (data.total_pages > 1) {
    pagination.innerHTML = `
      <div class="pagination">
        <button class="pagination-btn" ${ordersPage <= 1 ? 'disabled' : ''} id="prev-page">← Previous</button>
        <span class="pagination-info">Page ${data.page} of ${data.total_pages}</span>
        <button class="pagination-btn" ${ordersPage >= data.total_pages ? 'disabled' : ''} id="next-page">Next →</button>
      </div>
    `;
    document.getElementById('prev-page')?.addEventListener('click', () => {
      if (ordersPage > 1) { ordersPage--; loadOrders(); }
    });
    document.getElementById('next-page')?.addEventListener('click', () => {
      if (ordersPage < data.total_pages) { ordersPage++; loadOrders(); }
    });
  } else {
    pagination.innerHTML = '';
  }
}

// ── Analytics Section ────────────────────────────────
async function loadAnalytics() {
  try {
    const [sales, traffic] = await Promise.all([
      api.getSalesData(currentPeriod, 'day'),
      api.getTrafficData(currentPeriod),
    ]);

    const salesCanvas = document.getElementById('analytics-sales-chart');
    drawBarChart(salesCanvas, sales.data, 'revenue', {
      color: '#6366f1',
      gradientStart: 'rgba(99, 102, 241, 0.3)',
      gradientEnd: 'rgba(99, 102, 241, 0.02)',
      label: 'Revenue',
      formatValue: formatCurrency,
    });

    const trafficCanvas = document.getElementById('analytics-traffic-chart');
    drawBarChart(trafficCanvas, traffic.data, 'views', {
      color: '#a78bfa',
      gradientStart: 'rgba(167, 139, 250, 0.3)',
      gradientEnd: 'rgba(167, 139, 250, 0.02)',
      label: 'Page Views',
      formatValue: (v) => v.toLocaleString(),
    });
  } catch (err) {
    console.error('Failed to load analytics:', err);
  }
}

// ── Products Section ─────────────────────────────────
async function loadProducts() {
  try {
    const data = await api.getListings(1, 100);
    cachedListings = data?.items || [];
    renderFilteredProducts();
  } catch (err) {
    console.error('Failed to load products:', err);
    const grid = document.getElementById('products-grid');
    if (grid) grid.innerHTML = '<div class="empty-state">Failed to load product catalog. Please check your connection.</div>';
  }
}

function renderFilteredProducts() {
  const grid = document.getElementById('products-grid');
  const countBadge = document.getElementById('catalog-count-badge');
  if (!grid) return;

  let filtered = [...cachedListings];

  // Filter by search term
  if (catalogSearchTerm) {
    filtered = filtered.filter((p) => {
      const titleMatch = (p.title || '').toLowerCase().includes(catalogSearchTerm);
      const descMatch = (p.description || '').toLowerCase().includes(catalogSearchTerm);
      const tagMatch = Array.isArray(p.tags) && p.tags.some(t => t.toLowerCase().includes(catalogSearchTerm));
      return titleMatch || descMatch || tagMatch;
    });
  }

  // Filter by type
  if (catalogTypeFilter) {
    filtered = filtered.filter(p => p.type === catalogTypeFilter);
  }

  // Sort
  if (catalogSortBy === 'price-asc') {
    filtered.sort((a, b) => (a.base_price || 0) - (b.base_price || 0));
  } else if (catalogSortBy === 'price-desc') {
    filtered.sort((a, b) => (b.base_price || 0) - (a.base_price || 0));
  } else if (catalogSortBy === 'title-asc') {
    filtered.sort((a, b) => (a.title || '').localeCompare(b.title || ''));
  }

  // Update badge
  if (countBadge) {
    if (filtered.length === cachedListings.length) {
      countBadge.textContent = `${cachedListings.length} ${cachedListings.length === 1 ? 'item' : 'items'}`;
    } else {
      countBadge.textContent = `${filtered.length} of ${cachedListings.length} items`;
    }
  }

  if (!filtered.length) {
    if (cachedListings.length === 0) {
      grid.innerHTML = `
        <div class="empty-state" style="padding: 48px 24px; background: rgba(255, 255, 255, 0.02); border-radius: var(--radius-md); border: 1px dashed var(--border-light);">
          <div style="font-size: 2.5rem; margin-bottom: 12px;">📦</div>
          <h3 style="color: var(--text-primary); margin-bottom: 8px;">No Products in Your Catalog Yet</h3>
          <p style="color: var(--text-muted); max-width: 480px; margin: 0 auto 20px auto;">
            Get started by bulk uploading a CSV / JSON catalog file or manually adding individual products.
          </p>
          <button class="pagination-btn" id="empty-bulk-upload-trigger" style="background: linear-gradient(135deg, #6366f1 0%, #8b5cf6 100%); color: #fff; border: none; font-weight: 600; cursor: pointer;">
            📤 Bulk Upload Catalog
          </button>
        </div>
      `;
      const emptyBtn = document.getElementById('empty-bulk-upload-trigger');
      if (emptyBtn) {
        emptyBtn.onclick = () => document.getElementById('open-bulk-upload-btn')?.click();
      }
    } else {
      grid.innerHTML = `
        <div class="empty-state">
          <div style="font-size: 2rem; margin-bottom: 8px;">🔍</div>
          <p>No products match your current search or filter criteria.</p>
        </div>
      `;
    }
    return;
  }

  grid.innerHTML = filtered.map((p) => {
    const tagsHtml = (p.tags && p.tags.length)
      ? p.tags.slice(0, 4).map(t => `<span class="product-tag-pill">#${escapeHtml(t)}</span>`).join('')
      : '';

    return `
      <div class="product-list-card" id="listing-card-${p.id}">
        <div class="product-list-icon">${getTypeEmoji(p.type)}</div>
        <div class="product-list-info">
          <div class="product-list-name" title="${escapeHtml(p.title)}">${escapeHtml(p.title)}</div>
          <div class="product-list-desc">${escapeHtml(p.description || 'No description provided')}</div>
          <div class="product-list-meta">
            <span class="status-badge ${p.status || 'active'}">${p.status || 'active'}</span>
            <span style="text-transform: capitalize; color: var(--text-secondary);">${p.type}</span>
            <span>⭐ ${(p.rating_avg || 0).toFixed(1)} (${p.rating_count || 0})</span>
            ${tagsHtml}
          </div>
        </div>
        <div class="product-list-price">
          ${formatCurrency(p.base_price)}
          <div style="font-size: 0.7rem; color: var(--text-muted); font-weight: normal;">${p.currency || 'USD'}</div>
        </div>
        <div class="product-list-actions">
          <button class="product-action-btn copy-id-btn" data-id="${p.id}" title="Copy Listing ID">
            📋 ID
          </button>
          <button class="product-action-btn delete delete-listing-btn" data-id="${p.id}" data-title="${escapeHtml(p.title)}" title="Delete from catalog">
            🗑️ Delete
          </button>
        </div>
      </div>
    `;
  }).join('');

  // Attach delete and copy listeners
  grid.querySelectorAll('.delete-listing-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const id = btn.dataset.id;
      const title = btn.dataset.title;
      if (!confirm(`Are you sure you want to remove "${title}" from your catalog?`)) return;

      try {
        btn.disabled = true;
        await api.deleteListing(id);
        showToast(`"${title}" deleted successfully.`);
        await loadProducts();
      } catch (err) {
        showToast('Failed to delete listing: ' + err.message, 'error');
        btn.disabled = false;
      }
    });
  });

  grid.querySelectorAll('.copy-id-btn').forEach(btn => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const id = btn.dataset.id;
      navigator.clipboard.writeText(id)
        .then(() => showToast('Listing ID copied to clipboard!'))
        .catch(() => showToast(id));
    });
  });
}

function downloadFile(content, fileName, mimeType) {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => {
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  }, 100);
}

function escapeHtml(str) {
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// ── Settings Section ─────────────────────────────────
async function loadSettings() {
  try {
    const profile = await api.getMerchantProfile();
    document.getElementById('settings-business-name').value = profile.business_name || '';
    document.getElementById('settings-business-type').value = profile.business_type || 'retail';
    document.getElementById('settings-tax-id').value = profile.tax_id || '';

    // Populate payout account details
    const payout = profile.payout_account || {};
    document.getElementById('settings-stripe-account').value = payout.stripe_account_id || '';
    document.getElementById('settings-razorpay-account').value = payout.razorpay_account_id || '';

    // Populate shareable AI Storefront Link
    const storeLinkInput = document.getElementById('settings-store-link');
    if (storeLinkInput && profile.id) {
      storeLinkInput.value = `http://localhost:3000/?merchant_id=${profile.id}`;
    }

    // Set up copy button event listener
    const copyBtn = document.getElementById('copy-store-link-btn');
    if (copyBtn && storeLinkInput) {
      copyBtn.onclick = () => {
        storeLinkInput.select();
        navigator.clipboard.writeText(storeLinkInput.value)
          .then(() => showToast('Storefront link copied to clipboard!'))
          .catch(() => showToast('Failed to copy link', 'error'));
      };
    }
  } catch (err) {
    console.error('Failed to load settings:', err);
  }
}

// ── Helpers ──────────────────────────────────────────
function formatCurrency(amount) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency: 'USD',
    minimumFractionDigits: 0,
    maximumFractionDigits: 2,
  }).format(amount || 0);
}

function formatDate(isoStr) {
  if (!isoStr) return '—';
  const d = new Date(isoStr);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
}

function getTypeEmoji(type) {
  const map = {
    product: '📦', hotel: '🏨', rental: '🏠', service: '🧰',
    electronics: '💻', real_estate: '🏗️',
  };
  return map[type] || '🛍️';
}

function showLoading() {
  loading.style.display = 'flex';
  document.querySelectorAll('.dash-section').forEach((el) => { el.style.display = 'none'; });
}

function showSection(name) {
  loading.style.display = 'none';
  const el = document.getElementById(`section-${name}`);
  if (el) el.style.display = 'block';
}

function renderEmptyState(sectionId, message) {
  const section = document.getElementById(sectionId);
  if (section) {
    section.innerHTML = `<div class="empty-state">${message}</div>`;
  }
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

// ── Bootstrap ────────────────────────────────────────
init();
