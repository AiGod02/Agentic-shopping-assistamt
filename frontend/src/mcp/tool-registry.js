/**
 * Tool Registry — mirrors the backend ToolRegistry.
 * Registers all MCP tools and provides a unified interface for the orchestrator.
 */
import {
    searchListings,
    getListingDetails,
    checkAvailability,
} from './tools/search-tool.js';
import { viewCart, addToCart, removeFromCart, clearCart } from './tools/cart-tool.js';
import { checkout } from './tools/payment-tool.js';
import { listOrders, getOrderStatus, cancelOrder } from './tools/order-tool.js';

const tools = {};

function register(name, definition) {
    tools[name] = definition;
}

export function getTool(name) {
    return tools[name] || null;
}

export function listTools() {
    return Object.values(tools);
}

export async function executeTool(name, params = {}) {
    const tool = tools[name];
    if (!tool) {
        return { error: `Unknown tool: ${name}` };
    }
    try {
        // Simulate network latency
        await new Promise((r) => setTimeout(r, 300 + Math.random() * 500));
        return tool.handler(params);
    } catch (err) {
        return { error: `Tool ${name} failed: ${err.message}` };
    }
}

// ── Register all commerce tools ──────────────────────────────

register('search_listings', {
    name: 'search_listings',
    description:
        'Search for products, hotels, rentals, services, or any listing. Uses smart hybrid search combining meaning and keywords.',
    category: 'search',
    icon: '🔍',
    parameters: [
        { name: 'query', type: 'string', description: 'Natural language search query', required: true },
        { name: 'type', type: 'string', description: 'Filter by type: product, hotel, rental, service', required: false },
        { name: 'min_price', type: 'number', description: 'Minimum price filter', required: false },
        { name: 'max_price', type: 'number', description: 'Maximum price filter', required: false },
        { name: 'tags', type: 'string', description: 'Comma-separated tags to filter', required: false },
        { name: 'limit', type: 'integer', description: 'Max results (default 10)', required: false },
    ],
    handler: searchListings,
});

register('get_listing_details', {
    name: 'get_listing_details',
    description: 'Get full details of a specific listing including variants, availability, and pricing.',
    category: 'search',
    icon: '📋',
    parameters: [
        { name: 'listing_id', type: 'string', description: 'The listing UUID', required: true },
    ],
    handler: getListingDetails,
});

register('check_availability', {
    name: 'check_availability',
    description: 'Check availability for a hotel, rental, or service listing.',
    category: 'search',
    icon: '📅',
    parameters: [
        { name: 'listing_id', type: 'string', description: 'The listing UUID', required: true },
        { name: 'check_in', type: 'string', description: 'Check-in date (YYYY-MM-DD)', required: false },
        { name: 'check_out', type: 'string', description: 'Check-out date (YYYY-MM-DD)', required: false },
    ],
    handler: checkAvailability,
});

register('view_cart', {
    name: 'view_cart',
    description: 'View the current contents of the user\'s shopping cart.',
    category: 'cart',
    icon: '🛒',
    parameters: [],
    handler: viewCart,
});

register('add_to_cart', {
    name: 'add_to_cart',
    description: 'Add an item to the shopping cart.',
    category: 'cart',
    icon: '➕',
    parameters: [
        { name: 'listing_id', type: 'string', description: 'Listing UUID to add', required: true },
        { name: 'quantity', type: 'integer', description: 'Quantity (default 1)', required: false },
        { name: 'variant_id', type: 'string', description: 'Variant UUID', required: false },
    ],
    handler: addToCart,
    requires_confirmation: true,
});

register('remove_from_cart', {
    name: 'remove_from_cart',
    description: 'Remove a specific item from the cart.',
    category: 'cart',
    icon: '🗑️',
    parameters: [
        { name: 'item_id', type: 'string', description: 'Cart item UUID to remove', required: true },
    ],
    handler: removeFromCart,
});

register('clear_cart', {
    name: 'clear_cart',
    description: 'Clear all items from the cart.',
    category: 'cart',
    icon: '🧹',
    parameters: [],
    handler: clearCart,
});

register('checkout', {
    name: 'checkout',
    description: 'Proceed to checkout — creates order and initiates payment.',
    category: 'order',
    icon: '💳',
    parameters: [
        { name: 'payment_gateway', type: 'string', description: 'Payment method: stripe or razorpay', required: false },
        { name: 'pay_platform', type: 'boolean', description: 'If true, processes transaction directly through the platform account bypassing split payout', required: false },
    ],
    handler: checkout,
    requires_confirmation: true,
});

register('get_order_status', {
    name: 'get_order_status',
    description: 'Check the status of a specific order.',
    category: 'order',
    icon: '📦',
    parameters: [
        { name: 'order_id', type: 'string', description: 'Order UUID', required: true },
    ],
    handler: getOrderStatus,
});

register('list_orders', {
    name: 'list_orders',
    description: 'List all orders for the current user.',
    category: 'order',
    icon: '📋',
    parameters: [],
    handler: listOrders,
});

register('cancel_order', {
    name: 'cancel_order',
    description: 'Cancel a pending or confirmed order.',
    category: 'order',
    icon: '❌',
    parameters: [
        { name: 'order_id', type: 'string', description: 'Order UUID to cancel', required: true },
    ],
    handler: cancelOrder,
    requires_confirmation: true,
});

console.log(`[MCP] ${Object.keys(tools).length} tools registered`);
