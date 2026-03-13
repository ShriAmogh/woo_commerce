import os
import requests
import logging
import json
import re
from woocommerce import API
from dotenv import load_dotenv
from . import actions_db

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Global user context for multi-user support
_user_context = None

# Session Cart Mapping (session_id -> order_id)
_session_orders = {}

def get_cart_id(session_id: str = "default"):
    """Gets the active order ID for the session or creates a new pending order silently."""
    global _session_orders
    if session_id not in _session_orders:
        wcapi = get_wcapi()
        logging.info(f"Silently creating a new cart (order) for session {session_id}...")
        response = wcapi.post("orders", {"status": "pending"})
        if response.status_code == 201:
            _session_orders[session_id] = response.json().get("id")
            logging.info(f"Created new cart with ID: {_session_orders[session_id]} for session {session_id}")
        else:
            logging.error(f"Error creating cart: {response.text}")
    return _session_orders.get(session_id)

def set_user_context(url: str, consumer_key: str, consumer_secret: str):
    """Sets the store credentials for the current session."""
    global _user_context
    _user_context = {
        "url": url,
        "consumer_key": consumer_key,
        "consumer_secret": consumer_secret
    }

def clear_user_context():
    """Clears the session-specific credentials."""
    global _user_context
    _user_context = None

def get_wcapi():
    """Initialize and return the WooCommerce API client using context or env vars."""
    global _user_context
    
    if _user_context:
        url = _user_context["url"]
        consumer_key = _user_context["consumer_key"]
        consumer_secret = _user_context["consumer_secret"]
    else:
        url = os.getenv("WOO_URL", "http://woo-test.local")
        consumer_key = os.getenv("WOO_CONSUMER_KEY")
        consumer_secret = os.getenv("WOO_CONSUMER_SECRET")

    if not url.startswith(("http://", "https://")):
        url = f"https://{url}"

    # Live Link Basic Auth (only needed when using localsite.io tunnel)
    live_user = os.getenv("WOO_LIVE_LINK_USER", "")
    live_pass = os.getenv("WOO_LIVE_LINK_PASS", "")

    return API(
        url=url,
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        wp_api=True,
        version="wc/v3",
        timeout=15,
        verify_ssl=False,
        auth=(live_user, live_pass) if live_user else None
    )

def list_products(min_price: str = None, max_price: str = None, category_id: str = None):
    """
    Retrieves products from the store, optionally filtered by price range or category.
    """
    # Resolve category name to ID if needed
    if category_id and isinstance(category_id, str) and not category_id.isdigit():
        logging.info(f"Attempting to resolve category name '{category_id}' to an ID...")
        categories = list_categories()
        if isinstance(categories, list):
            for cat in categories:
                if cat.get("name", "").lower() == category_id.lower() or cat.get("slug", "").lower() == category_id.lower():
                    category_id = str(cat["id"])
                    break

    logging.info(f"Fetching products (min: {min_price}, max: {max_price}, cat: {category_id})...")
    wcapi = get_wcapi()
    params = {}
    if min_price: params["min_price"] = min_price
    if max_price: params["max_price"] = max_price
    if category_id: params["category"] = category_id
    
    try:
        response = wcapi.get("products", params=params)
        if response.status_code == 200:
            optimized_products = []
            for product in response.json():
                product_info = {
                    'name': product.get('name'),
                    'id': product.get('id'),
                    'price': product.get('price'),
                    'regular_price': product.get('regular_price'),
                    'sale_price': product.get('sale_price'),
                    'stock_status': product.get('stock_status'),
                    'stock_quantity': product.get('stock_quantity'),
                    'permalink': product.get('permalink'),
                    'categories': [cat.get('name') for cat in product.get('categories', [])],
                    'sku': product.get('sku'),
                    'images': [img.get('src') for img in product.get('images', [])]
                }
                # Use short description if available, otherwise strip tags from description
                desc = product.get('short_description') or product.get('description', '')
                product_info['description'] = desc[:200] + '...' if len(desc) > 200 else desc
                
                optimized_products.append(product_info)
            return optimized_products
        else:
            logging.error(f"Error fetching products: {response.text}")
            return {"error": response.text}
    except Exception as e:
        logging.error(f"Exception in list_products: {e}")
        return {"error": str(e)}


