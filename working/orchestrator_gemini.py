import json
import logging
import re
import os
import requests
from google import genai
from dotenv import load_dotenv, find_dotenv

load_dotenv(find_dotenv())
from system_prompt_gemini import system_prompt, summarizer_prompt
from actions import actions, actions_db, actions_mcp
from mcp_client import WooCommerceMCPClient
from actions.actions_db import search_products_vector, get_product_details_vector, search_products_by_brand

load_dotenv()

class GeminiOrchestrator:
    def __init__(self, model_id="gemini-2.5-flash"):
        gcp_project  = os.getenv("GOOGLE_CLOUD_PROJECT")
        gcp_location = os.getenv("GOOGLE_CLOUD_LOCATION", "asia-south1")
        gcp_creds    = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")

        if gcp_project and gcp_creds and os.path.exists(gcp_creds):
            self.api_mode = f"Vertex AI (project={gcp_project}, location={gcp_location})"
            self.client   = genai.Client(vertexai=True, project=gcp_project, location=gcp_location)
        else:
            self.api_key = os.getenv("GEMINI_API_KEY_SOMESH") or os.getenv("GEMINI_API_KEY")
            if not self.api_key:
                raise ValueError("No valid Vertex AI credentials or Gemini API key found.")
            self.api_mode = "Google AI API Key (fallback)"
            self.client   = genai.Client(api_key=self.api_key)

        self.model_id           = model_id
        self.system_instruction = system_prompt
        logging.info(f"🔧 API: {self.api_mode} | 🤖 Model: {self.model_id}")

        try:
            self.mcp         = WooCommerceMCPClient()
            self.mcp_actions = actions_mcp.MCPActions(self.mcp)
            logging.info("✅ MCP connected")
        except Exception as e:
            logging.warning(f"⚠️ MCP unavailable, falling back to REST: {e}")

        self.available_tools = {
            "list_products":          actions.list_products,
            "search_products":        actions_db.search_products_vector,
            "get_product_details":    actions.get_product_details,
            "get_store_info":         actions.get_store_info,
            "list_categories":        actions.list_categories,
            "get_product_variations": actions.get_product_variations,
            "list_brands":            actions.list_brands,
            "get_products_by_brand":  actions_db.get_products_by_brand,
            "search_products_by_brand": actions_db.search_products_by_brand,
            "check_stock_status":     actions.check_stock_status,
            "view_cart":              actions.view_cart,
            "add_to_cart":            actions.add_to_cart,
            "remove_from_cart":       actions.remove_from_cart,
            "apply_coupon":           actions.apply_coupon,
        }

        self.AUTHENTICATED_TOOLS = {"view_cart", "add_to_cart", "remove_from_cart", "apply_coupon"}
        self.store_url  = os.getenv("WOO_URL", "Store")
        self.store_name = self.store_url.split("//")[-1].split(".")[0]
        self.history    = []
        self.context    = {"last_products": [], "categories": [], "brands": [], "cart": []}

    # ─────────────────────────────────────────────────────────────────────────
    # URL cleanup — Gemini wraps underscored URLs in __ markdown bold
    # e.g. [text](__https://url__) → [text](https://url)
    # ─────────────────────────────────────────────────────────────────────────
    def _clean_urls(self, text: str) -> str:
        if not text:
            return text

        # Fix [text](__url__) → [text](url)
        text = re.sub(r'\[([^\]]+)\]\(__+([^)]+?)__+\)', r'[\1](\2)', text)

        # Fix [text](url)? or [text](url)) — stray trailing bracket/paren
        text = re.sub(r'\[([^\]]+)\]\((https?://[^)]+?)\)+\)?', r'[\1](\2)', text)

        # Fix raw __https://...__ outside of markdown links
        text = re.sub(r'__+(https?://[^\s_]+?)__+', r'\1', text)

        # Fix trailing ) or ? after closing paren in markdown links
        text = re.sub(r'\]\((https?://[^)]+?)\)[)?]+', lambda m: f']({m.group(1).rstrip(")?/")})', text)

        # Clean up any remaining __ wrapping around URLs inside parens
        text = re.sub(r'\(_{1,2}(https?://[^)]+?)_{1,2}\)', r'(\1)', text)

        return text

    def _clean_html(self, text):
        if not text: return ""
        # Strip HTML tags
        clean = re.sub('<[^<]+?>', '', text)
        # Decode common entities and clean whitespace
        clean = clean.replace('&nbsp;', ' ').replace('&amp;', '&').replace('&quot;', '"')
        return clean.strip()

    def _format_price(self, price, currency):
        if price is None or price == "": return ""
        try:
            p = float(price)
            cur_sym = currency if currency != "INR" else "₹"
            if cur_sym == "₹":
                return f"₹{p:,.2f}"
            return f"{cur_sym} {p:,.2f}"
        except:
            return f"{currency} {price}"

    def _format_variations(self, attributes, price, currency):
        formatted = []
        f_price = self._format_price(price, currency)
        for attr in attributes:
            name = attr.get("name")
            options = attr.get("options", [])
            for opt in options:
                formatted.append(f"{name}: {opt} — {f_price}")
        return formatted

    def _prepare_results_for_llm(self, tool_results):
        """
        Transforms raw tool JSON into a curated, clean, LLM-ready object.
        """
        if not tool_results: return None

        # Helper to transform a single product
        def transform_product(p):
            price = p.get("price") or p.get("regular_price")
            currency = p.get("currency", "INR")
            stock = p.get("stock_status") or ("instock" if p.get("in_stock") else "outofstock")
            return {
                "name": p.get("name"),
                "price": self._format_price(price, currency),
                "stock": "In stock" if stock == "instock" else "Out of stock",
                "description": self._clean_html(p.get("short_description") or p.get("description")),
                "permalink": p.get("permalink"),
                "variations": self._format_variations(p.get("attributes", []), price, currency)
            }

        # Helper to transform cart
        def transform_cart(c):
            if not c or not isinstance(c, dict): return c
            currency = c.get("currency", "INR")
            items = []
            for item in c.get("line_items", []):
                items.append({
                    "name": item.get("name"),
                    "qty": item.get("quantity"),
                    "price": self._format_price(item.get("price"), currency),
                    "total": self._format_price(item.get("total"), currency)
                })
            return {
                "items": items,
                "subtotal": self._format_price(c.get("totals", {}).get("total_items"), currency),
                "total": self._format_price(c.get("totals", {}).get("total_price"), currency),
                "checkout_url": c.get("checkout_url")
            }

        # Helper to transform store info
        def transform_store_info(s):
            if not s or not isinstance(s, dict): return s
            return {
                "name": s.get("name"),
                "description": self._clean_html(s.get("description")),
                "url": s.get("url"),
                "policies": [self._clean_html(p.get("content")) for p in s.get("policies", [])]
            }

        # Handle flat list of products
        if isinstance(tool_results, list):
            return [transform_product(item) for item in tool_results if isinstance(item, dict) and "id" in item]

        # Handle single result or dict of results
        if isinstance(tool_results, dict):
            # If it's a single product result
            if "id" in tool_results and "name" in tool_results:
                return transform_product(tool_results)
            
            # If it's a cart result
            if "line_items" in tool_results or "totals" in tool_results:
                return transform_cart(tool_results)

            # If it's store info
            if "name" in tool_results and "url" in tool_results:
                return transform_store_info(tool_results)

            # Handle multi-tool results map
            prepared = {}
            for key, val in tool_results.items():
                if isinstance(val, list):
                    prepared[key] = [transform_product(i) for i in val if isinstance(i, dict) and "id" in i]
                elif isinstance(val, dict):
                    if "line_items" in val:
                        prepared[key] = transform_cart(val)
                    elif "id" in val and "name" in val:
                        prepared[key] = transform_product(val)
                    else:
                        prepared[key] = val
                else:
                    prepared[key] = val
            return prepared

        return tool_results

    # ─────────────────────────────────────────────────────────────────────────
    # Gemini router call
    # ─────────────────────────────────────────────────────────────────────────
    def _call_gemini(self, user_input: str, session_context: dict = None):
        auth_status = (
            "User is logged in."
            if session_context and session_context.get("is_logged_in")
            else "User is a GUEST (not logged in). They must log in to use Cart tools."
        )
        prompt = (
            self.system_instruction
            + f"\n\nCURRENT SESSION CONTEXT:\n{auth_status}"
            + f"\n\nContext block:\n{json.dumps(self.context, indent=2)}"
            + "\n\nAdhere to this context exactly."
        )

        history_for_gemini = self.history + [{"role": "user", "parts": [{"text": user_input}]}]

        try:
            response = self.client.models.generate_content(
                model=self.model_id,
                config={
                    'system_instruction': prompt,
                    'response_mime_type': 'application/json',
                },
                contents=history_for_gemini,
            )
            return response.text
        except Exception as e:
            logging.error(f"Gemini API Error: {e}")
            return None

    # ─────────────────────────────────────────────────────────────────────────
    # Summarizer call — converts raw tool JSON to friendly reply
    # ─────────────────────────────────────────────────────────────────────────
    def _summarize_results(self, user_query: str, tool_results):
        try:
            # Prepare results for LLM (clean HTML, format prices, etc.)
            clean_results = self._prepare_results_for_llm(tool_results)
            
            summarizer_input = (
                f"User Request: {user_query}\n\n"
                f"Curated Tool Results:\n{json.dumps(clean_results, indent=2, ensure_ascii=False)}"
            )

            response = self.client.models.generate_content(
                model=self.model_id,
                config={
                    'system_instruction': summarizer_prompt,
                    'temperature': 0.2,
                },
                contents=[{"role": "user", "parts": [{"text": summarizer_input}]}],
            )
            raw = response.text or ""

            # Always clean URLs — Gemini loves adding __ around them
            return self._clean_urls(raw)

        except Exception as e:
            logging.error(f"Summarization Error: {e}")
            # Fallback — return clean JSON, never raw with __ URLs
            return json.dumps(tool_results, indent=2, ensure_ascii=False)

    # ─────────────────────────────────────────────────────────────────────────
    # Product Card Injection — Manually appends cards from tool results
    # ─────────────────────────────────────────────────────────────────────────
    def _inject_product_cards(self, friendly_response, tool_results):
        """
        Scans results for product data and appends [PRODUCT_CARD] blocks.
        """
        if not tool_results or not isinstance(tool_results, (dict, list)):
            return friendly_response

        # Flatten results if it's a dict of multi-tool results
        raw_items = []
        if isinstance(tool_results, dict):
            for val in tool_results.values():
                if isinstance(val, list):
                    raw_items.extend(val)
                elif isinstance(val, dict):
                    raw_items.append(val)
        else:
            raw_items = tool_results

        appended_cards = ""
        seen_ids = set()
        
        # We only want to show cards for things that look like products (have an 'id' and 'name')
        for item in raw_items:
            if not isinstance(item, dict) or "id" not in item or "name" not in item:
                continue
            
            p_id = item["id"]
            if p_id in seen_ids:
                continue
            seen_ids.add(p_id)

            # Skip variations to avoid showing multiple identical images in the carousel
            if item.get("is_variation") or item.get("parent_id"):
                continue

            # Extract fields with better fallbacks
            name = item.get("name")
            desc = item.get("description") or item.get("short_description") or ""
            # Clean HTML from description
            desc = re.sub('<[^<]+?>', '', desc).strip()
            # If description is empty or just repeats the name, try to keep it empty to let the UI handle it cleanly
            if not desc or desc.lower() == name.lower():
                desc = ""
            
            reg_price = str(item.get("regular_price") or "")
            sal_price = str(item.get("sale_price") or "")
            
            # If sale_price is same as reg_price, or missing, default to items[price]
            if not sal_price or sal_price == reg_price:
                sal_price = str(item.get("price") or reg_price)

            sku = item.get("sku") or ""
            
            # Image handling (Vector DB uses 'image', standard API uses 'images')
            img_url = item.get("image") or item.get("image_url") or ""
            if not img_url:
                images = item.get("images")
                if images and isinstance(images, list) and len(images) > 0:
                    img_url = images[0] if isinstance(images[0], str) else images[0].get("src")
                    
            # Build card data
            card_data = {
                "id": p_id,
                "name": name,
                "description": desc,
                "regular_price": reg_price,
                "sale_price": sal_price,
                "sku": sku,
                "image_url": img_url,
                "permalink": item.get("permalink") or "",
                "attributes": item.get("attributes", [])
            }
            
            appended_cards += f"\n\n[PRODUCT_CARD]\n{json.dumps(card_data, indent=2)}\n[/PRODUCT_CARD]"

        return friendly_response + appended_cards

    # ─────────────────────────────────────────────────────────────────────────
    # Context updater
    # ─────────────────────────────────────────────────────────────────────────
    def _update_context(self, tool_name: str, result):
        if tool_name in ["list_products", "search_products", "get_product_details",
                         "get_products_by_brand", "search_products_by_brand"]:
            items = result if isinstance(result, list) else [result] if isinstance(result, dict) else []
            for item in items:
                if isinstance(item, dict) and "id" in item and "name" in item:
                    self.context["last_products"] = [
                        p for p in self.context["last_products"] if p["id"] != item["id"]
                    ]
                    self.context["last_products"].append({"id": item["id"], "name": item["name"]})
            self.context["last_products"] = self.context["last_products"][-10:]

        elif tool_name in ["view_cart", "add_to_cart", "remove_from_cart"]:
            if isinstance(result, dict) and "line_items" in result:
                self.context["cart"] = [
                    {"product_id": i.get("product_id"), "qty": i.get("quantity")}
                    for i in result["line_items"]
                ]
            elif isinstance(result, dict) and result.get("message") == "Cart is empty.":
                self.context["cart"] = []

        elif tool_name == "list_categories":
            if isinstance(result, list):
                self.context["categories"] = [
                    {"id": c.get("id"), "name": c.get("name")} for c in result
                ]

        elif tool_name == "list_brands":
            if isinstance(result, list):
                self.context["brands"] = [
                    {"id": b.get("id"), "name": b.get("name"), "slug": b.get("slug")} for b in result
                ]

        logging.info(f"Updated Session Memory: {self.context}")

    # ─────────────────────────────────────────────────────────────────────────
    # Main handler
    # ─────────────────────────────────────────────────────────────────────────
    def handle_query(self, user_input: str, session_context: dict = None):
        logging.info(f"User query: {user_input} | Session: {session_context}")

        # 1. Router call
        raw_response = self._call_gemini(user_input, session_context)
        if not raw_response:
            return "Gemini API is not responding."

        logging.info(f"Gemini raw response: {raw_response}")

        try:
            data = json.loads(raw_response)

            # ── Multi-tool ─────────────────────────────────────────────────
            if "tools" in data and isinstance(data["tools"], list):
                all_results = {}
                for i, call in enumerate(data["tools"]):
                    t_name = call.get("tool") or call.get("name")
                    t_args = call.get("args", {})
                    if not t_name or t_name not in self.available_tools:
                        continue
                    logging.info(f"Multi-tool [{i+1}]: {t_name} args={t_args}")

                    if t_name in self.AUTHENTICATED_TOOLS:
                        if not (session_context and session_context.get("is_logged_in")):
                            all_results[f"{i+1}_{t_name}"] = {"error": "Login required."}
                            continue
                        t_args["session_id"] = session_context.get("session_id", "default")

                    try:
                        res = self.available_tools[t_name](**t_args)
                        self._update_context(t_name, res)
                        all_results[f"{i+1}_{t_name}"] = res
                    except Exception as e:
                        logging.error(f"Multi-tool error {t_name}: {e}")
                        all_results[f"{i+1}_{t_name}"] = {"error": str(e)}

                if all_results:
                    friendly = self._summarize_results(user_input, all_results)
                    # Inject product cards manually
                    friendly = self._inject_product_cards(friendly, all_results)
                    self.history.append({"role": "user",  "parts": [{"text": user_input}]})
                    self.history.append({"role": "model", "parts": [{"text": friendly}]})
                    return friendly

            # ── Single tool ────────────────────────────────────────────────
            tool_name = data.get("tool")
            if tool_name:
                args = data.get("args", {})

                if tool_name not in self.available_tools:
                    return f"Error: unknown tool '{tool_name}'."

                logging.info(f"Tool: {tool_name} args={args}")

                if tool_name in self.AUTHENTICATED_TOOLS:
                    if not (session_context and session_context.get("is_logged_in")):
                        res      = {"error": "Login required to use cart features."}
                        friendly = self._summarize_results(user_input, {tool_name: res})
                        self.history.append({"role": "user",  "parts": [{"text": user_input}]})
                        self.history.append({"role": "model", "parts": [{"text": friendly}]})
                        return friendly
                    args["session_id"] = session_context.get("session_id", "default")

                try:
                    result   = self.available_tools[tool_name](**args)
                    self._update_context(tool_name, result)
                    friendly = self._summarize_results(user_input, result)
                    # Inject product cards manually
                    friendly = self._inject_product_cards(friendly, result)
                    self.history.append({"role": "user",  "parts": [{"text": user_input}]})
                    self.history.append({"role": "model", "parts": [{"text": friendly}]})
                    return friendly
                except Exception as e:
                    logging.error(f"Tool execution error: {e}")
                    return f"Error executing {tool_name}: {str(e)}"

            # ── Direct response (greetings etc.) ───────────────────────────
            if "response" in data:
                resp = self._clean_urls(data["response"])
                self.history.append({"role": "user",  "parts": [{"text": user_input}]})
                self.history.append({"role": "model", "parts": [{"text": resp}]})
                return resp

            return self._clean_urls(raw_response)

        except json.JSONDecodeError:
            cleaned = self._clean_urls(raw_response)
            self.history.append({"role": "user",  "parts": [{"text": user_input}]})
            self.history.append({"role": "model", "parts": [{"text": cleaned}]})
            return cleaned


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    orch = GeminiOrchestrator()
    print(orch.handle_query("List my products"))