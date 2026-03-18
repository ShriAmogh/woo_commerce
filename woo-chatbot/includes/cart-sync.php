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
    // Only target checkout and cart pages for restoration
    if ( ! is_checkout() && ! is_cart() ) {
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
    
    // Check if we already synced (avoid infinite loop or redundant work)
    if ( WC()->cart->get_cart_contents_count() > 0 ) {
        // Optional: Compare contents or check a session flag
        if ( WC()->session->get( 'woochat_synced_order' ) === $order->get_id() ) {
            return;
        }
    }

    WC()->cart->empty_cart();

    // 3. Populate session cart from order items
    foreach ( $order->get_items() as $item ) {
        $product_id   = $item->get_product_id();   // Parent ID for variations
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

    // Mark as synced to prevent re-syncing until the order changes
    WC()->session->set( 'woochat_synced_order', $order->get_id() );
}
