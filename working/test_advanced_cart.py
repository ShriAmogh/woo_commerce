import os
import requests
import logging
from requests.auth import HTTPBasicAuth
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def test_advanced_cart():
    base_url = os.getenv("WOO_URL", "https://smart-pier.localsite.io").rstrip('/')
    key = os.getenv("WOO_CONSUMER_KEY")
    secret = os.getenv("WOO_CONSUMER_SECRET")
    live_user = os.getenv("WOO_LIVE_LINK_USER", "")
    live_pass = os.getenv("WOO_LIVE_LINK_PASS", "")
    auth = HTTPBasicAuth(live_user, live_pass) if live_user else None

    session_id = "test-advanced-session"
    product_id = 93  # Black Shoes (Parent)
    
    auth_params = {"consumer_key": key, "consumer_secret": secret}

    # 1. Add 5 items
    print(f"\n--- 1. Adding 5 items (Product {product_id}) ---")
    url = f"{base_url}/wp-json/woo-chatbot/v1/cart/add"
    payload = {"session_id": session_id, "product_id": product_id, "quantity": 5}
    res = requests.post(url, json=payload, params=auth_params, auth=auth, verify=False)
    print(f"Status: {res.status_code}")
    if res.status_code == 200:
        print(f"Count: {res.json().get('item_count')}")
    else:
        print(f"Error: {res.text}")

    # 2. Update to absolute quantity 3
    print(f"\n--- 2. Updating to absolute quantity 3 ---")
    url = f"{base_url}/wp-json/woo-chatbot/v1/cart/update"
    payload = {"session_id": session_id, "product_id": product_id, "quantity": 3}
    res = requests.post(url, json=payload, params=auth_params, auth=auth, verify=False)
    print(f"Status: {res.status_code}")
    if res.status_code == 200:
        print(f"Count: {res.json().get('item_count')}")
    else:
        print(f"Error: {res.text}")

    # 3. Remove 1 item (should leave 2)
    print(f"\n--- 3. Removing 1 item (partial) ---")
    url = f"{base_url}/wp-json/woo-chatbot/v1/cart/remove"
    payload = {"session_id": session_id, "product_id": product_id, "quantity": 1}
    res = requests.post(url, json=payload, params=auth_params, auth=auth, verify=False)
    print(f"Status: {res.status_code}")
    if res.status_code == 200:
        print(f"Total items now: {res.json().get('item_count')}")
    else:
        print(f"Error: {res.text}")

    # 4. Remove all (quantity -1)
    print(f"\n--- 4. Removing all items ---")
    url = f"{base_url}/wp-json/woo-chatbot/v1/cart/remove"
    payload = {"session_id": session_id, "product_id": product_id, "quantity": -1}
    res = requests.post(url, json=payload, params=auth_params, auth=auth, verify=False)
    print(f"Status: {res.status_code}")
    if res.status_code == 200:
        print(f"Total items now: {res.json().get('item_count')}")
    else:
        print(f"Error: {res.text}")

if __name__ == "__main__":
    test_advanced_cart()
