import os
import logging
import re
import requests
from requests.auth import HTTPBasicAuth
from qdrant_client import QdrantClient
from qdrant_client import models
from fastembed import TextEmbedding
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configurations ---
COLLECTION_NAME      = "products"
EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"

# Qdrant Setup
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_URL     = os.getenv("QDRANT_CLUSTER_KEY")

# WooCommerce Setup
WOO_URL    = os.getenv("WOO_URL", "http://woo-test.local")
WOO_KEY    = os.getenv("WOO_CONSUMER_KEY")
WOO_SECRET = os.getenv("WOO_CONSUMER_SECRET")

# Live Link Basic Auth (needed when WOO_URL is a localsite.io tunnel)
WOO_LIVE_LINK_USER = os.getenv("WOO_LIVE_LINK_USER", "")
WOO_LIVE_LINK_PASS = os.getenv("WOO_LIVE_LINK_PASS", "")

if not WOO_URL.startswith("http"):
    WOO_URL = f"https://{WOO_URL}"


def clean_html(text):
    if not text:
        return ""
    return re.sub('<[^<]+?>', '', text)


def woo_get(endpoint, params=None):
    """
    Direct requests-based WooCommerce API call.
    Passes WC consumer keys as query params (avoids conflict with Basic Auth).
    Passes Live Link Basic Auth in headers when WOO_LIVE_LINK_USER is set.
    """
    base_url = WOO_URL.rstrip('/')
    url      = f"{base_url}/wp-json/wc/v3/{endpoint}"

    # WooCommerce OAuth via query params
    all_params = {
        "consumer_key":    WOO_KEY,
        "consumer_secret": WOO_SECRET,
    }
    if params:
        all_params.update(params)

    # Basic Auth for Live Link tunnel
    auth = HTTPBasicAuth(WOO_LIVE_LINK_USER, WOO_LIVE_LINK_PASS) \
           if WOO_LIVE_LINK_USER else None

    response = requests.get(
        url,
        params=all_params,
        auth=auth,
        verify=False,
        timeout=15
    )
    logging.info(f"DEBUG: calling {url} with params {all_params.keys()}")
    return response


def sync_products():
    logging.info("Starting product synchronization to Qdrant...")

    # 1. Initialize Clients
    qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    model         = TextEmbedding(EMBEDDING_MODEL_NAME)

    # 2. Create collection if it doesn't exist
    collections = qdrant_client.get_collections().collections
    exists      = any(c.name == COLLECTION_NAME for c in collections)

    if not exists:
        logging.info(f"Creating collection '{COLLECTION_NAME}'...")
        qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
        )

    # 3. Ensure payload indexes
    logging.info("Checking payload indexes...")
    index_fields = [
        ("in_stock",     models.PayloadSchemaType.BOOL),
        ("price",        models.PayloadSchemaType.FLOAT),
        ("id",           models.PayloadSchemaType.INTEGER),
        ("category_ids", models.PayloadSchemaType.INTEGER),
        ("brands",       models.PayloadSchemaType.KEYWORD),
    ]
    for field_name, field_schema in index_fields:
        try:
            qdrant_client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name=field_name,
                field_schema=field_schema,
            )
        except Exception as e:
            logging.warning(f"Note on index '{field_name}': {e}")

    # 4. Fetch products from WooCommerce
    page       = 1

    while True:
        logging.info(f"Fetching products page {page}...")
        response = woo_get("products", {"per_page": 50, "page": page})
        
        if response.status_code == 404:
            logging.info(f"Page {page} not found (404). Treating as end of catalog.")
            break

        if response.status_code != 200:
            logging.error(f"Error fetching products: {response.status_code} — {response.text[:300]}")
            break
            
        products = response.json()
        if not products:
            break
            
        all_points = []
        for p in products:
            p_id        = p.get("id")
            name        = p.get("name", "")
            description = clean_html(p.get("description", ""))
            price       = float(p.get("price") or 0.0)
            in_stock    = p.get("stock_status") == "instock"
            categories  = [c.get("id") for c in p.get("categories", [])]
            brands      = [b.get("slug") for b in p.get("brands", [])]
            image_url   = p.get("images")[0].get("src") if p.get("images") else ""

            # Build embedding text — include brand for semantic search
            brand_text   = " ".join(brands)
            text_content = f"{brand_text} {name}. {description}".strip()
            embedding    = list(model.embed([text_content]))[0].tolist()

            all_points.append(
                models.PointStruct(
                    id=p_id,
                    vector=embedding,
                    payload={
                        "id":           p_id,
                        "name":         name,
                        "description":  description[:300],
                        "price":        price,
                        "in_stock":     in_stock,
                        "category_ids": categories,
                        "brands":       brands,
                        "image":        image_url,
                        "is_variation": False,
                    }
                )
            )

            # Fetch variations for variable products
            if p.get("type") == "variable":
                p_id        = p.get("id")
                logging.info(f"Fetching variations for '{p.get('name')}' (ID: {p_id})...")
                var_response = woo_get(f"products/{p_id}/variations")

                if var_response.status_code == 200:
                    variations = var_response.json()
                    for v in variations:
                        v_id      = v.get("id")
                        qdrant_v_id = 1000000 + v_id  # avoid ID collision with parent

                        v_price   = float(v.get("price") or 0.0)
                        v_stock   = v.get("stock_status") == "instock"
                        v_image   = v.get("image", {}).get("src") or image_url

                        v_attrs   = v.get("attributes", [])
                        attr_text = ", ".join([
                            f"{a.get('name')}: {a.get('option')}" for a in v_attrs
                        ])

                        v_name        = f"{name} ({attr_text})"
                        v_description = clean_html(v.get("description", "")) or description

                        v_text_content = f"{brand_text} {v_name}. {v_description}".strip()
                        v_embedding    = list(model.embed([v_text_content]))[0].tolist()

                        all_points.append(
                            models.PointStruct(
                                id=qdrant_v_id,
                                vector=v_embedding,
                                payload={
                                    "id":           v_id,
                                    "parent_id":    p_id,
                                    "name":         v_name,
                                    "description":  v_description[:300],
                                    "price":        v_price,
                                    "in_stock":     v_stock,
                                    "category_ids": categories,
                                    "brands":       brands,
                                    "image":        v_image,
                                    "is_variation": True,
                                    "attributes":   v_attrs,
                                }
                            )
                        )
                elif var_response.status_code == 404:
                    logging.warning(f"Variations endpoint for product {p_id} returned 404. Skipping.")
                else:
                    logging.warning(
                        f"Failed to fetch variations for product {p_id}: "
                        f"{var_response.status_code} {var_response.text[:200]}"
                    )

        # Upsert results for this page
        if all_points:
            logging.info(f"Upserting {len(all_points)} total points for page {page} to Qdrant...")
            qdrant_client.upsert(
                collection_name=COLLECTION_NAME,
                wait=True,
                points=all_points,
            )
        
        page += 1

    # 5. Upsert to Qdrant (This section is now redundant as upsert happens per page)
    # The original code had a final upsert here, but the new logic upserts per page.
    # Keeping the original final check for completeness, though it will likely be empty.
    # If the loop breaks early and all_points is not empty from the last page, it would be upserted.
    # However, all_points is reset per page, so this final check will always be on an empty list.
    # It's safer to remove this final block if the per-page upsert is the intended final behavior.
    # For now, removing the original final upsert block as it's replaced by per-page upsert.
    logging.info("Sync complete! ✅")


if __name__ == "__main__":
    sync_products()