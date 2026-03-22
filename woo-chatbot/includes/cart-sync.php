<?php
/**
 * Session synchronization for WooCommerce AI Chatbot.
 * Restores items from a draft order (linked via meta) to the active browser session
 * whenever a user visits the checkout page.
 */

if ( ! defined( 'ABSPATH' ) ) exit;

add_action( 'template_redirect', 'woochat_sync_session_from_draft' );

/**
 * Restores the cart from a draft order if the woochat_session cookie is present.
 */
function woochat_sync_session_from_draft() {
    // Only target storefront pages (not admin/rest/ajax)
    if ( is_admin() || (defined('DOING_AJAX') && DOING_AJAX) || (defined('REST_REQUEST') && REST_REQUEST) ) {
        return;
    }

    // Identify the session from the cookie
    $session_id = woochat_get_session_id();
    if ( empty( $session_id ) ) {
        return;
    }

    // 1. Find the draft order for this session
    $args = [
        'status'     => 'pending',
        'limit'      => 1,
        'meta_key'   => '_woochat_session_id',
        'meta_value' => $session_id,
        'orderby'    => 'date',
        'order'      => 'DESC',
    ];

    $orders = wc_get_orders( $args );

    if ( empty( $orders ) ) {
        return;
    }

    $order = $orders[0];

    // 2. Clear current session cart
    if ( ! WC()->cart ) {
        wc_load_cart();
    }
    
    // Check if we already synced this specific VERSION of the order
    // Incorporating the modified timestamp ensures that if the chatbot changes
    // the order (even if the ID is the same), we trigger a re-sync.
    $modified_date = $order->get_date_modified();
    $sync_key = $order->get_id() . '_' . ($modified_date ? $modified_date->getTimestamp() : time());

    if ( WC()->cart->get_cart_contents_count() > 0 || WC()->session->get( 'woochat_synced_order_key' ) ) {
        if ( WC()->session->get( 'woochat_synced_order_key' ) === $sync_key ) {
            return;
        }
    }

    WC()->cart->empty_cart();

    // 3. Populate session cart from order items
    foreach ( $order->get_items() as $item ) {
        $product_id   = $item->get_product_id();
        $variation_id = (int) $item->get_variation_id();
        $quantity     = $item->get_quantity();
        
        $variation = [];
        if ( $variation_id > 0 ) {
            $variation_obj = wc_get_product( $variation_id );
            if ( $variation_obj ) {
                $variation = $variation_obj->get_variation_attributes();
            }
        }

        WC()->cart->add_to_cart( $product_id, $quantity, $variation_id, $variation );
    }

    // Mark this specific version as synced
    WC()->session->set( 'woochat_synced_order_key', $sync_key );
}
