<?php
/**
 * Custom REST API endpoints for WooCommerce AI Chatbot.
 * Provides a way for the Python agent to update the user's cart (draft order)
 * without direct dependency on the browser session for every call.
 */

if ( ! defined( 'ABSPATH' ) ) exit;

add_action( 'rest_api_init', function () {
    register_rest_route( 'woo-chatbot/v1', '/cart/add', [
        'methods'             => 'POST',
        'callback'            => 'woochat_rest_add_to_cart',
        'permission_callback' => '__return_true',
    ] );

    register_rest_route( 'woo-chatbot/v1', '/cart/get', [
        'methods'             => 'GET',
        'callback'            => 'woochat_rest_get_cart',
        'permission_callback' => '__return_true',
    ] );

    register_rest_route( 'woo-chatbot/v1', '/cart/remove', [
        'methods'             => 'POST',
        'callback'            => 'woochat_rest_remove_from_cart',
        'permission_callback' => '__return_true',
    ] );
} );

/**
 * REST Callback: Adds a product to a persistent draft order for a session.
 */
function woochat_rest_add_to_cart( $request ) {
    $params     = $request->get_json_params();
    $session_id = isset( $params['session_id'] ) ? sanitize_text_field( $params['session_id'] ) : '';
    $product_id = isset( $params['product_id'] ) ? (int) $params['product_id'] : 0;
    $quantity   = isset( $params['quantity'] )   ? (int) $params['quantity']   : 1;

    if ( empty( $session_id ) || ! $product_id ) {
        return new WP_Error( 'missing_params', 'Session ID and Product ID are required.', [ 'status' => 400 ] );
    }

    // 1. Get or create the draft order
    $order = woochat_get_or_create_draft_order( $session_id );
    if ( is_wp_error( $order ) ) {
        return $order;
    }

    // 2. Add/Update item in the order
    $found = false;
    foreach ( $order->get_items() as $item_id => $item ) {
        // If the ID matches either the parent_id or variation_id, we count it as a match
        $item_product_id   = (int) $item->get_product_id();
        $item_variation_id = (int) $item->get_variation_id();
        
        if ( $item_product_id === $product_id || $item_variation_id === $product_id ) {
            $item->set_quantity( $item->get_quantity() + $quantity );
            $item->save();
            $found = true;
            break;
        }
    }

    if ( ! $found ) {
        $order->add_product( wc_get_product( $product_id ), $quantity );
    }

    $order->calculate_totals();
    $order->save();

    return rest_ensure_response( [
        'success'      => true,
        'order_id'     => $order->get_id(),
        'item_count'   => $order->get_item_count(),
        'total'        => $order->get_total(),
        'checkout_url' => wc_get_checkout_url(),
    ] );
}

/**
 * REST Callback: Retrieves the draft order ID for a session.
 */
function woochat_rest_get_cart( $request ) {
    $session_id = sanitize_text_field( $request->get_param( 'session_id' ) );
    if ( empty( $session_id ) ) {
        return new WP_Error( 'missing_session', 'Session ID is required.', [ 'status' => 400 ] );
    }

    $order = woochat_get_or_create_draft_order( $session_id );
    if ( is_wp_error( $order ) ) {
        return $order;
    }

    return rest_ensure_response( [
        'success'      => true,
        'order_id'     => $order->get_id(),
        'checkout_url' => wc_get_checkout_url(),
    ] );
}

/**
 * REST Callback: Removes a product from the draft order.
 */
function woochat_rest_remove_from_cart( $request ) {
    $params     = $request->get_json_params();
    $session_id = isset( $params['session_id'] ) ? sanitize_text_field( $params['session_id'] ) : '';
    $product_id = isset( $params['product_id'] ) ? (int) $params['product_id'] : 0;
    
    if ( empty( $session_id ) || ! $product_id ) {
        return new WP_Error( 'missing_params', 'Session ID and Product ID are required.', [ 'status' => 400 ] );
    }

    $order = woochat_get_or_create_draft_order( $session_id );
    if ( is_wp_error( $order ) ) {
        return $order;
    }

    foreach ( $order->get_items() as $item_id => $item ) {
        if ( (int) $item->get_product_id() === $product_id ) {
            $order->remove_item( $item_id );
            break;
        }
    }

    $order->calculate_totals();
    $order->save();

    return rest_ensure_response( [
        'success'  => true,
        'order_id' => $order->get_id(),
        'total'    => $order->get_total(),
    ] );
}

/**
 * Helper: Finds a draft order for a session or creates a new one.
 */
function woochat_get_or_create_draft_order( $session_id ) {
    $args = [
        'status'     => 'pending', // We use pending as the draft state
        'limit'      => 1,
        'meta_key'   => '_woochat_session_id',
        'meta_value' => $session_id,
        'orderby'    => 'date',
        'order'      => 'DESC',
    ];

    $orders = wc_get_orders( $args );

    if ( ! empty( $orders ) ) {
        return $orders[0];
    }

    // Create new order
    $order = wc_create_order( [
        'status'      => 'pending',
        'customer_id' => 0, // Guest initially
    ] );

    if ( is_wp_error( $order ) ) {
        return $order;
    }

    $order->update_meta_data( '_woochat_session_id', $session_id );
    $order->save();

    return $order;
}
