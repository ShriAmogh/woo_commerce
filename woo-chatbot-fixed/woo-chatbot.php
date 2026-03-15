<?php
/**
 * Plugin Name: WooCommerce AI Chatbot
 * Plugin URI:  https://github.com/your-repo/woo-chatbot
 * Description: AI-powered shopping assistant for WooCommerce stores. Connects to your hosted Gemini agent to help visitors browse products, check stock, and manage their cart.
 * Version:     1.0.0
 * Author:      Your Name
 * License:     GPL-2.0+
 * Text Domain: woo-chatbot
 * Requires at least: 6.0
 * Requires PHP: 8.0
 * WC requires at least: 6.9
 */

// ─── Safety: prevent direct file access ───────────────────────────────────────
if ( ! defined( 'ABSPATH' ) ) {
    exit;
}

// ─── Plugin Constants ─────────────────────────────────────────────────────────
define( 'WOOCHAT_VERSION',     '1.0.0' );
define( 'WOOCHAT_PLUGIN_DIR',  plugin_dir_path( __FILE__ ) );
define( 'WOOCHAT_PLUGIN_URL',  plugin_dir_url( __FILE__ ) );
define( 'WOOCHAT_PLUGIN_FILE', __FILE__ );

// ─── Load Components ──────────────────────────────────────────────────────────
require_once WOOCHAT_PLUGIN_DIR . 'includes/api-proxy.php';

// ─── Activation Hook ──────────────────────────────────────────────────────────
register_activation_hook( __FILE__, 'woochat_activate' );
function woochat_activate() {
    // Check WooCommerce is active
    if ( ! class_exists( 'WooCommerce' ) ) {
        deactivate_plugins( plugin_basename( __FILE__ ) );
        wp_die(
            '<strong>WooCommerce AI Chatbot</strong> requires WooCommerce to be installed and active.',
            'Plugin Activation Error',
            [ 'back_link' => true ]
        );
    }

    // Check WooCommerce version
    if ( defined( 'WC_VERSION' ) && version_compare( WC_VERSION, '6.9.0', '<' ) ) {
        deactivate_plugins( plugin_basename( __FILE__ ) );
        wp_die(
            '<strong>WooCommerce AI Chatbot</strong> requires WooCommerce 6.9 or higher. You are running ' . WC_VERSION,
            'Plugin Activation Error',
            [ 'back_link' => true ]
        );
    }

    // Set default options on first activation
    add_option( 'woochat_agent_url',     '' );
    add_option( 'woochat_enabled',       '1' );
    add_option( 'woochat_widget_title',  'Store Assistant' );
    add_option( 'woochat_placeholder',   'Ask me anything...' );
    add_option( 'woochat_welcome_msg',   'Hi! I\'m your shopping assistant. How can I help you today?' );
    add_option( 'woochat_primary_color', '#2271b1' );
}

// ─── Deactivation Hook ────────────────────────────────────────────────────────
register_deactivation_hook( __FILE__, 'woochat_deactivate' );
function woochat_deactivate() {
    // Options preserved so settings survive deactivation/reactivation
}

// ─── Admin Settings Page ──────────────────────────────────────────────────────
add_action( 'admin_menu', 'woochat_add_settings_page' );
function woochat_add_settings_page() {
    add_options_page(
        'WooCommerce AI Chatbot Settings',
        'AI Chatbot',
        'manage_options',
        'woo-chatbot',
        'woochat_render_settings_page'
    );
}

