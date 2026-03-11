import os
import logging
import re
from woocommerce import API
from qdrant_client import QdrantClient
from qdrant_client import models
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configurations ---
COLLECTION_NAME = "products"
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"

# Qdrant Setup
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_URL = os.getenv("QDRANT_CLUSTER_KEY")

# WooCommerce Setup
WOO_URL = os.getenv("WOO_URL", "http://woo-test.local")
WOO_KEY = os.getenv("WOO_CONSUMER_KEY")
WOO_SECRET = os.getenv("WOO_CONSUMER_SECRET")

if not WOO_URL.startswith("http"):
    WOO_URL = f"http://{WOO_URL}"

def get_wcapi():
    return API(
        url=WOO_URL,
        consumer_key=WOO_KEY,
        consumer_secret=WOO_SECRET,
        wp_api=True,
        version="wc/v3",
        timeout=15,
        verify_ssl=False
    )

def clean_html(text):
    if not text: return ""
    return re.sub('<[^<]+?>', '', text)

def sync_products():
    logging.info("Starting product synchronization to Qdrant...")
    
    # 1. Initialize Clients
    wcapi = get_wcapi()
    qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    
    # 2. Recreate Collection (Optional: for fresh start)
    # Check if collection exists, if not create it
    collections = qdrant_client.get_collections().collections
    exists = any(c.name == COLLECTION_NAME for c in collections)
    
    if not exists:
        logging.info(f"Creating collection '{COLLECTION_NAME}'...")
        qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=models.VectorParams(size=384, distance=models.Distance.COSINE),
        )

    # Ensure Payload Indexes exist
    logging.info("Checking payload indexes...")
    # This will silently skip if they already exist in newer client versions
    try:
        qdrant_client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="in_stock",
            field_schema=models.PayloadSchemaType.BOOL,
        )
        qdrant_client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="price",
            field_schema=models.PayloadSchemaType.FLOAT,
        )
        qdrant_client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="id",
            field_schema=models.PayloadSchemaType.INTEGER,
        )
        qdrant_client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="category_ids",
            field_schema=models.PayloadSchemaType.INTEGER,
        )
        qdrant_client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="brands",
            field_schema=models.PayloadSchemaType.KEYWORD,
        )
    except Exception as e:
        logging.warning(f"Note on indexes: {e}")
    
    # 3. Fetch Products from WooCommerce
    page = 1
    all_points = []
    
    while True:
        logging.info(f"Fetching products page {page}...")
        response = wcapi.get("products", params={"per_page": 50, "page": page})
        
        if response.status_code != 200:
            logging.error(f"Error fetching products: {response.text}")
            break
            
        products = response.json()
        if not products:
            break
            
        for p in products:
            p_id = p.get("id")
            name = p.get("name", "")
            description = clean_html(p.get("description", ""))
            price = float(p.get("price") or 0.0)
            in_stock = p.get("stock_status") == "instock"
            categories = [c.get("id") for c in p.get("categories", [])]
            brands = [b.get("slug") for b in p.get("brands", [])]
            image_url = p.get("images")[0].get("src") if p.get("images") else ""
            
            # Text to embed
            text_content = f"{name}. {description}"
            embedding = model.encode(text_content).tolist()
            
            all_points.append(
                models.PointStruct(
                    id=p_id,
                    vector=embedding,
                    payload={
                        "id": p_id,
                        "name": name,
                        "description": description[:300], # Store preview
                        "price": price,
                        "in_stock": in_stock,
                        "category_ids": categories,
                        "brands": brands,
                        "image": image_url,
                        "is_variation": False
                    }
                )
            )

            # --- Fetch Variations if it's a variable product ---
            if p.get("type") == "variable":
                logging.info(f"Fetching variations for product '{name}' (ID: {p_id})...")
                var_response = wcapi.get(f"products/{p_id}/variations")
                if var_response.status_code == 200:
                    variations = var_response.json()
                    for v in variations:
                        v_id = v.get("id")
                        # Synthetic ID for Qdrant (offset to avoid collision with parent IDs)
                        # Parent IDs are usually small, 1,000,000 is a safe gap.
                        qdrant_v_id = 1000000 + v_id 
                        
                        v_price = float(v.get("price") or 0.0)
                        v_stock = v.get("stock_status") == "instock"
                        v_image = v.get("image", {}).get("src") or image_url
                        
                        # Format attributes for context (e.g., "Size: Large, Color: Blue")
                        v_attrs = v.get("attributes", [])
                        attr_text = ", ".join([f"{a.get('name')}: {a.get('option')}" for a in v_attrs])
                        
                        v_name = f"{name} ({attr_text})"
                        v_description = clean_html(v.get("description", "")) or description
                        
                        # Specialized embedding for variation
                        v_text_content = f"{v_name}. {v_description}"
                        v_embedding = model.encode(v_text_content).tolist()
                        
                        all_points.append(
                            models.PointStruct(
                                id=qdrant_v_id,
                                vector=v_embedding,
                                payload={
                                    "id": v_id,
                                    "parent_id": p_id,
                                    "name": v_name,
                                    "description": v_description[:300],
                                    "price": v_price,
                                    "in_stock": v_stock,
                                    "category_ids": categories,
                                    "brands": brands,
                                    "image": v_image,
                                    "is_variation": True,
                                    "attributes": v_attrs
                                }
                            )
                        )
                else:
                    logging.warning(f"Failed to fetch variations for product {p_id}: {var_response.text}")
            
        page += 1
        
    # 4. Upsert to Qdrant
    if all_points:
        logging.info(f"Upserting {len(all_points)} total points (products + variations) to Qdrant...")
        qdrant_client.upsert(
            collection_name=COLLECTION_NAME,
            wait=True,
            points=all_points
        )
        logging.info("Sync complete!")
    else:
        logging.warning("No products found to sync.")

if __name__ == "__main__":
    sync_products()
