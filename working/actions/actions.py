import os
import requests
import logging
import re
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv
from . import actions_db

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Global user context for multi-user support
_user_context = None

# Session Cart Mapping (session_id -> order_id)
_session_orders = {}

# ─────────────────────────────────────────────────────────────────────────────
# WooCommerce HTTP helpers — replaces woocommerce.API entirely
# Passes consumer keys as query params + Basic Auth for Live Link tunnel
# ─────────────────────────────────────────────────────────────────────────────

def _get_woo_config():
    """Returns (base_url, consumer_key, consumer_secret, auth)"""
    global _user_context
    if _user_context:
        url = _user_context["url"]
        key = _user_context["consumer_key"]
        secret = _user_context["consumer_secret"]
    else:
        url    = os.getenv("WOO_URL", "http://woo-test.local")
        key    = os.getenv("WOO_CONSUMER_KEY")
        secret = os.getenv("WOO_CONSUMER_SECRET")

    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    live_user = os.getenv("WOO_LIVE_LINK_USER", "")
    live_pass = os.getenv("WOO_LIVE_LINK_PASS", "")
    auth = HTTPBasicAuth(live_user, live_pass) if live_user else None

    return url.rstrip('/'), key, secret, auth


def woo_get(endpoint, params=None):
    base_url, key, secret, auth = _get_woo_config()
    url = f"{base_url}/wp-json/wc/v3/{endpoint}"
    all_params = {"consumer_key": key, "consumer_secret": secret}
    if params:
        all_params.update(params)
    return requests.get(url, params=all_params, auth=auth, verify=False, timeout=15)


def woo_post(endpoint, data=None):
    base_url, key, secret, auth = _get_woo_config()
    url = f"{base_url}/wp-json/wc/v3/{endpoint}"
    params = {"consumer_key": key, "consumer_secret": secret}
    return requests.post(url, params=params, json=data or {}, auth=auth, verify=False, timeout=15)


def woo_put(endpoint, data=None):
    base_url, key, secret, auth = _get_woo_config()
    url = f"{base_url}/wp-json/wc/v3/{endpoint}"
    params = {"consumer_key": key, "consumer_secret": secret}
    return requests.put(url, params=params, json=data or {}, auth=auth, verify=False, timeout=15)


def woo_delete(endpoint, params=None):
    base_url, key, secret, auth = _get_woo_config()
    url = f"{base_url}/wp-json/wc/v3/{endpoint}"
    all_params = {"consumer_key": key, "consumer_secret": secret, "force": True}
    if params:
        all_params.update(params)
    return requests.delete(url, params=all_params, auth=auth, verify=False, timeout=15)


# ─────────────────────────────────────────────────────────────────────────────
# Context helpers
# ─────────────────────────────────────────────────────────────────────────────

def set_user_context(url: str, consumer_key: str, consumer_secret: str):
    global _user_context
    _user_context = {"url": url, "consumer_key": consumer_key, "consumer_secret": consumer_secret}

def clear_user_context():
    global _user_context
    _user_context = None


# ─────────────────────────────────────────────────────────────────────────────
# Cart helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_cart_id(session_id: str = "default"):
    global _session_orders
    if session_id not in _session_orders:
        logging.info(f"Creating new cart (order) for session {session_id}...")
        response = woo_post("orders", {"status": "pending"})
        if response.status_code == 201:
            _session_orders[session_id] = response.json().get("id")
            logging.info(f"Created cart ID: {_session_orders[session_id]}")
        else:
            logging.error(f"Error creating cart: {response.text}")
    return _session_orders.get(session_id)


# ─────────────────────────────────────────────────────────────────────────────
# Product tools
# ─────────────────────────────────────────────────────────────────────────────

def list_products(min_price=None, max_price=None, category_id=None):
    """Retrieves products, optionally filtered by price range or category."""
    if category_id and isinstance(category_id, str) and not str(category_id).isdigit():
        logging.info(f"Resolving category name '{category_id}' to ID...")
        categories = list_categories()
        if isinstance(categories, list):
            for cat in categories:
                if cat.get("name", "").lower() == category_id.lower() \
                        or cat.get("slug", "").lower() == category_id.lower():
                    category_id = str(cat["id"])
                    break

    logging.info(f"Fetching products (min:{min_price} max:{max_price} cat:{category_id})...")
    params = {}
    if min_price:    params["min_price"] = min_price
    if max_price:    params["max_price"] = max_price
    if category_id:  params["category"]  = category_id

    try:
        response = woo_get("products", params)
        if response.status_code == 200:
            out = []
            for p in response.json():
                desc = p.get('short_description') or p.get('description', '')
                desc = re.sub('<[^<]+?>', '', desc)
                out.append({
                    'id':            p.get('id'),
                    'name':          p.get('name'),
                    'price':         p.get('price'),
                    'regular_price': p.get('regular_price'),
                    'sale_price':    p.get('sale_price'),
                    'stock_status':  p.get('stock_status'),
                    'stock_quantity':p.get('stock_quantity'),
                    'permalink':     p.get('permalink'),
                    'categories':    [c.get('name') for c in p.get('categories', [])],
                    'sku':           p.get('sku'),
                    'images':        [i.get('src') for i in p.get('images', [])],
                    'description':   desc[:200] + '...' if len(desc) > 200 else desc,
                })
            return out
        logging.error(f"list_products error: {response.status_code} {response.text[:200]}")
        return {"error": response.text}
    except Exception as e:
        logging.error(f"Exception in list_products: {e}")
        return {"error": str(e)}