// ─── Register Settings ────────────────────────────────────────────────────────
add_action( 'admin_init', 'woochat_register_settings' );
function woochat_register_settings() {
    register_setting( 'woochat_settings', 'woochat_agent_url',     [ 'sanitize_callback' => 'esc_url_raw' ] );
    register_setting( 'woochat_settings', 'woochat_enabled',       [ 'sanitize_callback' => 'sanitize_text_field' ] );
    register_setting( 'woochat_settings', 'woochat_widget_title',  [ 'sanitize_callback' => 'sanitize_text_field' ] );
    register_setting( 'woochat_settings', 'woochat_placeholder',   [ 'sanitize_callback' => 'sanitize_text_field' ] );
    register_setting( 'woochat_settings', 'woochat_welcome_msg',   [ 'sanitize_callback' => 'sanitize_text_field' ] );
    register_setting( 'woochat_settings', 'woochat_primary_color', [ 'sanitize_callback' => 'sanitize_hex_color' ] );
}

// ─── Render Settings Page ─────────────────────────────────────────────────────
function woochat_render_settings_page() {
    if ( ! current_user_can( 'manage_options' ) ) return;

    $saved         = isset( $_GET['settings-updated'] ) && $_GET['settings-updated'];
    $agent_url     = get_option( 'woochat_agent_url',     '' );
    $enabled       = get_option( 'woochat_enabled',       '1' );
    $widget_title  = get_option( 'woochat_widget_title',  'Store Assistant' );
    $placeholder   = get_option( 'woochat_placeholder',   'Ask me anything...' );
    $welcome_msg   = get_option( 'woochat_welcome_msg',   'Hi! How can I help you today?' );
    $primary_color = get_option( 'woochat_primary_color', '#2271b1' );

    // Live connection test
    $connection_status = '';
    if ( ! empty( $agent_url ) ) {
        $response = wp_remote_get( trailingslashit( $agent_url ) . 'health', [ 'timeout' => 5 ] );
        $connection_status = ( ! is_wp_error( $response ) && wp_remote_retrieve_response_code( $response ) === 200 )
            ? 'ok'
            : 'error';
    }
    ?>
    <div class="wrap">
        <h1>🛍️ WooCommerce AI Chatbot</h1>

        <?php if ( $saved ) : ?>
            <div class="notice notice-success is-dismissible"><p>Settings saved successfully.</p></div>
        <?php endif; ?>

        <?php if ( $connection_status === 'ok' ) : ?>
            <div class="notice notice-success"><p>✅ <strong>Agent connected</strong> — Railway agent is reachable.</p></div>
        <?php elseif ( $connection_status === 'error' ) : ?>
            <div class="notice notice-error"><p>❌ <strong>Agent unreachable</strong> — check your Agent URL and Railway deployment.</p></div>
        <?php endif; ?>

        <form method="post" action="options.php">
            <?php settings_fields( 'woochat_settings' ); ?>

            <h2 class="title">Connection</h2>
            <table class="form-table" role="presentation">
                <tr>
                    <th scope="row"><label for="woochat_agent_url">Agent URL</label></th>
                    <td>
                        <input type="url" id="woochat_agent_url" name="woochat_agent_url"
                            value="<?php echo esc_attr( $agent_url ); ?>"
                            placeholder="https://your-agent.up.railway.app"
                            class="regular-text" />
                        <p class="description">
                            Public URL of your hosted Gemini agent.<br>
                            Example: <code>https://woocommerce-production-18ad.up.railway.app</code>
                        </p>
                    </td>
                </tr>
                <tr>
                    <th scope="row">Enable Chatbot</th>
                    <td>
                        <label>
                            <input type="checkbox" name="woochat_enabled" value="1"
                                <?php checked( $enabled, '1' ); ?> />
                            Show chatbot widget on all storefront pages
                        </label>
                    </td>
                </tr>
            </table>

            <h2 class="title">Widget Appearance</h2>
            <table class="form-table" role="presentation">
                <tr>
                    <th scope="row"><label for="woochat_widget_title">Widget Title</label></th>
                    <td>
                        <input type="text" id="woochat_widget_title" name="woochat_widget_title"
                            value="<?php echo esc_attr( $widget_title ); ?>" class="regular-text" />
                        <p class="description">Shown in the chatbot header bar.</p>
                    </td>
                </tr>
                <tr>
                    <th scope="row"><label for="woochat_placeholder">Input Placeholder</label></th>
                    <td>
                        <input type="text" id="woochat_placeholder" name="woochat_placeholder"
                            value="<?php echo esc_attr( $placeholder ); ?>" class="regular-text" />
                    </td>
                </tr>
                <tr>
                    <th scope="row"><label for="woochat_welcome_msg">Welcome Message</label></th>
                    <td>
                        <input type="text" id="woochat_welcome_msg" name="woochat_welcome_msg"
                            value="<?php echo esc_attr( $welcome_msg ); ?>" class="regular-text" />
                        <p class="description">First message shown when the visitor opens the chat.</p>
                    </td>
                </tr>
                <tr>
                    <th scope="row"><label for="woochat_primary_color">Primary Color</label></th>
                    <td>
                        <input type="color" id="woochat_primary_color" name="woochat_primary_color"
                            value="<?php echo esc_attr( $primary_color ); ?>" />
                        <p class="description">Used for the chat header and send button.</p>
                    </td>
                </tr>
            </table>

            <?php submit_button( 'Save Settings' ); ?>
        </form>

        <!-- QUICK TEST PANEL -->
        <?php if ( ! empty( $agent_url ) && $connection_status === 'ok' ) : ?>
        <hr>
        <h2>Quick Test</h2>
        <p>Send a test message to your agent directly from here:</p>
        <div style="display:flex; gap:10px; align-items:center; max-width:600px;">
            <input type="text" id="woochat-test-input"
                placeholder="e.g. show me your products"
                class="regular-text" style="flex:1;" />
            <button class="button button-primary" id="woochat-test-btn">Send</button>
        </div>
        <div id="woochat-test-response"
             style="margin-top:10px; padding:10px; background:#f0f0f0; border-radius:4px; display:none; max-width:600px;"></div>
        <script>
        document.getElementById('woochat-test-btn').addEventListener('click', function() {
            var msg = document.getElementById('woochat-test-input').value.trim();
            if ( ! msg ) return;
            var resBox = document.getElementById('woochat-test-response');
            resBox.style.display = 'block';
            resBox.textContent   = 'Sending...';
            fetch('<?php echo admin_url( 'admin-ajax.php' ); ?>', {
                method:  'POST',
                headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
                body: new URLSearchParams({
                    action:  'woochat_message',
                    nonce:   '<?php echo wp_create_nonce( 'woochat_nonce' ); ?>',
                    message: msg
                })
            })
            .then( r => r.json() )
            .then( data => {
                resBox.textContent = data.success
                    ? data.data.response
                    : 'Error: ' + ( data.data || 'Unknown error' );
            })
            .catch( err => { resBox.textContent = 'Request failed: ' + err.message; });
        });
        </script>
        <?php endif; ?>

        <!-- SETUP CHECKLIST -->
        <hr>
        <h2>Setup Checklist</h2>
        <ul style="list-style:none; padding:0; line-height:2;">
            <li><?php echo class_exists( 'WooCommerce' ) ? '✅' : '❌'; ?> WooCommerce active</li>
            <li><?php echo ( defined( 'WC_VERSION' ) && version_compare( WC_VERSION, '6.9', '>=' ) ) ? '✅' : '❌'; ?> WooCommerce 6.9+</li>
            <li><?php echo get_option( 'permalink_structure' ) ? '✅' : '❌'; ?> Pretty permalinks enabled</li>
            <li><?php echo ! empty( $agent_url ) ? '✅' : '❌'; ?> Agent URL configured</li>
            <li><?php echo $connection_status === 'ok' ? '✅' : '❌'; ?> Agent reachable</li>
            <li><?php echo $enabled ? '✅' : '❌'; ?> Chatbot widget enabled</li>
        </ul>
    </div>
    <?php
}

