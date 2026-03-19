import os
import json
import requests
import urllib3
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class WooCommerceMCPClient:
    """
    Client to interact with the WooCommerce MCP HTTP endpoint directly.

    Auth spec (official docs):
        Header: X-MCP-API-Key: ck_your_consumer_key:cs_your_consumer_secret

    Required .env variables:
        WOO_URL              = woo-test.local  (or https://yourstore.com)
        WOO_CONSUMER_KEY     = ck_xxxxxxxxxxxx
        WOO_CONSUMER_SECRET  = cs_xxxxxxxxxxxx

    WordPress requirement for local dev (add to functions.php or a plugin):
        add_filter( 'woocommerce_mcp_allow_insecure_transport', '__return_true' );
    """

    def __init__(self, config: Optional[dict] = None):
        """
        :param config: Optional per-request store credentials dict with keys:
                       'woo_url', 'consumer_key', 'consumer_secret'.
                       When None, falls back to environment variables (local dev).
        """
        if config:
            woo_url         = config.get("woo_url", os.getenv("WOO_URL", "woo-test.local"))
            consumer_key    = config.get("consumer_key", "")
            consumer_secret = config.get("consumer_secret", "")
        else:
            woo_url         = os.getenv("WOO_URL", "woo-test.local")
            consumer_key    = os.getenv("WOO_CONSUMER_KEY", "")
            consumer_secret = os.getenv("WOO_CONSUMER_SECRET", "")

        if not woo_url.startswith(("http://", "https://")):
            woo_url = f"https://{woo_url}"

        self.endpoint = f"{woo_url}/wp-json/woocommerce/mcp"

        if not consumer_key or not consumer_secret:
            raise ValueError(
                "WooCommerce consumer_key and consumer_secret are required "
                "(pass a config dict or set WOO_CONSUMER_KEY / WOO_CONSUMER_SECRET in .env)"
            )

        self.headers = {
            "Content-Type": "application/json",
            "X-MCP-API-Key": f"{consumer_key}:{consumer_secret}",
        }

        # Handle Tunnel / Live Link Authentication (still env-based — shared infra)
        live_user = os.getenv("WOO_LIVE_LINK_USER", "")
        live_pass = os.getenv("WOO_LIVE_LINK_PASS", "")
        self.auth = (live_user, live_pass) if live_user else None

        self.session_id = None
        self.verify = False

    def _initialize_session(self):
        """Official MCP initialization to get a session ID."""
        payload = {
            "jsonrpc": "2.0",
            "id":      1,
            "method":  "initialize",
            "params":  {
                "protocolVersion": "2024-11-05",
                "capabilities":    {},
                "clientInfo":      {
                    "name":    "woo-mcp-client",
                    "version": "1.0.0"
                }
            }
        }
        try:
            # We don't use _send_request here to avoid recursion
            response = requests.post(
                self.endpoint,
                json=payload,
                headers=self.headers,
                auth=self.auth,
                verify=self.verify,
                timeout=15
            )
            
            # Fallback for plain permalinks during init
            if response.status_code in [404, 405]:
                base_url = self.endpoint.split("/wp-json")[0]
                fallback_url = f"{base_url}/index.php?rest_route=/woocommerce/mcp"
                response = requests.post(
                    fallback_url,
                    json=payload,
                    headers=self.headers,
                    auth=self.auth,
                    verify=self.verify,
                    timeout=15,
                )

            response.raise_for_status()
            self.session_id = response.headers.get("Mcp-Session-Id")
            if self.session_id:
                self.headers["Mcp-Session-Id"] = self.session_id
                print(f"[debug] MCP Session Initialized: {self.session_id}")
            else:
                print("[warning] No Mcp-Session-Id returned during initialization.")
        except Exception as e:
            print(f"[error] Failed to initialize MCP session: {e}")
            raise e

    def _send_request(self, payload: dict) -> dict:
        """
        Send a JSON-RPC 2.0 request to the WooCommerce MCP endpoint.
        Includes plain-permalink fallback and clear error messages.
        """
        if not self.session_id:
            self._initialize_session()

        try:
            response = requests.post(
                self.endpoint,
                json=payload,
                headers=self.headers,   # ✅ No auth= kwarg — header carries auth
                auth=self.auth,
                verify=self.verify,
                timeout=15,
            )

            # ✅ FIX 2: Fallback for plain permalinks (?rest_route=...)
            if response.status_code in (404, 405):
                base_url = self.endpoint.split("/wp-json")[0]
                fallback_url = f"{base_url}/index.php?rest_route=/woocommerce/mcp"
                print(f"[debug] {response.status_code} on primary endpoint, "
                      f"trying fallback: {fallback_url}")
                response = requests.post(
                    fallback_url,
                    json=payload,
                    headers=self.headers,
                    auth=self.auth,
                    verify=self.verify,
                    timeout=15,
                )

            response.raise_for_status()
            return response.json()

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code
            body   = e.response.text[:300]

            if status == 401:
                raise Exception(
                    "401 Unauthorized — check WOO_CONSUMER_KEY / WOO_CONSUMER_SECRET "
                    "and that the key has the correct read/write permissions."
                ) from e
            if status == 404:
                raise Exception(
                    f"404 Not Found — MCP endpoint not registered at {self.endpoint}.\n"
                    "Checklist:\n"
                    "  1. WooCommerce MCP feature flag enabled?\n"
                    "     wp option update woocommerce_feature_mcp_integration_enabled yes\n"
                    "  2. Permalinks flushed? (WP Admin → Settings → Permalinks → Save)\n"
                    "  3. WooCommerce 10.3+ installed?"
                ) from e
            if status == 405:
                raise Exception(
                    f"405 Method Not Allowed at {self.endpoint}.\n"
                    "Most likely cause: HTTPS transport enforcement is blocking the request.\n"
                    "For local dev, add this to functions.php:\n"
                    "  add_filter('woocommerce_mcp_allow_insecure_transport', '__return_true');\n"
                    f"Response body: {body}"
                ) from e
            if status == 502:
                raise Exception(
                    "502 Bad Gateway — restart your Local by Flywheel site "
                    "or check the nginx/router logs."
                ) from e

            raise Exception(f"HTTP {status}: {body}") from e

        except requests.exceptions.SSLError as e:
            raise Exception(
                "SSL error on local site. verify=False should handle self-signed certs. "
                "Also add the insecure transport filter in WordPress:\n"
                "  add_filter('woocommerce_mcp_allow_insecure_transport', '__return_true');"
            ) from e

        except requests.exceptions.ConnectionError as e:
            raise Exception(
                f"Cannot connect to {self.endpoint}. "
                "Is the Local site running?"
            ) from e

    def get_tools(self) -> list:
        """Fetch the list of available MCP tools from the server."""
        payload = {
            "jsonrpc": "2.0",
            "id":      1,
            "method":  "tools/list",
            "params":  {},
        }
        result = self._send_request(payload)
        return result.get("result", {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict) -> dict:
        """Invoke a specific MCP tool by name."""
        payload = {
            "jsonrpc": "2.0",
            "id":      2,
            "method":  "tools/call",
            "params":  {
                "name":      name,
                "arguments": arguments,
            },
        }
        result = self._send_request(payload)
        return result.get("result", {})