def search_products(query: str):
    """Searches for products with an enriched, optimized output for better summaries."""
    logging.info(f"Searching for products with query: {query}")
    wcapi = get_wcapi()
    try:
        response = wcapi.get("products", params={"search": query})
        if response.status_code == 200:
            optimized_products = []
            for p in response.json():
                product_info = {
                    'name': p.get('name'),
                    'id': p.get('id'),
                    #'price': p.get('price'),
                    'regular_price': p.get('regular_price'),
                    'sale_price': p.get('sale_price'),
                    'stock_status': p.get('stock_status'),
                    'stock_quantity': p.get('stock_quantity'),
                    'permalink': p.get('permalink'),
                    'sku': p.get('sku'),
                    'images': [img.get('src') for img in p.get('images', [])]
                }
                # Include a snippet of the description for context
                desc = p.get('short_description') or p.get('description', '')
                # Strip HTML tags for cleaner summary
                clean_desc = re.sub('<[^<]+?>', '', desc)
                product_info['description'] = clean_desc[:200] + '...' if len(clean_desc) > 200 else clean_desc
                optimized_products.append(product_info)
            return optimized_products
        else:
            logging.error(f"Error searching products: {response.text}")
            return {"error": response.text}
    except Exception as e:
        logging.error(f"Exception in search_products: {e}")
        return {"error": str(e)}

def product_exists(product_id):
    """Checks if a product ID actually exists in the store."""
    wcapi = get_wcapi()
    try:
        response = wcapi.get(f"products/{product_id}")
        return response.status_code == 200
    except:
        return False

def resolve_product_id(query):
    """Helper to resolve a product name/query to a numeric ID. Prioritizes vector search for semantic accuracy."""
    if not query: return None
    
    # 1. Use Vector Search for Semantic Resolution (handles variations accurately)
    try:
        logging.info(f"Resolving '{query}' via vector search...")
        # get_product_details_vector handles both numeric IDs and names semantically
        result = actions_db.get_product_details_vector(str(query))
        if isinstance(result, dict) and "id" in result:
            logging.info(f"Resolved '{query}' to ID: {result['id']}")
            return result['id']
    except Exception as e:
        logging.warning(f"Vector resolution failed for '{query}': {e}")

    # 2. Fallback to exact numeric ID check (if it's already an ID)
    try:
        if str(query).isdigit():
            p_id = int(query)
            if product_exists(p_id):
                logging.info(f"Verified numeric ID: {p_id} exists.")
                return p_id
    except:
        pass
    
    # 3. Last resort: standard WooCommerce search
    results = search_products(str(query))
    if isinstance(results, list) and len(results) > 0:
        logging.info(f"Resolved '{query}' via standard search to ID: {results[0].get('id')}")
        return results[0].get('id')
    
    return None

def get_product_details(product_id_or_name):
    """Gets detailed information for a specific product by ID or Name."""
    product_id = resolve_product_id(product_id_or_name)
    if not product_id:
        return {"error": f"Could not find product: {product_id_or_name}"}
    logging.info(f"Fetching details for product ID: {product_id}")
    wcapi = get_wcapi()
    try:
        response = wcapi.get(f"products/{product_id}")
        if response.status_code == 200:
            product = response.json()
            return {
                'name': product.get('name'),
                'id': product.get('id'),
                'price': product.get('price'),
                'regular_price': product.get('regular_price'),
                'sale_price': product.get('sale_price'),
                'stock_status': product.get('stock_status'),
                'stock_quantity': product.get('stock_quantity'),
                'description': product.get('description'),
                'short_description': product.get('short_description'),
                'permalink': product.get('permalink'),
                'sku': product.get('sku'),
                'categories': [cat.get('name') for cat in product.get('categories', [])],
                'attributes': product.get('attributes', []),
                'images': [img.get('src') for img in product.get('images', [])]
            }
        else:
            logging.error(f"Error fetching product {product_id}: {response.text}")
            return {"error": response.text}
    except Exception as e:
        logging.error(f"Exception in get_product_details: {e}")
        return {"error": str(e)}

