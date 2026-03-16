import json
import logging
from actions import actions_db

# Configure logging to see the resolution process
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def test_get_product_details_standard():
    query = "footwear products"
    print(f"\n=== Testing get_product_details for query: '{query}' (Standard + DB) ===")
    
    try:
        # This function handles name resolution via Vector DB first, then fallback to search
        result = actions_db.get_product_details(query)
        result_2 = actions_db.search_products(query)
        
        if "error" in result:
            print(f"Error: {result['error']}")
        else:
            print("Successfully retrieved product details:")
            print(json.dumps(result, indent=2))
            print("\n\n\n")
            print("search_products")
            print(json.dumps(result_2, indent=2))
            
            # Basic validation
            if result.get("id"):
                print(f"\u2705 Found Product ID: {result['id']}")
            if result.get("name"):
                print(f"\u2705 Found Product Name: {result['name']}")
                
    except Exception as e:
        print(f"FAILED with exception: {e}")

if __name__ == "__main__":
    test_get_product_details_standard()
