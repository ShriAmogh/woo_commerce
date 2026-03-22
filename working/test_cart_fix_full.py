import requests
import json
import os
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

load_dotenv()

def test_cart_logic():
    url = os.getenv("WOO_URL", "http://woo-test.local").rstrip('/')
    key = os.getenv("WOO_CONSUMER_KEY")
    secret = os.getenv("WOO_CONSUMER_SECRET")
    
    live_user = os.getenv("WOO_LIVE_LINK_USER", "")
    live_pass = os.getenv("WOO_LIVE_LINK_PASS", "")
    auth = HTTPBasicAuth(live_user, live_pass) if live_user else None

    session_id = "test-session-123"
    product_id = 93  # Black Shoes
    payload = {"session_id": session_id, "product_id": product_id, "quantity": 1}
    
    # 1. Add to cart
    print(f"--- Testing Add to Cart (Session: {session_id}, Product: {product_id}) ---")
    
    add_url_pretty = f"{url}/wp-json/woo-chatbot/v1/cart/add"
    add_url_plain = f"{url}/?rest_route=/woo-chatbot/v1/cart/add"
    
    working_url = None
    last_res = None
    for add_url in [add_url_pretty, add_url_plain]:
        print(f"Trying URL: {add_url}")
        try:
            res = requests.post(add_url, json=payload, auth=auth, verify=False, timeout=10)
            if res.status_code == 200:
                working_url = add_url
                last_res = res
                print(f"SUCCESS with {add_url}")
                break
            else:
                print(f"Failed with {res.status_code}: {res.text}")
        except Exception as e:
            print(f"Request failed for {add_url}: {e}")
    
    if not working_url:
        print("FAILED at step 1: No working URL found.")
        return

    data = last_res.json()
    order_id = data.get("order_id")
    print(f"Draft Order Created: {order_id}")
    
    # Use the same URL style for subsequent calls
    base_api = working_url.rsplit('/', 1)[0] # removes 'add'
    
    # 2. Get Cart
    print(f"\n--- Testing Get Cart (Session: {session_id}) ---")
    if '/wp-json/' in working_url:
        get_url = f"{base_api}/get"
        res = requests.get(get_url, params={"session_id": session_id}, auth=auth, verify=False)
    else:
        get_url = f"{url}/?rest_route=/woo-chatbot/v1/cart/get"
        res = requests.get(get_url, params={"session_id": session_id}, auth=auth, verify=False)
        
    print(f"Status: {res.status_code}")
    if res.status_code == 200:
        if res.json().get("order_id") == order_id:
            print("SUCCESS: Order ID matches.")
        else:
            print(f"FAILED: ID mismatch. Expected {order_id}, got {res.json().get('order_id')}")
    else:
        print(f"FAILED: {res.text}")

    # 3. Remove from cart
    print(f"\n--- Testing Remove from Cart (Session: {session_id}, Product: {product_id}) ---")
    if '/wp-json/' in working_url:
        remove_url = f"{base_api}/remove"
    else:
        remove_url = f"{url}/?rest_route=/woo-chatbot/v1/cart/remove"
        
    res = requests.post(remove_url, json={"session_id": session_id, "product_id": product_id}, auth=auth, verify=False)
    print(f"Status: {res.status_code}")
    if res.status_code == 200:
        print("SUCCESS: Item removed.")
    else:
        print(f"FAILED: {res.text}")
    
    print("\nVerification complete.")

if __name__ == "__main__":
    test_cart_logic()
