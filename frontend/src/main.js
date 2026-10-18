/**
 * Main entry point — bootstraps the Agentic Commerce frontend.
 */
import './styles/index.css';
import { processMessage, ensureAuthToken, resetSession } from './mcp/agent-orchestrator.js';
import { renderChat } from './components/chat.js';
import { renderCart, updateCartUI } from './components/cart.js';

// ── DOM References ──────────────────────────────────
const chatInput = document.getElementById('chat-input');
const sendBtn = document.getElementById('send-btn');
const chatMessages = document.getElementById('chat-messages');
const chatContainer = document.getElementById('chat-container');
const welcomeCard = document.getElementById('welcome-card');
const sidebarToggle = document.getElementById('sidebar-toggle');
const cartSidebar = document.getElementById('cart-sidebar');
const newChatBtn = document.getElementById('new-chat-btn');
const checkoutBtn = document.getElementById('checkout-btn');
const ordersBtn = document.getElementById('orders-btn');
const helpBtn = document.getElementById('help-btn');
const quickActions = document.querySelectorAll('.quick-action-btn');

let isProcessing = false;

// ── Event Listeners ──────────────────────────────────
if (newChatBtn) {
    newChatBtn.addEventListener('click', () => {
        resetSession();
        chatMessages.innerHTML = '';
        if (welcomeCard) {
            welcomeCard.style.display = '';
            chatMessages.appendChild(welcomeCard);
        }
        chatInput.value = '';
        chatInput.focus();
    });
}

chatInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleSend();
    }
});

sendBtn.addEventListener('click', handleSend);

sidebarToggle.addEventListener('click', () => {
    cartSidebar.classList.toggle('open');
});

checkoutBtn.addEventListener('click', () => {
    sendMessage('Checkout');
});

ordersBtn.addEventListener('click', () => {
    sendMessage('Show my orders');
});

helpBtn.addEventListener('click', () => {
    sendMessage('Help');
});

quickActions.forEach((btn) => {
    btn.addEventListener('click', () => {
        const query = btn.getAttribute('data-query');
        if (query) sendMessage(query);
    });
});

// ── Send Message Flow ────────────────────────────────

function sendMessage(text) {
    chatInput.value = text;
    handleSend();
}

async function handleSend() {
    const message = chatInput.value.trim();
    if (!message || isProcessing) return;

    isProcessing = true;
    sendBtn.disabled = true;
    chatInput.value = '';

    // Hide welcome card on first message
    if (welcomeCard) {
        welcomeCard.style.display = 'none';
    }

    // Add user message
    renderChat.addUserMessage(chatMessages, message);
    scrollToBottom();

    // Show typing indicator
    const typingEl = renderChat.showTyping(chatMessages);
    scrollToBottom();

    try {
        // Process through agent orchestrator
        const result = await processMessage(message);

        // Remove typing indicator
        typingEl.remove();

        // Show tool call indicators
        if (result.toolCalls?.length > 0) {
            for (const tc of result.toolCalls) {
                renderChat.addToolCall(chatMessages, tc);
                scrollToBottom();
                await sleep(200);
            }
        }

        // Add agent response
        renderChat.addAgentMessage(chatMessages, result.text, result);
        scrollToBottom();

        // Render product cards if search results
        if (result.products?.length > 0) {
            renderChat.addProductGrid(chatMessages, result.products, (product) => {
                sendMessage(`Add ${product.name} to cart`);
            });
            scrollToBottom();
        }

        // Render Sign In CTA if checkout requires account sign-in
        if (result.requiresSignIn) {
            renderChat.addSignInPrompt(chatMessages, async () => {
                renderChat.addUserMessage(chatMessages, "🔑 Signing in...");
                scrollToBottom();
                try {
                    const loginRes = await fetch('/api/merchant/merchants/login', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ email: 'customer@example.com', password: 'password' }),
                    });
                    if (loginRes.ok) {
                        const loginData = await loginRes.json();
                        localStorage.setItem('acp_jwt_token', loginData.access_token);
                        localStorage.setItem('acp_is_guest', 'false');
                        renderChat.addAgentMessage(chatMessages, "✅ Signed in successfully! Resuming checkout...");
                        updateCartUI();
                        sendMessage("Checkout");
                    } else {
                        renderChat.addAgentMessage(chatMessages, "Sign in failed. Please check your credentials.");
                    }
                } catch (e) {
                    renderChat.addAgentMessage(chatMessages, `Sign in error: ${e.message}`);
                }
            });
            scrollToBottom();
        }

        // Update cart UI if cart was modified
        if (result.cart || result.type === 'cart_update' || result.type === 'cart_view' || result.type === 'checkout') {
            updateCartUI();
        }
    } catch (err) {
        typingEl?.remove();
        renderChat.addAgentMessage(chatMessages, `❌ Something went wrong: ${err.message}. Please try again.`);
        scrollToBottom();
    }

    isProcessing = false;
    sendBtn.disabled = false;
    chatInput.focus();
}

function scrollToBottom() {
    requestAnimationFrame(() => {
        chatContainer.scrollTop = chatContainer.scrollHeight;
    });
}

function sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
}

// ── Initialize ───────────────────────────────────────
ensureAuthToken().finally(() => {
    updateCartUI();
});
import { initStorefront } from './components/storefront.js';
initStorefront();
console.log('[Agentic Commerce] Frontend initialized');