// ─── Enqueue Widget Assets on Storefront ──────────────────────────────────────
add_action( 'wp_enqueue_scripts', 'woochat_enqueue_widget' );
function woochat_enqueue_widget() {
    if ( ! get_option( 'woochat_enabled' ) )    return;
    if ( ! get_option( 'woochat_agent_url' ) )  return;
    if ( is_admin() )                            return;

    wp_enqueue_style(
        'woochat-widget',
        WOOCHAT_PLUGIN_URL . 'assets/chatbot-widget.css',
        [],
        WOOCHAT_VERSION
    );

    wp_enqueue_script(
        'woochat-widget',
        WOOCHAT_PLUGIN_URL . 'assets/chatbot-widget.js',
        [],
        WOOCHAT_VERSION,
        true
    );

    $user      = wp_get_current_user();
    $is_logged = is_user_logged_in();

    wp_localize_script( 'woochat-widget', 'woochatConfig', [
        // AJAX proxy endpoint (same WordPress server — never exposes Railway URL to browser)
        'ajaxUrl'      => admin_url( 'admin-ajax.php' ),

        // Security nonces
        'nonce'        => wp_create_nonce( 'woochat_nonce' ),
        'wcNonce'      => wp_create_nonce( 'wc_store_api' ),

        // Visitor auth state
        'isLoggedIn'   => $is_logged,
        'userId'       => $is_logged ? $user->ID        : null,
        'username'     => $is_logged ? $user->display_name : null,
        'loginUrl'     => wp_login_url( get_permalink() ),

        // Store API base for direct cart calls from browser
        'storeUrl'     => get_site_url(),

        // Widget appearance
        'widgetTitle'  => get_option( 'woochat_widget_title',  'Store Assistant' ),
        'placeholder'  => get_option( 'woochat_placeholder',   'Ask me anything...' ),
        'welcomeMsg'   => get_option( 'woochat_welcome_msg',   'Hi! How can I help you today?' ),
        'primaryColor' => get_option( 'woochat_primary_color', '#2271b1' ),

        // Persistent session ID per visitor
        'sessionId'    => woochat_get_session_id(),
    ] );
}