def list_categories():
    """Retrieves all product categories."""
    logging.info("Fetching product categories...")
    wcapi = get_wcapi()
    try:
        response = wcapi.get("products/categories")
        if response.status_code == 200:
            return [{"id": cat.get("id"), "name": cat.get("name"), "slug": cat.get("slug")} for cat in response.json()]
        else:
            logging.error(f"Error fetching categories: {response.text}")
            return {"error": response.text}
    except Exception as e:
        logging.error(f"Exception in list_categories: {e}")
        return {"error": str(e)}

def list_brands():
    """Retrieves all product brands from the custom taxonomy."""
    logging.info("Fetching product brands...")
    wcapi = get_wcapi()
    try:
        response = wcapi.get("products/brands")
        if response.status_code == 200:
            return [{"id": b.get("id"), "name": b.get("name"), "slug": b.get("slug")} for b in response.json()]
        else:
            logging.error(f"Error fetching brands: {response.text}")
            return {"error": response.text}
    except Exception as e:
        logging.error(f"Exception in list_brands: {e}")
        return {"error": str(e)}

def get_products_by_brand(brand_slug: str):
    """Retrieves products filtered by brand slug using Vector DB for reliability."""
    logging.info(f"Fetching products for brand: {brand_slug} via Vector DB")
    try:
        # We use the vector DB because standard REST filtering for custom taxonomies can be inconsistent
        results = actions_db.search_products_by_brand(brand_slug, query="", top_k=20)
        return results
    except Exception as e:
        logging.error(f"Error in get_products_by_brand: {e}")
        return {"error": str(e)}

def get_product_variations(product_id_or_name):
    """Retrieves all variations for a specific variable product ID or Name."""
    product_id = resolve_product_id(product_id_or_name)
    if not product_id:
        return {"error": f"Could not find product: {product_id_or_name}"}
    logging.info(f"Fetching variations for product ID: {product_id}")
    wcapi = get_wcapi()
    try:
        response = wcapi.get(f"products/{product_id}/variations")
        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"Error fetching variations for product {product_id}: {response.text}")
            return {"error": response.text}
    except Exception as e:
        logging.error(f"Exception in get_product_variations: {e}")
        return {"error": str(e)}

def check_stock_status(product_id_or_name):
    """Checks the stock status and quantity for a specific product ID or Name."""
    product_id = resolve_product_id(product_id_or_name)
    if not product_id:
        return {"error": f"Could not find product: {product_id_or_name}"}
    logging.info(f"Checking stock for product ID: {product_id}")
    product = get_product_details(product_id)
    if "error" in product:
        return product
    
    return {
        "name": product.get("name"),
        "price": product.get("price"),
        "sku": product.get("sku"),
        "stock_status": product.get("stock_status"),
        "stock_quantity": product.get("stock_quantity"),
        "manage_stock": product.get("manage_stock")
    }

# def list_orders():
#     """Retrieves all orders from the store with minimal fields."""
#     logging.info("Fetching all orders...")
#     wcapi = get_wcapi()
#     try:
#         response = wcapi.get("orders")
#         if response.status_code == 200:
#             return [{
#                 "id": o.get("id"),
#                 "status": o.get("status"),
#                 "total": o.get("total"),
#                 "date_created": o.get("date_created"),
#                 "customer": o.get("billing", {}).get("first_name", "") + " " + o.get("billing", {}).get("last_name", "")
#             } for o in response.json()]
#         else:
#             logging.error(f"Error fetching orders: {response.text}")
#             return {"error": response.text}
#     except Exception as e:
#         logging.error(f"Exception in list_orders: {e}")
#         return {"error": str(e)}

def get_order(order_id: int):
    """Retrieves details of a specific order by ID."""
    logging.info(f"Fetching details for order ID: {order_id}")
    wcapi = get_wcapi()
    try:
        response = wcapi.get(f"orders/{order_id}")
        if response.status_code == 200:
            o = response.json()
            return {
                "id": o.get("id"),
                "status": o.get("status"),
                "total": o.get("total"),
                "date_created": o.get("date_created"),
                "Currency": o.get("currency"),
                "line_items": [
                    {   
                        "line_id": item.get("id"),
                        "name": item.get("name"),
                        "product_id": item.get("product_id"),
                        "price": item.get("price"),
                        "quantity": item.get("quantity"),
                        "total": item.get("total"),
                        "images": [{"src": item.get("image", {}).get("src")}] if item.get("image") else []
                    } for item in o.get("line_items", [])
                ],
                "billing": o.get("billing"),
                "shipping": o.get("shipping"),
                "checkout_url": o.get("payment_url")
            }
        else:
            logging.error(f"Error fetching order {order_id}: {response.text}")
            return {"error": response.text}
    except Exception as e:
        logging.error(f"Exception in get_order: {e}")
        return {"error": str(e)}

