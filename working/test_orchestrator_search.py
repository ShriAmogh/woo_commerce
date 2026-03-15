import os
import sys
import logging
import json
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

from orchestrator_gemini import GeminiOrchestrator

def main():
    print("=== Testing Orchestrator MCP search & get ===")
    
    try:
        logging.info("Initializing Orchestrator...")
        orchestrator = GeminiOrchestrator()
        tools = orchestrator.available_tools
        
        query = "socks"
        
        # 1. Test search_products
        print(f"\n--- 1. Testing search_products ('{query}') ---")
        if "search_products" in tools:
            try:
                res = tools["search_products"](query)
                print(f"Result type: {type(res)}")
                if isinstance(res, list):
                    print(f"Found {len(res)} products.")
                    for p in res:
                        print(f" - ID: {p.get('id')}, Name: {p.get('name')}")
                else:
                    print(json.dumps(res, indent=2)[:500] + "...")
            except Exception as e:
                print(f"Error in search_products: {e}")
                
        # 2. Test get_product_details
        print(f"\n--- 2. Testing get_product_details ('{query}') ---")
        if "get_product_details" in tools:
            try:
                res = tools["get_product_details"](query)
                print(f"Result type: {type(res)}")
                
                if isinstance(res, dict) and "error" in res:
                     print(f"Error returned: {res['error']}")
                elif isinstance(res, dict):
                    print(f"Name: {res.get('name', 'N/A')}")
                    print(f"ID: {res.get('id')}")
                elif isinstance(res, list) and len(res) > 0:
                    first = res[0]
                    if isinstance(first, dict):
                         print(f"List response, first item. Name: {first.get('name', 'N/A')}, ID: {first.get('id')}")
                    else:
                         print(f"List response, first item: {first}")
                else:
                     print(f"Raw response: {res}")
            except Exception as e:
                print(f"Error in get_product_details: {e}")

        # 3. Test get_products_by_brand ('nike')
        brand_slug = "nike"
        print(f"\n--- 3. Testing get_products_by_brand ('{brand_slug}') ---")
        if "get_products_by_brand" in tools:
            try:
                res = tools["get_products_by_brand"](brand_slug)
                print(f"Result type: {type(res)}")
                if isinstance(res, list):
                    print(f"Found {len(res)} products for brand {brand_slug}.")
                    for p in res[:5]: # print first 5
                        print(f" - ID: {p.get('id')}, Name: {p.get('name')}")
                else:
                    print(json.dumps(res, indent=2)[:500] + "...")
            except Exception as e:
                print(f"Error in get_products_by_brand: {e}")

        # 4. Test search_products_by_brand ('nike' + query)
        brand_slug = "nike"
        brand_query = "shoes"
        print(f"\n--- 4. Testing search_products_by_brand ('{brand_slug}', '{brand_query}') ---")
        if "search_products_by_brand" in tools:
            try:
                # Assuming signature is (brand, query)
                res = tools["search_products_by_brand"](brand_slug, brand_query)
                print(f"Result type: {type(res)}")
                if isinstance(res, list):
                    print(f"Found {len(res)} products for brand {brand_slug} and query {brand_query}.")
                    for p in res[:5]: # print first 5
                        print(f" - ID: {p.get('id')}, Name: {p.get('name')}")
                else:
                    print(json.dumps(res, indent=2)[:500] + "...")
            except Exception as e:
                print(f"Error in search_products_by_brand: {e}")
                
    except Exception as e:
        print(f"Orchestrator init failed: {e}")

if __name__ == "__main__":
    main()
