(function () {
    'use strict';

    // ── Guard: don't initialise twice ─────────────────────────────────────────
    if (window.__woochatInitialised) return;
    window.__woochatInitialised = true;

    // ── Config injected by wp_localize_script ─────────────────────────────────
    const cfg = window.woochatConfig || {};

    const AJAX_URL     = cfg.ajaxUrl     || '';
    const NONCE        = cfg.nonce       || '';
    const WC_NONCE     = cfg.wcNonce     || '';
    const STORE_URL    = cfg.storeUrl    || '';
    const SESSION_ID   = cfg.sessionId   || '';
    const IS_LOGGED_IN = cfg.isLoggedIn  || false;
    const LOGIN_URL    = cfg.loginUrl    || '';
    const USERNAME     = cfg.username    || '';
    const TITLE        = cfg.widgetTitle  || 'Store Assistant';
    const PLACEHOLDER  = cfg.placeholder  || 'Ask me anything...';
    const WELCOME_MSG  = cfg.welcomeMsg   || 'Hi! How can I help you today?';
    const PRIMARY      = cfg.primaryColor || '#2271b1';

    // ── Store API base ────────────────────────────────────────────────────────
    const STORE_API = STORE_URL + '/wp-json/wc/store/v1';

    // ─────────────────────────────────────────────────────────────────────────
    // 1. BUILD WIDGET HTML
    // ─────────────────────────────────────────────────────────────────────────
    const container  = document.createElement('div');
    container.id     = 'woochat-container';
    container.innerHTML = `
        <div id="woochat-bubble" role="button" aria-label="Open chat assistant" tabindex="0">
            <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" width="26" height="26">
                <path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2z"/>
            </svg>
        </div>

        <div id="woochat-window" role="dialog" aria-label="Store Assistant" aria-hidden="true">
            <div id="woochat-header">
                <span id="woochat-title">${escHtml(TITLE)}</span>
                <button id="woochat-close" aria-label="Close chat">✕</button>
            </div>
            <div id="woochat-messages" role="log" aria-live="polite"></div>
            <div id="woochat-input-row">
                <input
                    id="woochat-input"
                    type="text"
                    placeholder="${escHtml(PLACEHOLDER)}"
                    autocomplete="off"
                    aria-label="Type a message"
                    maxlength="500"
                />
                <button id="woochat-send" aria-label="Send message">
                    <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="white" width="18" height="18">
                        <path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/>
                    </svg>
                </button>
            </div>
        </div>
    `;
    document.body.appendChild(container);

    // ── Apply primary colour dynamically ──────────────────────────────────────
    const style = document.createElement('style');
    style.textContent = `
        #woochat-bubble { background: ${PRIMARY} !important; }
        #woochat-header { background: ${PRIMARY} !important; }
        #woochat-send   { background: ${PRIMARY} !important; }
        #woochat-input:focus {
            border-color: ${PRIMARY} !important;
            box-shadow: 0 0 0 2px ${PRIMARY}33 !important;
        }
        .woochat-login-btn {
            background: ${PRIMARY} !important;
        }
    `;
    document.head.appendChild(style);

    // ─────────────────────────────────────────────────────────────────────────
    // 2. DOM REFERENCES
    // ─────────────────────────────────────────────────────────────────────────
    const bubble   = document.getElementById('woochat-bubble');
    const win      = document.getElementById('woochat-window');
    const messages = document.getElementById('woochat-messages');
    const input    = document.getElementById('woochat-input');
    const sendBtn  = document.getElementById('woochat-send');
    const closeBtn = document.getElementById('woochat-close');

    let isOpen    = false;
    let isLoading = false;

    // ─────────────────────────────────────────────────────────────────────────
    // 3. OPEN / CLOSE
    // ─────────────────────────────────────────────────────────────────────────
    function openChat() {
        isOpen = true;
        win.style.display    = 'flex';
        win.setAttribute('aria-hidden', 'false');
        bubble.style.display = 'none';

        // Show welcome message only on first open
        if (messages.children.length === 0) {
            const greeting = IS_LOGGED_IN && USERNAME
                ? 'Hi ' + escHtml(USERNAME) + '! ' + escHtml(WELCOME_MSG)
                : escHtml(WELCOME_MSG);
            appendMessage('bot', greeting);
        }

        input.focus();
    }

    function closeChat() {
        isOpen = false;
        win.style.display    = 'none';
        win.setAttribute('aria-hidden', 'true');
        bubble.style.display = 'flex';
    }

    bubble.addEventListener('click', openChat);
    bubble.addEventListener('keydown', e => {
        if (e.key === 'Enter' || e.key === ' ') openChat();
    });
    closeBtn.addEventListener('click', closeChat);
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape' && isOpen) closeChat();
    });

    // ─────────────────────────────────────────────────────────────────────────
    // 4. SEND MESSAGE
    // ─────────────────────────────────────────────────────────────────────────
    function sendMessage() {
        const text = input.value.trim();
        if (!text || isLoading) return;

        appendMessage('user', escHtml(text));
        input.value = '';
        setLoading(true);
        proxyToAgent(text);
    }

    sendBtn.addEventListener('click', sendMessage);
    input.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendMessage();
        }
    });

    // ─────────────────────────────────────────────────────────────────────────
    // 5. PROXY TO RAILWAY VIA WORDPRESS AJAX
    // ─────────────────────────────────────────────────────────────────────────
    function proxyToAgent(message) {
        fetch(AJAX_URL, {
            method:      'POST',
            headers:     { 'Content-Type': 'application/x-www-form-urlencoded' },
            credentials: 'same-origin',
            body: new URLSearchParams({
                action:     'woochat_message',
                nonce:      NONCE,
                message:    message,
                session_id: SESSION_ID,
                wc_nonce:   WC_NONCE,
            }),
        })
        .then(r => r.json())
        .then(data => {
            setLoading(false);

            if (!data.success) {
                appendMessage('bot', '⚠️ ' + (data.data || 'Something went wrong. Please try again.'));
                return;
            }

            const reply  = data.data.response || '';
            const action = data.data.action   || null;

            if (action === 'prompt_login') {
                appendMessage('bot', formatResponse(reply));
                appendLoginPrompt();
                return;
            }

            appendMessage('bot', formatResponse(reply));

            if (action === 'cart_updated') {
                refreshWooCart();
            }
        })
        .catch(err => {
            setLoading(false);
            console.error('[WooChat]', err);
            appendMessage('bot', '⚠️ Could not reach the assistant. Please check your connection.');
        });
    }

    // ─────────────────────────────────────────────────────────────────────────
    // 6. STORE API — DIRECT CART CALLS FROM BROWSER
    // ─────────────────────────────────────────────────────────────────────────
    // Cart calls go directly from the browser to WooCommerce Store API.
    // The visitor's session cookie authenticates these automatically.
    // Railway never touches cart operations directly.

    async function storeApiRequest(method, path, body) {
        const opts = {
            method,
            headers: {
                'Content-Type': 'application/json',
                'Nonce':        WC_NONCE,
            },
            credentials: 'include',
        };
        if (body) opts.body = JSON.stringify(body);

        const res = await fetch(STORE_API + path, opts);
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            throw new Error(err.message || 'Store API error ' + res.status);
        }
        return res.json();
    }

    function addToCart(productId, quantity, variationId) {
        const body = { id: productId, quantity: quantity || 1 };
        if (variationId) body.variation_id = variationId;
        return storeApiRequest('POST', '/cart/add-item', body);
    }

    function viewCart() {
        return storeApiRequest('GET', '/cart');
    }

    function removeFromCart(itemKey) {
        return storeApiRequest('DELETE', '/cart/items/' + itemKey);
    }

    function applyCoupon(code) {
        return storeApiRequest('POST', '/cart/coupons', { code });
    }

    function refreshWooCart() {
        if (typeof jQuery !== 'undefined') {
            jQuery(document.body).trigger('wc_fragment_refresh');
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    // 7. UI HELPERS
    // ─────────────────────────────────────────────────────────────────────────
    function appendMessage(role, html) {
        const div = document.createElement('div');
        div.className = 'woochat-msg woochat-msg--' + role;
        div.innerHTML = html;
        messages.appendChild(div);
        messages.scrollTop = messages.scrollHeight;
    }

    function appendLoginPrompt() {
        const div = document.createElement('div');
        div.className = 'woochat-msg woochat-msg--bot';
        div.innerHTML = `<a href="${escHtml(LOGIN_URL)}" class="woochat-login-btn">🔐 Log in to continue</a>`;
        messages.appendChild(div);
        messages.scrollTop = messages.scrollHeight;
    }

    function setLoading(loading) {
        isLoading        = loading;
        sendBtn.disabled = loading;
        input.disabled   = loading;

        const existing = document.getElementById('woochat-typing');
        if (loading && !existing) {
            const t = document.createElement('div');
            t.id        = 'woochat-typing';
            t.className = 'woochat-msg woochat-msg--bot woochat-typing';
            t.innerHTML = '<span></span><span></span><span></span>';
            messages.appendChild(t);
            messages.scrollTop = messages.scrollHeight;
        } else if (!loading && existing) {
            existing.remove();
        }

        if (!loading) input.focus();
    }

    // Format agent response — converts markdown-lite to HTML
    function formatResponse(text) {
        if (!text) return '';
        let s = escHtml(text);
        s = s.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        s = s.replace(/\*(.*?)\*/g,     '<em>$1</em>');
        s = s.replace(/^•\s+/gm,        '• ');
        s = s.replace(/\n/g,            '<br>');
        s = s.replace(
            /(https?:\/\/[^\s<"]+)/g,
            '<a href="$1" target="_blank" rel="noopener noreferrer">$1</a>'
        );
        return s;
    }

    function escHtml(str) {
        const d = document.createElement('div');
        d.appendChild(document.createTextNode(str || ''));
        return d.innerHTML;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // 8. AUTO-CLEAR SESSION ON LOGOUT
    // ─────────────────────────────────────────────────────────────────────────
    document.addEventListener('click', function (e) {
        const link = e.target.closest('a[href*="action=logout"]');
        if (!link) return;
        // Non-blocking beacon — clears Railway session without delaying logout
        navigator.sendBeacon(AJAX_URL, new URLSearchParams({
            action:     'woochat_clear_session',
            nonce:      NONCE,
            session_id: SESSION_ID,
        }));
    });

})();