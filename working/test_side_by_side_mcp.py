import os
import sys
import logging
import json
from dotenv import load_dotenv

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(message)s')
# Reduce lower-level noise if desired: logging.getLogger("urllib3").setLevel(logging.WARNING)

from orchestrator_gemini import GeminiOrchestrator
from mcp_client import WooCommerceMCPClient
from actions.actions_mcp import MCPActions

def print_result(res):
    if isinstance(res, list):
        print(f"List response with {len(res)} items.")
        if len(res) > 0:
            # Safely print first item summary
            first = res[0]
            if isinstance(first, dict):
                print(f"First item -> ID: {first.get('id')}, Name: {first.get('name')}")
            else:
                print(f"First item: {str(first)[:100]}...")
    elif isinstance(res, dict):
        if "error" in res:
            print(f"Error Result: {res['error']}")
        else:
            # Just print the top-level keys or short dump for brevity
            keys = list(res.keys())
            name = res.get('name', 'N/A')
            print(f"Dict response. Keys: {keys}. Name: {name}")
    else:
        print(f"Raw response: {str(res)[:200]}...")

def main():
    print("=== Testing MCP Actions: Orchestrator Mapped vs Direct Class ===")
    
    # Initialize both Orchestrator (which creates its own MCPActions)
    # and a standalone direct instance of MCPActions.
    try:
        logging.info("[Setup] Initializing Orchestrator...")
        orchestrator = GeminiOrchestrator()
        orch_tools = orchestrator.available_tools
        
        logging.info("[Setup] Initializing standalone direct MCPActions...")
        mcp_client = WooCommerceMCPClient()
        direct_actions = MCPActions(mcp_client)
    except Exception as e:
        print(f"Failed to initialize: {e}")
        return

    # Define the 5 tasks to test based on your requirement
    test_cases = [
        {
            "name": "get_store_info",
            "kwargs": {},
            "orch_func": orch_tools.get("get_store_info"),
            "direct_func": direct_actions.get_store_info
        },
        {
            "name": "list_categories",
            "kwargs": {},
            "orch_func": orch_tools.get("list_categories"),
            "direct_func": direct_actions.list_categories
        },
        {
            "name": "list_products",
            "kwargs": {},
            "orch_func": orch_tools.get("list_products"),
            "direct_func": direct_actions.list_products
        },
        {
            "name": "search_products",
            "kwargs": {"query": "shoes"},
            "orch_func": orch_tools.get("search_products"),
            "direct_func": direct_actions.search_products
        },
        {
            "name": "get_product_details",
            "kwargs": {"product_id_or_name": "socks"},
            "orch_func": orch_tools.get("get_product_details"),
            "direct_func": direct_actions.get_product_details
        }
    ]

    for tc in test_cases:
        func_name = tc["name"]
        kwargs = tc["kwargs"]
        print(f"\n{'='*60}")
        print(f"TESTING: {func_name} | Args: {kwargs}")
        print(f"{'='*60}")
        
        # 1. Direct Function Call
        print(f"\n--- [DIRECT CLASS CALL : MCPActions.{func_name}] ---")
        try:
            if tc["direct_func"]:
                print_result(tc["direct_func"](**kwargs))
            else:
                print("Direct function not available.")
        except Exception as e:
            print(f"Direct call failed: {e}")

        # 2. Orchestrator Tool Call
        print(f"\n--- [ORCHESTRATOR MAPPED CALL : available_tools['{func_name}']] ---")
        try:
            if tc["orch_func"]:
                 print_result(tc["orch_func"](**kwargs))
            else:
                print("Tool mapped function not available.")
        except Exception as e:
            print(f"Orchestrator call failed: {e}")

if __name__ == "__main__":
    main()