// ─── Session ID Helper ────────────────────────────────────────────────────────
function woochat_get_session_id() {
    // Prefer WooCommerce session customer ID (stable across pages)
    if ( function_exists( 'WC' ) && WC()->session ) {
        return (string) WC()->session->get_customer_id();
    }
    // Fallback: UUID stored in a 30-day cookie
    if ( ! isset( $_COOKIE['woochat_session'] ) ) {
        $session_id = wp_generate_uuid4();
        setcookie(
            'woochat_session',
            $session_id,
            time() + DAY_IN_SECONDS * 30,
            COOKIEPATH,
            COOKIE_DOMAIN,
            is_ssl(),
            true
        );
        return $session_id;
    }
    return sanitize_text_field( $_COOKIE['woochat_session'] );
}

// ─── Admin Notice: Missing Agent URL ──────────────────────────────────────────
add_action( 'admin_notices', 'woochat_admin_notices' );
function woochat_admin_notices() {
    if ( ! current_user_can( 'manage_options' ) ) return;
    if ( ! empty( get_option( 'woochat_agent_url', '' ) ) ) return;

    $settings_url = admin_url( 'options-general.php?page=woo-chatbot' );
    echo '<div class="notice notice-warning is-dismissible">
        <p>
            <strong>WooCommerce AI Chatbot:</strong>
            Agent URL not configured.
            <a href="' . esc_url( $settings_url ) . '">Configure it here →</a>
        </p>
    </div>';
}

// ─── Plugin Action Links ───────────────────────────────────────────────────────
add_filter( 'plugin_action_links_' . plugin_basename( __FILE__ ), 'woochat_action_links' );
function woochat_action_links( $links ) {
    array_unshift(
        $links,
        '<a href="' . admin_url( 'options-general.php?page=woo-chatbot' ) . '">Settings</a>'
    );
    return $links;
}
