import json
import logging
import sys
import os

# Ensure we can import mcp_client from the parent or current directory
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

try:
    from mcp_client import WooCommerceMCPClient
except ImportError as e:
    print(f"Import Error: {e}")
    sys.exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def test_mcp_search_direct(query_string):
    print(f"\n=== Testing MCP Product Search (Direct) for: '{query_string}' ===")
    
    try:
        # 1. Initialize the MCP Client directly
        print("Initializing WooCommerce MCP Client...")
        client = WooCommerceMCPClient()
        
        # 2. Call 'woocommerce-products-list' which accepts a 'search' string
        # This bypasses the Vector DB and tests the MCP tool's native search ability.
        print(f"Calling 'woocommerce-products-list' with search='{query_string}'...")
        res = client.call_tool("woocommerce-products-list", {"search": query_string})
        
        # 3. Extract results
        result = res.get("structuredContent", res)
        
        if isinstance(result, dict) and result.get("isError"):
            print(f"MCP Error: {result.get('content', [{}])[0].get('text', 'Unknown error')}")
        else:
            print(f"Successfully retrieved results for '{query_string}' directly via MCP:")
            print(json.dumps(result, indent=2))
            
    except Exception as e:
        print(f"FAILED with exception: {e}")

if __name__ == "__main__":
    # The user wanted to pass "socks" to the MCP
    test_mcp_search_direct("socks")
