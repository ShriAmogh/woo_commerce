import json
import logging
from actions import actions
from actions import actions_db

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def compare_search(query):
    print(f"\n{'='*80}")
    print(f" COMPARISON: SEARCH for '{query}'")
    print(f"{'='*80}")
    
    # 1. Standard search
    print("\n--- [actions.py] search_products (Keyword Search) ---")
    res_std = actions.search_products(query)
    print(json.dumps(res_std, indent=2))
    
    # 2. Vector search
    print("\n--- [actions_db.py] search_products_vector (Semantic AI Search) ---")
    res_vec = actions_db.search_products_vector(query)
    print(json.dumps(res_vec, indent=2))

def compare_details(query):
    print(f"\n{'='*80}")
    print(f" COMPARISON: DETAILS for '{query}'")
    print(f"{'='*80}")
    
    # 1. Standard details
    print("\n--- [actions.py] get_product_details (Live API - Full Data) ---")
    res_std = actions.get_product_details(query)
    print(json.dumps(res_std, indent=2))
    
    # 2. Vector details
    print("\n--- [actions_db.py] get_product_details_vector (Qdrant Payload - Simplified) ---")
    res_vec = actions_db.get_product_details_vector(query)
    print(json.dumps(res_vec, indent=2))

def compare_brand(brand):
    print(f"\n{'='*80}")
    print(f" COMPARISON: BRAND LIST for '{brand}'")
    print(f"{'='*80}")
    
    # 1. Standard search (by keyword)
    print(f"\n--- [actions.py] search_products('{brand}') ---")
    res_std = actions.search_products(brand)
    print(json.dumps(res_std, indent=2))
    
    # 2. Vector brand search
    print(f"\n--- [actions_db.py] get_products_by_brand('{brand}') ---")
    res_vec = actions_db.get_products_by_brand(brand)
    print(json.dumps(res_vec, indent=2))

if __name__ == "__main__":
    # Test cases
    test_query = "socks"
    test_brand = "nike"
    
    compare_search(test_query)
    compare_details(test_query)
    compare_brand(test_brand)
