<?php
/**
 * API Proxy — bridges the browser widget to the Railway FastAPI agent.
 *
 * Why a proxy?
 *   - The Railway URL never reaches the browser.
 *   - WordPress nonce validation happens here before anything is forwarded.
 *   - Auth state (is_logged_in, user_id) is determined server-side —
 *     the browser cannot spoof elevated permissions.
 *
 * AJAX hooks:
 *   wp_ajax_woochat_message        → logged-in WordPress users
 *   wp_ajax_nopriv_woochat_message → guests (not logged into WordPress)
 */

if ( ! defined( 'ABSPATH' ) ) exit;

// ─── Register AJAX handlers ────────────────────────────────────────────────────
add_action( 'wp_ajax_woochat_message',              'woochat_handle_message' );
add_action( 'wp_ajax_nopriv_woochat_message',       'woochat_handle_message' );
add_action( 'wp_ajax_woochat_clear_session',        'woochat_handle_clear_session' );
add_action( 'wp_ajax_nopriv_woochat_clear_session', 'woochat_handle_clear_session' );

/**
 * Main AJAX handler — validates, builds payload, proxies to Railway agent.
 */
function woochat_handle_message() {

    // ── 1. Verify nonce ────────────────────────────────────────────────────────
    $nonce = isset( $_POST['nonce'] ) ? sanitize_text_field( $_POST['nonce'] ) : '';
    if ( ! wp_verify_nonce( $nonce, 'woochat_nonce' ) ) {
        wp_send_json_error( 'Invalid or expired security token. Please refresh the page.', 403 );
        return;
    }

    // ── 2. Validate message ────────────────────────────────────────────────────
    $message = isset( $_POST['message'] ) ? sanitize_text_field( wp_unslash( $_POST['message'] ) ) : '';
    if ( empty( $message ) ) {
        wp_send_json_error( 'Message cannot be empty.', 400 );
        return;
    }
    if ( mb_strlen( $message ) > 500 ) {
        wp_send_json_error( 'Message too long. Please keep it under 500 characters.', 400 );
        return;
    }

    // ── 3. Get agent URL ───────────────────────────────────────────────────────
    $agent_url = get_option( 'woochat_agent_url', '' );
    if ( empty( $agent_url ) ) {
        wp_send_json_error( 'Chatbot is not configured. Please contact the store admin.', 503 );
        return;
    }

    // ── 4. Read per-store WooCommerce credentials from wp_options ──────────────
    $woo_url = get_option( 'woochat_woo_url',            '' );
    $woo_ck  = get_option( 'woochat_woo_consumer_key',   '' );
    $woo_cs  = get_option( 'woochat_woo_consumer_secret', '' );

    // ── 5. Build auth context server-side ─────────────────────────────────────
    //    is_logged_in and user_id are determined here — the browser cannot
    //    spoof these values since this runs on the WordPress server.
    $is_logged_in = is_user_logged_in();
    $user         = wp_get_current_user();

    $session_context = [
        'is_logged_in' => $is_logged_in,
        'session_id'   => isset( $_POST['session_id'] )
                            ? sanitize_text_field( $_POST['session_id'] )
                            : woochat_get_session_id(),
        'user_id'      => $is_logged_in ? (int) $user->ID : null,
        // wc_nonce forwarded from browser — used for Store API cart calls
        'wc_nonce'     => isset( $_POST['wc_nonce'] )
                            ? sanitize_text_field( $_POST['wc_nonce'] )
                            : '',
    ];

    // ── 6. Build payload ──────────────────────────────────────────────────────
    $payload = [
        'message'         => $message,
        'session_context' => $session_context,
    ];

    // ── 7. POST to Railway agent (with per-store credentials as headers) ───────
    $response = wp_remote_post(
        trailingslashit( $agent_url ) . 'chat',
        [
            'headers'     => [
                'Content-Type'              => 'application/json',
                'Accept'                    => 'application/json',
                // ✅ Multi-tenant: inject this store's WooCommerce credentials
                'X-WooChat-Store-URL'       => $woo_url,
                'X-WooChat-Consumer-Key'    => $woo_ck,
                'X-WooChat-Consumer-Secret' => $woo_cs,
            ],
            'body'        => wp_json_encode( $payload ),
            'timeout'     => 30,
            'data_format' => 'body',
            'sslverify'   => true,
        ]
    );

    // ── 7. Handle network errors ──────────────────────────────────────────────
    if ( is_wp_error( $response ) ) {
        error_log( '[WooChat] Agent request failed: ' . $response->get_error_message() );
        wp_send_json_error( 'Could not reach the assistant right now. Please try again shortly.', 503 );
        return;
    }

    $status_code = wp_remote_retrieve_response_code( $response );
    $body        = wp_remote_retrieve_body( $response );

    if ( $status_code !== 200 ) {
        error_log( '[WooChat] Agent returned HTTP ' . $status_code . ': ' . $body );
        wp_send_json_error( 'Assistant returned an unexpected error (HTTP ' . $status_code . '). Please try again.', 502 );
        return;
    }

    // ── 8. Parse agent response ───────────────────────────────────────────────
    $data = json_decode( $body, true );

    if ( json_last_error() !== JSON_ERROR_NONE || ! isset( $data['response'] ) ) {
        error_log( '[WooChat] Invalid JSON from agent: ' . $body );
        wp_send_json_error( 'Received an invalid response from the assistant.', 502 );
        return;
    }

    // ── 9. Return to browser ──────────────────────────────────────────────────
    wp_send_json_success( [
        'response'   => $data['response'],
        'session_id' => $session_context['session_id'],
        'action'     => isset( $data['action'] ) ? $data['action'] : null,
    ] );
}

/**
 * Clears the visitor session on the Railway agent.
 * Called when visitor logs out of WordPress.
 */
function woochat_handle_clear_session() {
    $nonce = isset( $_POST['nonce'] ) ? sanitize_text_field( $_POST['nonce'] ) : '';
    if ( ! wp_verify_nonce( $nonce, 'woochat_nonce' ) ) {
        wp_send_json_error( 'Invalid nonce.', 403 );
        return;
    }

    $agent_url  = get_option( 'woochat_agent_url', '' );
    $session_id = isset( $_POST['session_id'] ) ? sanitize_text_field( $_POST['session_id'] ) : '';

    if ( empty( $agent_url ) || empty( $session_id ) ) {
        wp_send_json_success( [ 'cleared' => false ] );
        return;
    }

    wp_remote_request(
        trailingslashit( $agent_url ) . 'session/' . urlencode( $session_id ),
        [
            'method'  => 'DELETE',
            'timeout' => 5,
        ]
    );

    wp_send_json_success( [ 'cleared' => true ] );
}

/**
 * Auto-clear agent session when visitor logs out of WordPress.
 * Non-blocking — does not delay the logout redirect.
 */
add_action( 'wp_logout', 'woochat_on_logout' );
function woochat_on_logout() {
    $agent_url  = get_option( 'woochat_agent_url', '' );
    $session_id = woochat_get_session_id();

    if ( empty( $agent_url ) || empty( $session_id ) ) return;

    wp_remote_request(
        trailingslashit( $agent_url ) . 'session/' . urlencode( $session_id ),
        [
            'method'   => 'DELETE',
            'timeout'  => 3,
            'blocking' => false, // fire and forget
        ]
    );
}