# -- Cart Management Tools --

def view_cart(session_id: str = "default"):
    """Shows the contents of the current session cart."""
    logging.info(f"Viewing cart for session {session_id}.")
    order_id = get_cart_id(session_id)
    if not order_id: return {"error": "No active cart found."}
    return get_order(order_id)

def add_to_cart(product_id, quantity: int = 1, session_id: str = "default"):
    """Adds a product to the user's cart (order). Creates cart if none exists."""
    # Resolve product_id (it might be a name/hallucinated ID)
    resolved_id = resolve_product_id(product_id)
    if not resolved_id:
        return {"error": f"Could not find product: {product_id}"}
    product_id = resolved_id

    logging.info(f"Adding product {product_id} (qty {quantity}) to cart for session {session_id}...")
    
    # --- Option A: Stock Validation ---
    stock_info = check_stock_status(product_id)
    if "error" in stock_info:
        return {"error": f"Could not verify stock for product {product_id}: {stock_info['error']}"}
    
    if stock_info.get("stock_status") != "instock":
        return {"error": f"Product '{stock_info.get('name')}' is currently out of stock."}
    
    # If store manages stock, check if quantity is enough
    if stock_info.get("manage_stock") and stock_info.get("stock_quantity") is not None:
        if stock_info.get("stock_quantity") < quantity:
            return {"error": f"Only {stock_info.get('stock_quantity')} units of '{stock_info.get('name')}' are available. You requested {quantity}."}

    order_id = get_cart_id(session_id)
    if not order_id: return {"error": "Failed to retrieve or create cart."}
    
    wcapi = get_wcapi()
    order = get_order(order_id)
    if "error" in order: return order
    
    line_items = order.get("line_items", [])
    found = False
    
    update_lines = []

    for item in line_items:
        line_id = item.get("line_id")
        p_id = item.get("product_id")
        qty = item.get("quantity", 0)

        if str(p_id) == str(product_id):
            update_lines.append({
                "id": line_id,
                "quantity": int(qty) + int(quantity)
            })
            found = True
        else:
            update_lines.append({
                "id": line_id,
                "quantity": qty
            })

    if not found:
        update_lines.append({
            "product_id": product_id,
            "quantity": quantity
        })

    response = wcapi.put(f"orders/{order_id}", {"line_items": update_lines})
    if response.status_code == 200:
        o = response.json()
        return {
            "Currency": o.get("currency"),
            "checkout_url": o.get("payment_url"),
            "line_items": [
                {
                    "line_id": item.get("id"),
                    "name": item.get("name"),
                    "product_id": item.get("product_id"),
                    "price": item.get("price"),
                    "quantity": item.get("quantity"),
                    "total": item.get("total"),
                    "images": [{"src": item.get("image", {}).get("src")}] if item.get("image") else []
                } for item in o.get("line_items", [])
            ]
        }
    else:
        logging.error(f"Failed to add to cart: {response.text}")
        return {"error": response.text}

def remove_from_cart(product_id, quantity: int = -1, session_id: str = "default"):
    """Removes a product from the user's cart. If quantity is given, reduces by that amount; otherwise removes all."""
    # Resolve product_id
    resolved_id = resolve_product_id(product_id)
    if not resolved_id:
        return {"error": f"Could not find product: {product_id}"}
    product_id = resolved_id

    logging.info(f"Removing product {product_id} (qty: {quantity if quantity != -1 else 'all'}) from cart for session {session_id}...")
    order_id = get_cart_id(session_id)
    if not order_id: return {"error": "No active cart found."}
    
    wcapi = get_wcapi()
    order = get_order(order_id)
    if "error" in order: return order
    line_items = order.get("line_items", [])
    
    update_lines = []
    removed = False

    for item in line_items: 
        line_id = item.get("line_id")
        p_id = item.get("product_id")
        qty = int(item.get("quantity", 0))

        if str(p_id) == str(product_id):
            removed = True
            if quantity != -1:
                new_qty = qty - int(quantity)
            else:
                new_qty = 0  # Remove all
            update_lines.append({
                "id": line_id,
                "quantity": max(0, new_qty)
            })
        else:
            update_lines.append({
                "id": line_id,
                "quantity": qty
            })

    # API overwrite
    response = wcapi.put(f"orders/{order_id}", {"line_items": update_lines})
    if response.status_code == 200:
        o = response.json()
        return {
            "Currency": o.get("currency"),
            "checkout_url": o.get("payment_url"),
            "line_items": [
                {
                    "line_id": item.get("id"),
                    "name": item.get("name"),
                    "product_id": item.get("product_id"),
                    "price": item.get("price"),
                    "quantity": item.get("quantity"),
                    "total": item.get("total"),
                    "images": [{"src": item.get("image", {}).get("src")}] if item.get("image") else []
                } for item in o.get("line_items", [])
            ]
        }
    else:
        logging.error(f"Failed to remove from cart: {response.text}")
        return {"error": response.text}


