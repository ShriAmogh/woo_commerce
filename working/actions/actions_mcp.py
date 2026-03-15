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
                categories = self.list_categories() # Changed to self.list_categories()
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

    def search_products(self, query):
        """Wrapper for MCP woocommerce-products-list ability with search query."""
        logging.info(f"Calling MCP woocommerce-products-list (search) with query: {query}")
        try:
            res = self.mcp.call_tool("woocommerce-products-list", {"search": query})
            if "structuredContent" in res:
                return res["structuredContent"]
            return res
        except Exception as e:
            logging.error(f"MCP search_products error: {e}")
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

    def get_store_info(self):
        """Wrapper for MCP woocommerce-system-status-get ability."""
        logging.info("Calling MCP woocommerce-system-status-get")
        try:
            res = self.mcp.call_tool("woocommerce-system-status-get", {})
            if "structuredContent" in res:
                return res["structuredContent"]
            return res
        except Exception as e:
            logging.error(f"MCP get_store_info error: {e}")
            return {"error": str(e)}

    def list_categories(self):
        """Wrapper for MCP woocommerce-products-categories-list ability."""
        logging.info("Calling MCP woocommerce-products-categories-list")
        try:
            res = self.mcp.call_tool("woocommerce-products-categories-list", {})
            if "structuredContent" in res:
                return res["structuredContent"]
            return res
        except Exception as e:
            logging.error(f"MCP list_categories error: {e}")
            return {"error": str(e)}

    def list_brands(self):
        """Wrapper for MCP woocommerce-products-brands-list ability."""
        logging.info("Calling MCP woocommerce-products-brands-list")
        try:
            res = self.mcp.call_tool("woocommerce-products-brands-list", {})
            if "structuredContent" in res:
                return res["structuredContent"]
            return res
        except Exception as e:
            logging.error(f"MCP list_brands error: {e}")
            return {"error": str(e)}

    def get_products_by_brand(self, brand_slug):
        """Wrapper for MCP woocommerce-products-list ability to filter by brand slug."""
        logging.info(f"Calling MCP woocommerce-products-list (brand search) for: {brand_slug}")
        try:
            # Assuming the 'search' parameter can effectively filter by brand slug
            res = self.mcp.call_tool("woocommerce-products-list", {"search": brand_slug})
            if "structuredContent" in res:
                return res["structuredContent"]
            return res
        except Exception as e:
            logging.error(f"MCP get_products_by_brand error: {e}")
            return {"error": str(e)}

    def search_products_by_brand(self, brand, query):
        """Wrapper for MCP woocommerce-products-list ability to search within a brand."""
        logging.info(f"Calling MCP woocommerce-products-list for brand: {brand} and query: {query}")
        try:
            # Combining brand and query for a broader search
            res = self.mcp.call_tool("woocommerce-products-list", {"search": f"{brand} {query}"})
            if "structuredContent" in res:
                return res["structuredContent"]
            return res
        except Exception as e:
            logging.error(f"MCP search_products_by_brand error: {e}")
            return {"error": str(e)}
