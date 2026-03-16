import os
import logging
import re
import requests
from requests.auth import HTTPBasicAuth
from qdrant_client import QdrantClient
from qdrant_client import models
from fastembed import TextEmbedding
from dotenv import load_dotenv
from pathlib import Path

# Load .env from project root regardless of where script is run from
load_dotenv(Path(__file__).parent.parent / '.env')
load_dotenv()  # fallback for running from root

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

COLLECTION_NAME      = "products"
EMBEDDING_MODEL_NAME = "BAAI/bge-small-en-v1.5"

QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_URL     = os.getenv("QDRANT_URL") or os.getenv("QDRANT_CLUSTER_KEY")

WOO_URL    = os.getenv("WOO_URL", "http://woo-test.local")
WOO_KEY    = os.getenv("WOO_CONSUMER_KEY")
WOO_SECRET = os.getenv("WOO_CONSUMER_SECRET")

WOO_LIVE_LINK_USER = os.getenv("WOO_LIVE_LINK_USER", "")
WOO_LIVE_LINK_PASS = os.getenv("WOO_LIVE_LINK_PASS", "")

if not WOO_URL.startswith("http"):
    WOO_URL = f"https://{WOO_URL}"


def clean_html(text):
    if not text:
        return ""
    return re.sub('<[^<]+?>', '', text)


def woo_get(endpoint, params=None):
    url        = f"{WOO_URL.rstrip('/')}/wp-json/wc/v3/{endpoint}"
    all_params = {"consumer_key": WOO_KEY, "consumer_secret": WOO_SECRET}
    if params:
        all_params.update(params)
    auth = HTTPBasicAuth(WOO_LIVE_LINK_USER, WOO_LIVE_LINK_PASS) if WOO_LIVE_LINK_USER else None
    logging.info(f"GET {url}")
    return requests.get(url, params=all_params, auth=auth, verify=False, timeout=15)


def sync_products():
    logging.info("Starting product synchronization to Qdrant...")

    qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    model         = TextEmbedding(EMBEDDING_MODEL_NAME)

    # Create collection if needed
    collections = qdrant_client.get_collections().collections
    if not any(c.name == COLLECTION_NAME for c in collections):
        logging.info(f"Creating collection '{COLLECTION_NAME}'...")
        qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
        )

    # Ensure indexes
    logging.info("Checking payload indexes...")
    for field_name, field_schema in [
        ("in_stock",     models.PayloadSchemaType.BOOL),
        ("price",        models.PayloadSchemaType.FLOAT),
        ("id",           models.PayloadSchemaType.INTEGER),
        ("category_ids", models.PayloadSchemaType.INTEGER),
        ("brands",       models.PayloadSchemaType.KEYWORD),
    ]:
        try:
            qdrant_client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name=field_name,
                field_schema=field_schema,
            )
        except Exception as e:
            logging.warning(f"Index '{field_name}': {e}")

    # Fetch and sync page by page
    page = 1

    while True:
        logging.info(f"Fetching products page {page}...")
        response = woo_get("products", {"per_page": 50, "page": page})

        if response.status_code == 404:
            logging.info("404 — end of catalog.")
            break
        if response.status_code != 200:
            logging.error(f"Error {response.status_code}: {response.text[:300]}")
            break

        products = response.json()
        if not products:
            logging.info("Empty page — sync complete.")
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

            brand_text   = " ".join(brands)
            text_content = f"{brand_text} {name}. {description}".strip()
            embedding    = list(model.embed([text_content]))[0].tolist()

            all_points.append(models.PointStruct(
                id=p_id,
                vector=embedding,
                payload={
                    "id":            p_id,
                    "name":          name,
                    "description":   description,
                    "price":         price,
                    "regular_price": float(p.get("regular_price") or price),
                    "sale_price":    float(p.get("sale_price") or 0.0),
                    "sku":           p.get("sku") or "",
                    "permalink":     p.get("permalink") or "",
                    "in_stock":      in_stock,
                    "category_ids":  categories,
                    "brands":        brands,
                    "image":         image_url,
                    "is_variation":  False,
                }
            ))

            if p.get("type") == "variable":
                logging.info(f"Fetching variations for '{name}' (ID: {p_id})...")
                var_response = woo_get(f"products/{p_id}/variations")

                if var_response.status_code == 200:
                    for v in var_response.json():
                        v_id        = v.get("id")
                        qdrant_v_id = 1000000 + v_id
                        v_price     = float(v.get("price") or 0.0)
                        v_stock     = v.get("stock_status") == "instock"
                        v_image     = v.get("image", {}).get("src") or image_url
                        v_attrs     = v.get("attributes", [])
                        attr_text   = ", ".join([f"{a.get('name')}: {a.get('option')}" for a in v_attrs])
                        v_name      = f"{name} ({attr_text})"
                        v_desc      = clean_html(v.get("description", "")) or description
                        v_text      = f"{brand_text} {v_name}. {v_desc}".strip()
                        v_embedding = list(model.embed([v_text]))[0].tolist()

                        all_points.append(models.PointStruct(
                            id=qdrant_v_id,
                            vector=v_embedding,
                            payload={
                                "id":            v_id,
                                "parent_id":     p_id,
                                "name":          v_name,
                                "description":   v_desc[:300],
                                "price":         v_price,
                                "regular_price": float(v.get("regular_price") or v_price),
                                "sale_price":    float(v.get("sale_price") or 0.0),
                                "sku":           v.get("sku") or "",
                                "permalink":     v.get("permalink") or "",
                                "in_stock":      v_stock,
                                "category_ids":  categories,
                                "brands":        brands,
                                "image":         v_image,
                                "is_variation":  True,
                                "attributes":    v_attrs,
                            }
                        ))
                elif var_response.status_code != 404:
                    logging.warning(f"Variations error for {p_id}: {var_response.status_code}")

        if all_points:
            logging.info(f"Upserting {len(all_points)} points for page {page}...")
            qdrant_client.upsert(collection_name=COLLECTION_NAME, wait=True, points=all_points)

        page += 1

    logging.info("Sync complete! ✅")


if __name__ == "__main__":
    sync_products()