def update_order(order_id: int, data: dict):
    """Updates an existing order. 'data' should be a dictionary containing fields to update."""
    logging.info(f"Updating order ID: {order_id}")
    wcapi = get_wcapi()
    try:
        response = wcapi.put(f"orders/{order_id}", data)
        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"Error updating order {order_id}: {response.text}")
            return {"error": response.text}
    except Exception as e:
        logging.error(f"Exception in update_order: {e}")
        return {"error": str(e)}

def delete_order(order_id: int):
    """Deletes an order by ID."""
    logging.info(f"Deleting order ID: {order_id}")
    wcapi = get_wcapi()
    try:
        response = wcapi.delete(f"orders/{order_id}", params={"force": True})
        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"Error deleting order {order_id}: {response.text}")
            return {"error": response.text}
    except Exception as e:
        logging.error(f"Exception in delete_order: {e}")
        return {"error": str(e)}

def batch_orders(data: dict):
    """
    Perform batch operations on orders (create, update, delete).
    'data' should be a dictionary like {'create': [...], 'update': [...], 'delete': [...]}
    """
    logging.info("Performing batch operations on orders...")
    wcapi = get_wcapi()
    try:
        response = wcapi.post("orders/batch", data)
        if response.status_code == 200:
            return response.json()
        else:
            logging.error(f"Error in batch orders: {response.text}")
            return {"error": response.text}
    except Exception as e:
        logging.error(f"Exception in batch_orders: {e}")
        return {"error": str(e)}
def apply_coupon(coupon_code: str, session_id: str = "default"):
    """Applies a coupon to the user's cart."""
    logging.info(f"Applying coupon {coupon_code} to cart for session {session_id}...")
    order_id = get_cart_id(session_id)
    if not order_id: return {"error": "No active cart found."}
    
    wcapi = get_wcapi()
    
    # Needs to match WooCommerce API structure for adding a coupon line
    update_data = {
        "coupon_lines": [
            {
                "code": coupon_code
            }
        ]
    }
    
    response = wcapi.put(f"orders/{order_id}", update_data)
    if response.status_code == 200:
        o = response.json()
        return {
            "Currency": o.get("currency"),
            "checkout_url": o.get("payment_url"),
            "coupon_lines": o.get("coupon_lines", []),
            "total": o.get("total")
        }
    else:
        logging.error(f"Failed to apply coupon: {response.text}")
        return {"error": response.text}

def get_store_info():
    """
    Retrieves general store information via the REST API.
    """
    logging.info("Fetching store info via REST API...")
    try:
        wcapi = get_wcapi()
        # The root of wc/v3 doesn't give much, but we can get some from /wp-json
        # However, for simplicity and currency, we might need settings or just the root.
        # Let's try the root of the site for basic info.
        response = requests.get(wcapi.url.split("/wp-json")[0] + "/wp-json", verify=False, timeout=10)
        if response.status_code == 200:
            data = response.json()
            return {
                "name": data.get("name"),
                "description": data.get("description"),
                "url": data.get("url"),
                "home": data.get("home"),
                "currency": "INR" # Defaulting for now as it's hard to get from root
            }
        return {"error": f"Failed to fetch store info: {response.status_code}"}
    except Exception as e:
        logging.error(f"Error in get_store_info: {e}")
        return {"error": str(e)}

# Export all tools
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
    get_products_by_brand
]
