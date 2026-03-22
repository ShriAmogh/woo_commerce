import json
from orchestrator_gemini import GeminiOrchestrator

def test_prep():
    orch = GeminiOrchestrator()
    
    # 1. Test Product
    raw_p = {
        "id": 123,
        "name": "Cool Shoes",
        "price": "10000.0",
        "regular_price": "12000.0",
        "currency": "INR",
        "stock_status": "instock",
        "description": "<p>These are <strong>great</strong> shoes.</p>",
        "attributes": [
            {"name": "Size", "options": ["Small", "Medium"]}
        ]
    }
    
    clean_p = orch._prepare_results_for_llm(raw_p)
    print("--- PRODUCT TEST ---")
    print(json.dumps(clean_p, indent=2, ensure_ascii=False))
    
    # 2. Test Cart
    raw_cart = {
        "line_items": [
            {"name": "Shoes", "quantity": 1, "price": "10000", "total": "10000"}
        ],
        "totals": {"total_items": "10000", "total_price": "10000"},
        "currency": "INR",
        "checkout_url": "https://store.com/checkout"
    }
    
    clean_cart = orch._prepare_results_for_llm(raw_cart)
    print("\n--- CART TEST ---")
    print(json.dumps(clean_cart, indent=2, ensure_ascii=False))
    
    # 3. Test Store Info
    raw_store = {
        "name": "My Shop",
        "url": "https://myshop.com",
        "description": "Best shop <b>ever</b>",
        "policies": [{"content": "No returns <i>allowed</i>"}]
    }
    
    clean_store = orch._prepare_results_for_llm(raw_store)
    print("\n--- STORE TEST ---")
    print(json.dumps(clean_store, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    test_prep()
