import logging
import json
from . import actions_db
from . import actions

class MCPActions:
    def __init__(self, mcp_client):
        """
        Initializes the MCP Actions wrapper.
        :param mcp_client: An instance of WooCommerceMCPClient.
        """
        self.mcp = mcp_client

    def list_products(self, **kwargs):
        """Wrapper for MCP woocommerce-products-list ability with category resolution."""
        logging.info(f"Calling MCP woocommerce-products-list with args: {kwargs}")
        
        # Resolve category_id name to ID if needed
        category_id = kwargs.get("category_id")
        if category_id and isinstance(category_id, str) and not category_id.isdigit():
            logging.info(f"Attempting to resolve category name '{category_id}' to an ID...")
            try:
                categories = actions.list_categories()
                if isinstance(categories, list):
                    for cat in categories:
                        if cat.get("name", "").lower() == category_id.lower() or cat.get("slug", "").lower() == category_id.lower():
                            kwargs["category_id"] = str(cat["id"])
                            logging.info(f"Resolved category '{category_id}' to ID: {kwargs['category_id']}")
                            break
            except Exception as e:
                logging.error(f"Error resolving category name: {e}")

        try:
            res = self.mcp.call_tool("woocommerce-products-list", kwargs)
            if "structuredContent" in res:
                return res["structuredContent"]
            return res
        except Exception as e:
            logging.error(f"MCP list_products error: {e}")
            return {"error": str(e)}

    def get_product_details(self, product_id_or_name):
        """Wrapper for MCP woocommerce-products-get ability with name-to-ID resolution."""
        logging.info(f"Calling MCP woocommerce-products-get with: {product_id_or_name}")
        
        # 1. Resolve Name to ID if needed
        final_id = product_id_or_name
        if not str(product_id_or_name).isdigit():
            logging.info(f"Attempting to resolve '{product_id_or_name}' to a numeric ID via Vector DB...")
            res_db = actions_db.get_product_details_vector(product_id_or_name)
            if isinstance(res_db, dict) and "id" in res_db:
                final_id = res_db["id"]
                logging.info(f"Resolved to ID: {final_id}")
            else:
                logging.warning(f"Could not resolve '{product_id_or_name}' to an ID. Proceeding anyway.")

        try:
            # MCP 'woocommerce-products-get' tool expects 'id' as an integer
            if str(final_id).isdigit():
                final_id = int(final_id)
                
            res = self.mcp.call_tool("woocommerce-products-get", {"id": final_id})
            if "structuredContent" in res:
                return res["structuredContent"]
            return res
        except Exception as e:
            logging.error(f"MCP get_product error: {e}")
            return {"error": str(e)}