def search_products(query: str):
    """Searches products by keyword."""
    logging.info(f"Searching products: {query}")
    try:
        response = woo_get("products", {"search": query})
        if response.status_code == 200:
            out = []
            for p in response.json():
                desc = p.get('short_description') or p.get('description', '')
                desc = re.sub('<[^<]+?>', '', desc)
                out.append({
                    'id':            p.get('id'),
                    'name':          p.get('name'),
                    'regular_price': p.get('regular_price'),
                    'sale_price':    p.get('sale_price'),
                    'stock_status':  p.get('stock_status'),
                    'stock_quantity':p.get('stock_quantity'),
                    'permalink':     p.get('permalink'),
                    'sku':           p.get('sku'),
                    'images':        [i.get('src') for i in p.get('images', [])],
                    'description':   desc[:200] + '...' if len(desc) > 200 else desc,
                })
            return out
        logging.error(f"search_products error: {response.status_code} {response.text[:200]}")
        return {"error": response.text}
    except Exception as e:
        logging.error(f"Exception in search_products: {e}")
        return {"error": str(e)}


def product_exists(product_id):
    try:
        return woo_get(f"products/{product_id}").status_code == 200
    except:
        return False


def resolve_product_id(query):
    """Resolves product name/query to numeric ID. Tries vector search first."""
    if not query:
        return None

    # 1. Vector search
    try:
        logging.info(f"Resolving '{query}' via vector search...")
        result = actions_db.get_product_details_vector(str(query))
        if isinstance(result, dict) and "id" in result:
            logging.info(f"Resolved '{query}' → ID {result['id']}")
            return result['id']
    except Exception as e:
        logging.warning(f"Vector resolution failed for '{query}': {e}")

    # 2. Numeric ID check
    try:
        if str(query).isdigit():
            p_id = int(query)
            if product_exists(p_id):
                return p_id
    except:
        pass

    # 3. WooCommerce keyword search fallback
    results = search_products(str(query))
    if isinstance(results, list) and results:
        logging.info(f"Resolved '{query}' via search → ID {results[0].get('id')}")
        return results[0].get('id')

    return None


def get_product_details(product_id_or_name):
    """Gets full product details by ID or name."""
    product_id = resolve_product_id(product_id_or_name)
    if not product_id:
        return {"error": f"Could not find product: {product_id_or_name}"}
    logging.info(f"Fetching details for product ID: {product_id}")
    try:
        response = woo_get(f"products/{product_id}")
        if response.status_code == 200:
            p = response.json()
            return {
                'id':                p.get('id'),
                'name':              p.get('name'),
                'price':             p.get('price'),
                'regular_price':     p.get('regular_price'),
                'sale_price':        p.get('sale_price'),
                'stock_status':      p.get('stock_status'),
                'stock_quantity':    p.get('stock_quantity'),
                'description':       p.get('description'),
                'short_description': p.get('short_description'),
                'permalink':         p.get('permalink'),
                'sku':               p.get('sku'),
                'categories':        [c.get('name') for c in p.get('categories', [])],
                'attributes':        p.get('attributes', []),
                'images':            [i.get('src') for i in p.get('images', [])],
            }
        logging.error(f"get_product_details error: {response.status_code} {response.text[:200]}")
        return {"error": response.text}
    except Exception as e:
        logging.error(f"Exception in get_product_details: {e}")
        return {"error": str(e)}


def list_categories():
    """Retrieves all product categories."""
    logging.info("Fetching categories...")
    try:
        response = woo_get("products/categories")
        if response.status_code == 200:
            return [{"id": c.get("id"), "name": c.get("name"), "slug": c.get("slug")}
                    for c in response.json()]
        return {"error": response.text}
    except Exception as e:
        return {"error": str(e)}


