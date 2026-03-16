(function () {
    'use strict';

    if (window.__woochatInitialised) return;
    window.__woochatInitialised = true;

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
    const PLACEHOLDER  = cfg.placeholder  || 'Type a message...';
    const WELCOME_MSG  = cfg.welcomeMsg   || 'Hello! How can I help?';
    const PRIMARY      = cfg.primaryColor || '#3b6ef8';

    const STORE_API = STORE_URL + '/wp-json/wc/store/v1';

    // ─────────────────────────────────────────────────────────────────────────
    // 1. BUILD WIDGET HTML — matches screenshots exactly
    // ─────────────────────────────────────────────────────────────────────────
    const container = document.createElement('div');
    container.id    = 'woochat-container';
    container.innerHTML = `

        <!-- Bubble: blue circle with chat icon (screenshot 1) -->
        <div id="woochat-bubble" role="button" aria-label="Open store assistant" tabindex="0">
            <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none">
                <path d="M21 15C21 15.5304 20.7893 16.0391 20.4142 16.4142C20.0391 16.7893 19.5304 17 19 17H7L3 21V5C3 4.46957 3.21071 3.96086 3.58579 3.58579C3.96086 3.21071 4.46957 3 5 3H19C19.5304 3 20.0391 3.21071 20.4142 3.58579C20.7893 3.96086 21 4.46957 21 5V15Z"
                    stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                <circle cx="8"  cy="10" r="1" fill="white"/>
                <circle cx="12" cy="10" r="1" fill="white"/>
                <circle cx="16" cy="10" r="1" fill="white"/>
            </svg>
        </div>

        <!-- Chat window -->
        <div id="woochat-window" role="dialog" aria-label="${escHtml(TITLE)}" aria-hidden="true">

            <!-- Header: emoji + title + × -->
            <div id="woochat-header">
                <span id="woochat-title">🛍️ ${escHtml(TITLE)}</span>
                <button id="woochat-close" aria-label="Close">✕</button>
            </div>

            <!-- Messages -->
            <div id="woochat-messages" role="log" aria-live="polite"></div>

            <!-- Input row -->
            <div id="woochat-input-row">
                <input
                    id="woochat-input"
                    type="text"
                    placeholder="${escHtml(PLACEHOLDER)}"
                    autocomplete="off"
                    aria-label="Type a message"
                    maxlength="500"
                />
                <!-- Grey send button with paper-plane icon (screenshot 2) -->
                <button id="woochat-send" aria-label="Send">
                    <svg xmlns="http://www.w3.org/2000/svg" width="18" height="18" viewBox="0 0 24 24" fill="none">
                        <path d="M22 2L11 13" stroke="white" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
                        <path d="M22 2L15 22L11 13L2 9L22 2Z" stroke="white" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/>
                    </svg>
                </button>
            </div>
        </div>
    `;
    document.body.appendChild(container);

    // Apply dynamic primary colour
    const style = document.createElement('style');
    style.textContent = `
        #woochat-bubble  { background: ${PRIMARY} !important; box-shadow: 0 0 0 10px ${PRIMARY}1e, 0 4px 16px ${PRIMARY}66 !important; }
        #woochat-header  { background: ${PRIMARY} !important; }
        .woochat-msg--user { background: ${PRIMARY} !important; }
        .woochat-login-btn { background: ${PRIMARY} !important; }
        #woochat-input:focus { border-color: ${PRIMARY} !important; box-shadow: 0 0 0 3px ${PRIMARY}1e !important; }
        #woochat-send:hover  { background: ${PRIMARY} !important; }
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
        win.style.display = 'flex';
        win.setAttribute('aria-hidden', 'false');
        bubble.style.display = 'none';

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
        win.style.display = 'none';
        win.setAttribute('aria-hidden', 'true');
        bubble.style.display = 'flex';
    }

    bubble.addEventListener('click', openChat);
    bubble.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') openChat(); });
    closeBtn.addEventListener('click', closeChat);
    document.addEventListener('keydown', e => { if (e.key === 'Escape' && isOpen) closeChat(); });

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
        if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
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

            // Parse out [PRODUCT_CARD] blocks before rendering text
            const { text: cleanText, cards } = extractProductCards(reply);
            if (cleanText.trim()) {
                appendMessage('bot', formatResponse(cleanText));
            }
            if (cards.length === 1) {
                appendProductCard(cards[0]);
            } else if (cards.length > 1) {
                appendProductCardRow(cards);
            }

            if (action === 'cart_updated') refreshWooCart();
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
    async function storeApiRequest(method, path, body) {
        const opts = {
            method,
            headers: { 'Content-Type': 'application/json', 'Nonce': WC_NONCE },
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

    function viewCart()              { return storeApiRequest('GET',    '/cart'); }
    function removeFromCart(itemKey) { return storeApiRequest('DELETE', '/cart/items/' + itemKey); }
    function applyCoupon(code)       { return storeApiRequest('POST',   '/cart/coupons', { code }); }

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
        isLoading = loading;
        sendBtn.disabled = loading;
        input.disabled   = loading;

        const existing = document.getElementById('woochat-typing');
        if (loading && !existing) {
            const t = document.createElement('div');
            t.id        = 'woochat-typing';
            t.className = 'woochat-typing';
            t.innerHTML = '<span></span><span></span><span></span>';
            messages.appendChild(t);
            messages.scrollTop = messages.scrollHeight;
        } else if (!loading && existing) {
            existing.remove();
        }
        if (!loading) input.focus();
    }

    // Converts agent markdown-lite response to HTML
    // Matches screenshot: "* **Product Name** - price (In stock)"
    function formatResponse(text) {
        if (!text) return '';
        let s = escHtml(text);
        // Bold: **text**
        s = s.replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>');
        // Italic: *text* — but NOT bullet points (handled separately)
        s = s.replace(/(?<!\n)\*(?!\s)(.*?)\*/g, '<em>$1</em>');
        // Newlines to <br>
        s = s.replace(/\n/g, '<br>');
        // Markdown Links: [text](url)
        s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s<")]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
        
        // Clickable URLs (that aren't already part of an a-tag from the markdown regex)
        // We use a replacer function to avoid breaking HTML attributes
        s = s.replace(/(https?:\/\/[^\s<")]+)/g, function(match, p1, offset, string) {
            // If it's preceded by href=" or >, it's likely already an HTML link
            if (offset > 0 && string.charAt(offset - 1) === '"') return match;
            if (offset > 0 && string.charAt(offset - 1) === '>') return match;
            return '<a href="' + match + '" target="_blank" rel="noopener noreferrer">' + match + '</a>';
        });
        return s;
    }

    function escHtml(str) {
        const d = document.createElement('div');
        d.appendChild(document.createTextNode(str || ''));
        return d.innerHTML;
    }


    // ─────────────────────────────────────────────────────────────────────────
    // PRODUCT CARD — parse [PRODUCT_CARD]...[/PRODUCT_CARD] from agent reply
    // ─────────────────────────────────────────────────────────────────────────
    function extractProductCards(text) {
        const cards = [];
        const regex = /\[PRODUCT_CARD\]([\s\S]*?)\[\/PRODUCT_CARD\]/g;
        let match;
        while ((match = regex.exec(text)) !== null) {
            try {
                cards.push(JSON.parse(match[1].trim()));
            } catch (e) {
                console.warn('[WooChat] Failed to parse product card:', e);
            }
        }
        const clean = text.replace(/\[PRODUCT_CARD\][\s\S]*?\[\/PRODUCT_CARD\]/g, '').trim();
        return { text: clean, cards };
    }

    // Build card HTML — matches screenshot: full image top, desc left, price right
    function buildCardHTML(card, compact) {
        const hasDiscount = card.sale_price &&
            card.sale_price !== card.regular_price &&
            parseFloat(card.sale_price) > 0 &&
            parseFloat(card.regular_price) > 0;

        const discount = hasDiscount
            ? Math.round((1 - parseFloat(card.sale_price) / parseFloat(card.regular_price)) * 100)
            : 0;

        const price     = hasDiscount ? card.sale_price    : (card.regular_price || card.sale_price || '');
        const origPrice = hasDiscount ? card.regular_price : '';

        // Image section — full width top
        const imageHTML = card.image_url
            ? '<div class="wpc-image-wrap"><img src="' + escHtml(card.image_url) + '" alt="' + escHtml(card.name) + '" class="wpc-image" loading="lazy"/></div>'
            : '<div class="wpc-image-wrap wpc-no-image">🛍️</div>';

        // Price section
        const priceHTML =
            (origPrice
                ? '<div class="wpc-price-row"><span class="wpc-label-sm">REGULAR PRICE:</span><span class="wpc-price-old">\u20b9' + escHtml(origPrice) + '</span></div>'
                : '') +
            '<div class="wpc-price-row"><span class="wpc-label-sm' + (hasDiscount ? '' : '') + '">' + (hasDiscount ? 'SALE PRICE:' : 'PRICE:') + '</span>' +
            '<span class="wpc-price-sale">\u20b9' + escHtml(price) +
            (hasDiscount ? ' <span class="wpc-badge">' + discount + '% OFF</span>' : '') +
            '</span></div>' +
            (!compact && card.sku
                ? '<div class="wpc-price-row"><span class="wpc-label-sm">SKU:</span><span class="wpc-sku">' + escHtml(card.sku) + '</span></div>'
                : '');

        const btnHTML = (card.permalink
                ? '<a href="' + escHtml(card.permalink) + '" target="_blank" rel="noopener noreferrer" class="wpc-btn">\uD83C\uDF10 ' + (compact ? 'VIEW' : 'VIEW PRODUCT GALLERY') + '</a>'
                : '');

        // Description section
        const descHTML =
            '<div class="wpc-name">' + escHtml(card.name) + '</div>' +
            (card.description
                ? '<p class="wpc-desc">' + escHtml(card.description) + '</p>'
                : '');

        return imageHTML +
            '<div class="wpc-body' + (compact ? ' wpc-body--compact' : '') + '">' +
                '<div class="wpc-main-info">' +
                    '<div class="wpc-description-col">' + descHTML + '</div>' +
                    '<div class="wpc-price-col">' + priceHTML + '</div>' +
                '</div>' +
                btnHTML +
            '</div>';
    }
    // Single card — full width
    function appendProductCard(card) {
        const div = document.createElement('div');
        div.className = 'woochat-product-card';
        div.innerHTML = buildCardHTML(card, false);
        messages.appendChild(div);
        messages.scrollTop = messages.scrollHeight;
    }

    // Multiple cards — horizontal scrollable row
    function appendProductCardRow(cards) {
        const wrapper = document.createElement('div');
        wrapper.className = 'woochat-card-row';

        cards.forEach(card => {
            const div = document.createElement('div');
            div.className = 'woochat-product-card woochat-product-card--compact';
            div.innerHTML = buildCardHTML(card, true);
            wrapper.appendChild(div);
        });

        messages.appendChild(wrapper);
        messages.scrollTop = messages.scrollHeight;
    }

    // ─────────────────────────────────────────────────────────────────────────
    // 8. AUTO-CLEAR SESSION ON LOGOUT
    // ─────────────────────────────────────────────────────────────────────────
    document.addEventListener('click', function (e) {
        const link = e.target.closest('a[href*="action=logout"]');
        if (!link) return;
        navigator.sendBeacon(AJAX_URL, new URLSearchParams({
            action:     'woochat_clear_session',
            nonce:      NONCE,
            session_id: SESSION_ID,
        }));
    });

})();
// This line intentionally left blank
