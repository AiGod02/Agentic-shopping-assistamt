/**
 * Chat Component — renders chat messages, tool calls, product grids, and typing indicators.
 */

/** Simple markdown-like formatting for agent messages */
function formatMessage(text) {
    return text
        // Bold
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        // Italic (underscores)
        .replace(/_(.+?)_/g, '<em>$1</em>')
        // Line breaks
        .replace(/\n/g, '<br/>');
}

export const renderChat = {
    /**
     * Add a user message bubble to the chat.
     */
    addUserMessage(container, text) {
        const el = document.createElement('div');
        el.className = 'chat-message user';
        el.innerHTML = `
      <div class="chat-avatar">👤</div>
      <div class="chat-bubble">${escapeHtml(text)}</div>
    `;
        container.appendChild(el);
        return el;
    },

    /**
     * Add an agent message bubble with optional formatted content.
     */
    addAgentMessage(container, text, result = null) {
        const el = document.createElement('div');
        el.className = 'chat-message agent';
        el.innerHTML = `
      <div class="chat-avatar">🤖</div>
      <div class="chat-bubble">${formatMessage(text)}</div>
    `;
        container.appendChild(el);
        return el;
    },

    /**
     * Show a Scira-style tool invocation card with collapsible arguments.
     */
    addToolCall(container, toolCall) {
        const el = document.createElement('div');
        const isError = toolCall.status === 'error';
        const statusClass = isError ? 'error' : 'completed';
        const statusBadge = isError ? '❌ Error' : '✅ Completed';
        const toolIcons = {
            search_listings: '🔍',
            get_listing_details: '📋',
            check_availability: '📅',
            view_cart: '🛒',
            add_to_cart: '➕',
            remove_from_cart: '🗑️',
            clear_cart: '🧹',
            checkout: '💳',
            get_order_status: '📦',
            list_orders: '📋',
            cancel_order: '❌',
        };

        const paramsStr = toolCall.params ? JSON.stringify(toolCall.params, null, 2) : '';

        el.className = `tool-call-indicator ${statusClass}`;
        el.innerHTML = `
            <div class="tool-call-header">
                <span>${toolIcons[toolCall.tool] || '⚙️'}</span>
                <span style="font-weight: 600; color: var(--text-primary);">${toolCall.tool}</span>
                <span style="margin-left: auto; font-size: 0.72rem;">${statusBadge}</span>
                ${paramsStr ? `<span class="tool-call-arrow" style="font-size: 0.65rem; color: var(--text-muted); margin-left: 6px;">▼</span>` : ''}
            </div>
            ${paramsStr ? `<div class="tool-call-body" style="display: none;">${escapeHtml(paramsStr)}</div>` : ''}
        `;

        if (paramsStr) {
            const header = el.querySelector('.tool-call-header');
            const body = el.querySelector('.tool-call-body');
            const arrow = el.querySelector('.tool-call-arrow');
            header.addEventListener('click', () => {
                const isOpen = body.style.display !== 'none';
                body.style.display = isOpen ? 'none' : 'block';
                if (arrow) arrow.textContent = isOpen ? '▼' : '▲';
            });
        }

        container.appendChild(el);
        return el;
    },

    /**
     * Show a prominent Sign In prompt card when checkout requires authentication.
     */
    addSignInPrompt(container, onSignIn) {
        const el = document.createElement('div');
        el.className = 'chat-message agent';
        el.innerHTML = `
            <div class="chat-avatar">🔒</div>
            <div class="chat-bubble sign-in-cta-card">
                <p><strong>Sign In Required for Checkout</strong></p>
                <p style="font-size: 0.85rem; margin-top: 6px; color: var(--text-secondary);">
                    You are shopping as a guest. To complete your order, please sign in to your account.
                </p>
                <button class="sign-in-cta-btn" id="sign-in-cta-btn">
                    🔑 Sign In to Complete Purchase
                </button>
            </div>
        `;
        container.appendChild(el);
        const btn = el.querySelector('#sign-in-cta-btn');
        if (btn && onSignIn) {
            btn.addEventListener('click', onSignIn);
        }
        return el;
    },


    /**
     * Show typing indicator with bouncing dots.
     */
    showTyping(container) {
        const el = document.createElement('div');
        el.className = 'chat-message agent';
        el.id = 'typing-indicator';
        el.innerHTML = `
      <div class="chat-avatar">🤖</div>
      <div class="chat-bubble">
        <div class="typing-indicator">
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
          <div class="typing-dot"></div>
        </div>
      </div>
    `;
        container.appendChild(el);
        return el;
    },

    /**
     * Render a grid of product cards inside the chat.
     */
    addProductGrid(container, products, onAddToCart) {
        const grid = document.createElement('div');
        grid.className = 'product-grid';

        products.forEach((product) => {
            const card = document.createElement('div');
            card.className = 'product-card';
            const price = (Number(product.price) || 0).toFixed(2);
        const rating = Number(product.rating) || 0;
        card.innerHTML = `
        <div class="product-card-emoji">${product.image || '📦'}</div>
        <div class="product-card-name">${escapeHtml(product.name || 'Product')}</div>
        <div class="product-card-price">$${price}</div>
        <div class="product-card-rating">⭐ ${rating} (${product.reviews_count || 0} reviews)</div>
        <div class="product-card-stock ${product.in_stock ? 'in-stock' : 'out-of-stock'}">
          ${product.in_stock ? '✅ In Stock' : '❌ Out of Stock'}
        </div>
        <div class="product-card-actions">
          <button class="product-card-btn primary add-btn" ${!product.in_stock ? 'disabled' : ''}>
            🛒 Add to Cart
          </button>
        </div>
      `;

            const addBtn = card.querySelector('.add-btn');
            if (addBtn && product.in_stock) {
                addBtn.addEventListener('click', (e) => {
                    e.stopPropagation();
                    onAddToCart(product);
                });
            }

            grid.appendChild(card);
        });

        container.appendChild(grid);
        return grid;
    },
};

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
