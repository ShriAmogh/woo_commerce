import json
import logging
import os
import requests
from google import genai
from dotenv import load_dotenv, find_dotenv

# Load environment variables (search for .env in project root if present)
load_dotenv(find_dotenv())
from system_prompt_gemini import system_prompt, summarizer_prompt
from actions import actions, actions_db, actions_mcp
from mcp_client import WooCommerceMCPClient
from actions.actions_db import search_products_vector, get_product_details_vector, search_products_by_brand

load_dotenv()

class GeminiOrchestrator:
    def __init__(self, model_id="gemini-2.5-flash"):
        # Try Vertex AI (service account) first, then fall back to API key
        gcp_project = os.getenv("GOOGLE_CLOUD_PROJECT")
        gcp_location = os.getenv("GOOGLE_CLOUD_LOCATION", "asia-south1")
        gcp_creds = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

        if gcp_project and gcp_creds and os.path.exists(gcp_creds):
            self.api_mode = f"Vertex AI (project={gcp_project}, location={gcp_location})"
            self.client = genai.Client(
                vertexai=True,
                project=gcp_project,
                location=gcp_location,
            )
        else:
            self.api_key = os.getenv("GEMINI_API_KEY_SOMESH") or os.getenv("GEMINI_API_KEY")
            if not self.api_key:
                raise ValueError("No valid Vertex AI credentials or Gemini API key (GEMINI_API_KEY_SOMESH or GEMINI_API_KEY) found.")
            self.api_mode = "Google AI API Key (fallback)"
            self.client = genai.Client(api_key=self.api_key)

        self.model_id = model_id
        logging.info(f"🔧 API: {self.api_mode}")
        logging.info(f"🤖 Model: {self.model_id}")
        self.system_instruction = system_prompt
        
        try:
            self.mcp = WooCommerceMCPClient()
            self.mcp_actions = actions_mcp.MCPActions(self.mcp)
            mcp_available = True
            logging.info("✅ MCP connected")
        except Exception as e:
            logging.warning(f"⚠️ MCP unavailable, falling back to REST: {e}")
            mcp_available = False
        
        self.available_tools = {
            "list_products": self.mcp_actions.list_products if mcp_available else actions.list_products,
            "search_products": actions_db.search_products_vector,
            "get_product_details": self.mcp_actions.get_product_details if mcp_available else actions.get_product_details,
            "get_store_info": actions.get_store_info,
            "list_categories": actions.list_categories,
            "get_product_variations": actions.get_product_variations,
            "list_brands": actions.list_brands,
            "get_products_by_brand": actions.get_products_by_brand,
            "search_products_by_brand": search_products_by_brand,
            "check_stock_status": actions.check_stock_status,
            "view_cart": actions.view_cart,
            "add_to_cart": actions.add_to_cart,
            "remove_from_cart": actions.remove_from_cart,
            "apply_coupon": actions.apply_coupon
        }
        
        self.AUTHENTICATED_TOOLS = {"view_cart", "add_to_cart", "remove_from_cart", "apply_coupon"}

        self.store_url = os.getenv("WOO_URL", "Store")
        self.store_name = self.store_url.split("//")[-1].split(".")[0]
        self.history = [] # Gemini SDK handles history differently, but we'll keep a list of parts
        self.context = {"last_products": [], "categories": [], "cart": []} # Structured session memory

    def _call_gemini(self, user_input: str, session_context: dict = None):
        """Helper to invoke Gemini with history and context."""
        
        auth_status = "User is logged in." if session_context and session_context.get("is_logged_in") else "User is a GUEST (not logged in). They must log in to use Cart tools."
        session_info = f"\n\nCURRENT SESSION CONTEXT:\n{auth_status}"
        
        prompt_with_context = self.system_instruction + session_info + f"\n\nContext block:\n{json.dumps(self.context, indent=2)}\n\nPlease ensure your tool calls adhere to this context exactly."
        
        history_for_gemini = self.history + [{"role": "user", "parts": [{"text": user_input}]}]
        
        try:
            response = self.client.models.generate_content(
                model=self.model_id,
                config={
                    'system_instruction': prompt_with_context,
                    'response_mime_type': 'application/json'
                },
                contents=history_for_gemini
            )
            return response.text
        except Exception as e:
            logging.error(f"Gemini API Error: {e}")
            return None

    def _summarize_results(self, user_query, tool_results):
        """Second pass to convert raw JSON into a friendly response."""
        try:
            summarizer_input = f"User Request: {user_query}\n\nTool Results (JSON):\n{json.dumps(tool_results, indent=2)}"
            
            response = self.client.models.generate_content(
                model=self.model_id,
                config={
                    'system_instruction': summarizer_prompt,
                    'temperature': 0.3
                },
                contents=[{"role": "user", "parts": [{"text": summarizer_input}]}]
            )
            return response.text
        except Exception as e:
            logging.error(f"Summarization Error: {e}")
            return json.dumps(tool_results, indent=2)

    def handle_query(self, user_input: str, session_context: dict = None):
        """Sends user input to Gemini and handles manual tool calling."""
        logging.info(f"User query (Gemini): {user_input} | Session: {session_context}")
        
        # 1. Initial Call to Gemini
        raw_response = self._call_gemini(user_input, session_context)
        
        if not raw_response:
            return "Gemini API is not responding."

        logging.info(f"Gemini Intent/Direct Response Raw: {raw_response}")

        try:
            data = json.loads(raw_response)
            
            # 2a. Handle Multi-Tool Call
            if "tools" in data and isinstance(data["tools"], list):
                all_results = {}
                for i, call in enumerate(data["tools"]):
                    t_name = call.get("tool") or call.get("name")
                    t_args = call.get("args", {})
                    if not t_name or t_name not in self.available_tools:
                        continue
                    logging.info(f"Gemini calling tool (multi {i+1}): {t_name} with args: {t_args}")
                    
                    if t_name in self.AUTHENTICATED_TOOLS:
                        if not (session_context and session_context.get("is_logged_in")):
                            all_results[f"{i+1}_{t_name}"] = {"error": "Authentication required. Please ask the user to log in first."}
                            continue
                        else:
                            t_args["session_id"] = session_context.get("session_id", "default")
                        
                    try:
                        res = self.available_tools[t_name](**t_args)
                        all_results[f"{i+1}_{t_name}"] = res
                    except Exception as e:
                        logging.error(f"Multi-tool error on {t_name}: {e}")
                        all_results[f"{i+1}_{t_name}"] = {"error": str(e)}

                if all_results:
                    # Update context for each tool call result if applicable (simplified here)
                    # For multi-tool, we just summarize all at once
                    friendly_response = self._summarize_results(user_input, all_results)
                    
                    self.history.append({"role": "user", "parts": [{"text": user_input}]})
                    self.history.append({"role": "model", "parts": [{"text": friendly_response}]})
                    return friendly_response
            
            # 2b. Handle Single Tool Call
            tool_name = data.get("tool")
            if tool_name:
                args = data.get("args", {})
                
                if tool_name not in self.available_tools:
                    return f"Error: The model tried to call a non-existent tool: {tool_name}."
                
                logging.info(f"Gemini calling tool: {tool_name} with args: {args}")
                
                if tool_name in self.AUTHENTICATED_TOOLS:
                    if not (session_context and session_context.get("is_logged_in")):
                        res = {"error": "Authentication required. Please ask the user to log in first."}
                        friendly_response = self._summarize_results(user_input, {tool_name: res})
                        self.history.append({"role": "user", "parts": [{"text": user_input}]})
                        self.history.append({"role": "model", "parts": [{"text": friendly_response}]})
                        return friendly_response
                    else:
                        args["session_id"] = session_context.get("session_id", "default")
                
                try:
                    tool_func = self.available_tools[tool_name]
                    result = tool_func(**args)
                    
                    # Store IDs in Context Dictionary
                    if tool_name in ["list_products", "search_products", "get_product_details"]:
                        items_to_add = result if isinstance(result, list) else [result] if isinstance(result, dict) else []
                        for item in items_to_add:
                            if isinstance(item, dict) and "id" in item and "name" in item:
                                self.context["last_products"] = [p for p in self.context["last_products"] if p["id"] != item["id"]]
                                self.context["last_products"].append({"id": item["id"], "name": item["name"]})
                        self.context["last_products"] = self.context["last_products"][-10:]
                    
                    elif tool_name in ["view_cart", "add_to_cart", "remove_from_cart"]:
                        if isinstance(result, dict) and "line_items" in result:
                            self.context["cart"] = [{"product_id": item.get("product_id"), "qty": item.get("quantity")} for item in result["line_items"]]
                        elif isinstance(result, dict) and result.get("message") == "Cart is empty.":
                            self.context["cart"] = []
                            
                    elif tool_name == "list_categories":
                        if isinstance(result, list):
                            self.context["categories"] = [{"id": cat.get("id"), "name": cat.get("name")} for cat in result]
                            
                    elif tool_name == "list_brands":
                        if isinstance(result, list):
                            self.context["brands"] = [{"id": b.get("id"), "name": b.get("name"), "slug": b.get("slug")} for b in result]
                            
                    logging.info(f"Updated Session Memory: {self.context}")
                    
                    # 3. Summarization Pass (Friendly response)
                    friendly_response = self._summarize_results(user_input, result)
                    
                    self.history.append({"role": "user", "parts": [{"text": user_input}]})
                    self.history.append({"role": "model", "parts": [{"text": friendly_response}]})
                    
                    return friendly_response
                except Exception as e:
                    logging.error(f"Tool Execution Error: {e}")
                    return f"Error executing {tool_name}: {str(e)}"
            
            # 3. Handle Direct Response
            if "response" in data:
                response_text = data["response"]
                self.history.append({"role": "user", "parts": [{"text": user_input}]})
                self.history.append({"role": "model", "parts": [{"text": response_text}]})
                return response_text
            
            return raw_response
            
        except json.JSONDecodeError:
            self.history.append({"role": "user", "parts": [{"text": user_input}]})
            self.history.append({"role": "model", "parts": [{"text": raw_response}]})
            return raw_response

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    orch = GeminiOrchestrator()
    print(orch.handle_query("List my products"))