def list_brands():
    """Retrieves all product brands."""
    logging.info("Fetching brands...")
    try:
        response = woo_get("products/brands")
        if response.status_code == 200:
            return [{"id": b.get("id"), "name": b.get("name"), "slug": b.get("slug")}
                    for b in response.json()]
        return {"error": response.text}
    except Exception as e:
        return {"error": str(e)}


def get_products_by_brand(brand_slug: str):
    """Retrieves products filtered by brand via Vector DB."""
    logging.info(f"Fetching products for brand: {brand_slug}")
    try:
        return actions_db.search_products_by_brand(brand_slug, query="", top_k=20)
    except Exception as e:
        return {"error": str(e)}


def get_product_variations(product_id_or_name):
    """Retrieves all variations for a variable product."""
    product_id = resolve_product_id(product_id_or_name)
    if not product_id:
        return {"error": f"Could not find product: {product_id_or_name}"}
    logging.info(f"Fetching variations for product ID: {product_id}")
    try:
        response = woo_get(f"products/{product_id}/variations")
        if response.status_code == 200:
            return response.json()
        return {"error": response.text}
    except Exception as e:
        return {"error": str(e)}


def check_stock_status(product_id_or_name):
    """Checks stock status for a product."""
    product_id = resolve_product_id(product_id_or_name)
    if not product_id:
        return {"error": f"Could not find product: {product_id_or_name}"}
    logging.info(f"Checking stock for product ID: {product_id}")
    product = get_product_details(product_id)
    if "error" in product:
        return product
    return {
        "name":           product.get("name"),
        "price":          product.get("price"),
        "sku":            product.get("sku"),
        "stock_status":   product.get("stock_status"),
        "stock_quantity": product.get("stock_quantity"),
        "manage_stock":   product.get("manage_stock"),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Order helpers
# ─────────────────────────────────────────────────────────────────────────────

def get_order(order_id: int):
    logging.info(f"Fetching order ID: {order_id}")
    try:
        response = woo_get(f"orders/{order_id}")
        if response.status_code == 200:
            o = response.json()
            return {
                "id":           o.get("id"),
                "status":       o.get("status"),
                "total":        o.get("total"),
                "date_created": o.get("date_created"),
                "Currency":     o.get("currency"),
                "checkout_url": o.get("payment_url"),
                "line_items": [
                    {
                        "line_id":    item.get("id"),
                        "name":       item.get("name"),
                        "product_id": item.get("product_id"),
                        "price":      item.get("price"),
                        "quantity":   item.get("quantity"),
                        "total":      item.get("total"),
                        "images":     [{"src": item.get("image", {}).get("src")}] if item.get("image") else []
                    } for item in o.get("line_items", [])
                ],
                "billing":  o.get("billing"),
                "shipping": o.get("shipping"),
            }
        return {"error": response.text}
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Cart tools
# ─────────────────────────────────────────────────────────────────────────────

def view_cart(session_id: str = "default"):
    """Shows current cart contents."""
    logging.info(f"Viewing cart for session {session_id}")
    order_id = get_cart_id(session_id)
    if not order_id:
        return {"error": "No active cart found."}
    return get_order(order_id)


def add_to_cart(product_id, quantity: int = 1, session_id: str = "default"):
    """Adds a product to cart. Validates stock first."""
    resolved_id = resolve_product_id(product_id)
    if not resolved_id:
        return {"error": f"Could not find product: {product_id}"}
    product_id = resolved_id

    logging.info(f"Adding product {product_id} (qty {quantity}) to cart for session {session_id}...")

    # Stock validation
    stock_info = check_stock_status(product_id)
    if "error" in stock_info:
        return {"error": f"Could not verify stock: {stock_info['error']}"}
    if stock_info.get("stock_status") != "instock":
        return {"error": f"'{stock_info.get('name')}' is out of stock."}
    if stock_info.get("manage_stock") and stock_info.get("stock_quantity") is not None:
        if stock_info.get("stock_quantity") < quantity:
            return {"error": f"Only {stock_info.get('stock_quantity')} units available."}

    order_id = get_cart_id(session_id)
    if not order_id:
        return {"error": "Failed to retrieve or create cart."}

    order = get_order(order_id)
    if "error" in order:
        return order

    line_items = order.get("line_items", [])
    update_lines = []
    found = False

    for item in line_items:
        if str(item.get("product_id")) == str(product_id):
            update_lines.append({"id": item["line_id"], "quantity": int(item["quantity"]) + int(quantity)})
            found = True
        else:
            update_lines.append({"id": item["line_id"], "quantity": item["quantity"]})

    if not found:
        update_lines.append({"product_id": product_id, "quantity": quantity})

    response = woo_put(f"orders/{order_id}", {"line_items": update_lines})
    if response.status_code == 200:
        o = response.json()
        base_url = _get_woo_config()[0]
        return {
            "Currency":     o.get("currency"),
            "checkout_url": f"{base_url}/checkout/",   # real checkout page
            "line_items": [
                {
                    "line_id":    item.get("id"),
                    "name":       item.get("name"),
                    "product_id": item.get("product_id"),
                    "price":      item.get("price"),
                    "quantity":   item.get("quantity"),
                    "total":      item.get("total"),
                    "images":     [{"src": item.get("image", {}).get("src")}] if item.get("image") else []
                } for item in o.get("line_items", [])
            ]
        }
    logging.error(f"Failed to add to cart: {response.text}")
    return {"error": response.text}


def remove_from_cart(product_id, quantity: int = -1, session_id: str = "default"):
    """Removes a product from cart."""
    resolved_id = resolve_product_id(product_id)
    if not resolved_id:
        return {"error": f"Could not find product: {product_id}"}
    product_id = resolved_id

    logging.info(f"Removing product {product_id} from cart for session {session_id}...")
    order_id = get_cart_id(session_id)
    if not order_id:
        return {"error": "No active cart found."}

    order = get_order(order_id)
    if "error" in order:
        return order

    update_lines = []
    for item in order.get("line_items", []):
        if str(item.get("product_id")) == str(product_id):
            new_qty = max(0, int(item["quantity"]) - int(quantity)) if quantity != -1 else 0
            update_lines.append({"id": item["line_id"], "quantity": new_qty})
        else:
            update_lines.append({"id": item["line_id"], "quantity": item["quantity"]})

    response = woo_put(f"orders/{order_id}", {"line_items": update_lines})
    if response.status_code == 200:
        o = response.json()
        base_url = _get_woo_config()[0]
        return {
            "Currency":     o.get("currency"),
            "checkout_url": f"{base_url}/checkout/",   # real checkout page
            "line_items": [
                {
                    "line_id":    item.get("id"),
                    "name":       item.get("name"),
                    "product_id": item.get("product_id"),
                    "price":      item.get("price"),
                    "quantity":   item.get("quantity"),
                    "total":      item.get("total"),
                } for item in o.get("line_items", [])
            ]
        }
    logging.error(f"Failed to remove from cart: {response.text}")
    return {"error": response.text}


def apply_coupon(coupon_code: str, session_id: str = "default"):
    """Applies a coupon to the cart."""
    logging.info(f"Applying coupon {coupon_code} for session {session_id}...")
    order_id = get_cart_id(session_id)
    if not order_id:
        return {"error": "No active cart found."}

    response = woo_put(f"orders/{order_id}", {"coupon_lines": [{"code": coupon_code}]})
    if response.status_code == 200:
        o = response.json()
        base_url = _get_woo_config()[0]
        return {
            "Currency":     o.get("currency"),
            "checkout_url": f"{base_url}/checkout/",   # real checkout page
            "coupon_lines": o.get("coupon_lines", []),
            "total":        o.get("total"),
        }
    logging.error(f"Failed to apply coupon: {response.text}")
    return {"error": response.text}


def get_store_info():
    """Retrieves general store information."""
    logging.info("Fetching store info...")
    try:
        base_url, _, _, auth = _get_woo_config()
        response = requests.get(
            f"{base_url}/wp-json",
            auth=auth,
            verify=False,
            timeout=10
        )
        if response.status_code == 200:
            data = response.json()
            return {
                "name":        data.get("name"),
                "description": data.get("description"),
                "url":         data.get("url"),
                "home":        data.get("home"),
                "currency":    "INR",
            }
        return {"error": f"Failed to fetch store info: {response.status_code}"}
    except Exception as e:
        logging.error(f"Error in get_store_info: {e}")
        return {"error": str(e)}


def update_order(order_id: int, data: dict):
    try:
        response = woo_put(f"orders/{order_id}", data)
        return response.json() if response.status_code == 200 else {"error": response.text}
    except Exception as e:
        return {"error": str(e)}


def delete_order(order_id: int):
    try:
        response = woo_delete(f"orders/{order_id}")
        return response.json() if response.status_code == 200 else {"error": response.text}
    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Tool registry
# ─────────────────────────────────────────────────────────────────────────────
tools = [
    list_products,
    search_products,
    get_product_details,
    list_categories,
    get_product_variations,
    check_stock_status,
    add_to_cart,
    view_cart,
    remove_from_cart,
    apply_coupon,
    get_store_info,
    list_brands,
    get_products_by_brand,
]