import os
import logging
import json
from qdrant_client import QdrantClient
from qdrant_client import models
from fastembed import TextEmbedding
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configurations ---
COLLECTION_NAME = "products"
BI_ENCODER_MODEL = "BAAI/bge-small-en-v1.5"
# FastEmbed doesn't have a direct CrossEncoder equivalent in the same package.
# We will rely on Bi-Encoder scores for now or use a different reranking approach later if needed.

# Qdrant Setup
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_URL = os.getenv("QDRANT_CLUSTER_KEY")

# Initialize models (cached)
_bi_encoder = None
_qdrant_client = None

def get_qdrant_client():
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    return _qdrant_client

def get_models():
    global _bi_encoder
    if _bi_encoder is None:
        logging.info(f"Loading Bi-Encoder: {BI_ENCODER_MODEL}")
        _bi_encoder = TextEmbedding(BI_ENCODER_MODEL)
    return _bi_encoder

def search_products_vector(query: str, max_price: float = None, category_id: int = None, in_stock: bool = True, top_k: int = 5):
    """
    Semantic search for products with metadata filtering and cross-encoder re-ranking.
    """
    logging.info(f"Vector search for: '{query}' (max_price: {max_price}, cat: {category_id}, in_stock: {in_stock})")
    
    try:
        client = get_qdrant_client()
        bi_encoder = get_models()
        
        # 1. Generate Query Vector
        # fastembed.embed returns a generator, so we wrap it in a list
        query_vector = list(bi_encoder.embed([query]))[0].tolist()
        
        # 2. Build Filters
        must_conditions = []
        if in_stock:
            must_conditions.append(models.FieldCondition(key="in_stock", match=models.MatchValue(value=True)))
        
        if max_price is not None:
            must_conditions.append(models.FieldCondition(key="price", range=models.Range(lte=float(max_price))))
            
        if category_id is not None:
            must_conditions.append(models.FieldCondition(key="category_ids", match=models.MatchValue(value=int(category_id))))
            
        filter_obj = models.Filter(must=must_conditions) if must_conditions else None
        
        # 3. Retrieve Results from Qdrant
        search_results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            query_filter=filter_obj,
            limit=top_k
        ).points
        
        if not search_results:
            return []
            
        # 4. Format and Return Results
        final_results = []
        for res in search_results:
            p = res.payload
            final_results.append({
                "id":            p.get("id"),
                "name":          p.get("name"),
                "currency":      p.get("currency"),
                "price":         p.get("price"),
                "regular_price": p.get("regular_price"),
                "sale_price":    p.get("sale_price"),
                "sku":           p.get("sku"),
                "permalink":     p.get("permalink"),
                "in_stock":      p.get("in_stock"),
                "image":         p.get("image"),
                "short_description": p.get("short_description"),
                "description":   p.get("description"),
                "is_variation":  p.get("is_variation"),
                "parent_id":     p.get("parent_id"),
                "attributes":    p.get("attributes"),
                "relevance_score": float(res.score)
            })
            
        return final_results
        
    except Exception as e:
        logging.error(f"Error in vector search: {e}")
        return {"error": str(e)}

def get_products_by_brand(brand_slug: str):
    """Retrieves products filtered by brand via Vector DB."""
    logging.info(f"Fetching products for brand: {brand_slug}")
    try:
        return search_products_by_brand(brand_slug, query="", top_k=20)
    except Exception as e:
        return {"error": str(e)}

def search_products_by_brand(brand: str, query: str = "", top_k: int = 5):
    """
    Search for products by brand slug, with optional semantic query.
    """
    logging.info(f"Searching for products by brand: '{brand}' (query: '{query}')")
    
    try:
        client = get_qdrant_client()
        
        # 1. Build Filter
        must_conditions = [
            models.FieldCondition(key="brands", match=models.MatchValue(value=brand.lower()))
        ]
        filter_obj = models.Filter(must=must_conditions)
        
        # 2. Case: Pure Brand Filter (No Semantic Query)
        if not query:
            res, _ = client.scroll(
                collection_name=COLLECTION_NAME,
                scroll_filter=filter_obj,
                limit=top_k,
                with_payload=True,
                with_vectors=False
            )
            return [{
                "id": p.payload.get("id"),
                "name": p.payload.get("name"),
                "price": p.payload.get("price"),
                "regular_price": p.payload.get("regular_price"),
                "sale_price": p.payload.get("sale_price"),
                "permalink": p.payload.get("permalink"),
                "currency": p.payload.get("currency"),
                "in_stock": p.payload.get("in_stock"),
                "image": p.payload.get("image"),
                "description": p.payload.get("description") or p.payload.get("short_description")
            } for p in res]

        # 3. Case: Brand Filter + Semantic Query
        bi_encoder = get_models()
        query_vector = list(bi_encoder.embed([query]))[0].tolist()
        
        search_results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            query_filter=filter_obj,
            limit=top_k
        ).points
        
        if not search_results:
            return []
            
        return [{
            "id": res.payload.get("id"),
            "name": res.payload.get("name"),
            "price": res.payload.get("price"),
            "regular_price": res.payload.get("regular_price"),
            "sale_price": res.payload.get("sale_price"),
            "permalink": res.payload.get("permalink"),
            "currency": res.payload.get("currency"),
            "in_stock": res.payload.get("in_stock"),
            "image": res.payload.get("image"),
            "description": res.payload.get("description") or res.payload.get("short_description"),
            "relevance_score": float(res.score)
        } for res in search_results]
        
    except Exception as e:
        logging.error(f"Error in search_products_by_brand: {e}")
        return {"error": str(e)}

def list_products_vector(category_id: int = None, limit: int = 10):
    """
    List products from Vector DB using scroll (efficient for simple listing).
    """
    logging.info(f"Listing products via scroll (cat: {category_id}, limit: {limit})")
    try:
        client = get_qdrant_client()
        
        must_conditions = []
        if category_id is not None:
             must_conditions.append(models.FieldCondition(key="category_ids", match=models.MatchValue(value=int(category_id))))
        
        filter_obj = models.Filter(must=must_conditions) if must_conditions else None
        
        # Scroll is better for listing than query_points if no vector is involved
        res, _ = client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=filter_obj,
            limit=limit,
            with_payload=True,
            with_vectors=False
        )
        
        return [{
            "id": p.payload.get("id"),
            "name": p.payload.get("name"),
            "price": p.payload.get("price"),
            "regular_price": p.payload.get("regular_price"),
            "sale_price": p.payload.get("sale_price"),
            "permalink": p.payload.get("permalink"),
            "currency": p.payload.get("currency"),
            "in_stock": p.payload.get("in_stock"),
            "image": p.payload.get("image"),
            "description": p.payload.get("description"),
            "is_variation": p.payload.get("is_variation"),
            "parent_id": p.payload.get("parent_id"),
            "attributes": p.payload.get("attributes")
        } for p in res]
    except Exception as e:
        logging.error(f"Error listing products from vector db: {e}")
        return {"error": str(e)}

def get_product_details_vector(product_id_or_name):
    """
    Get detailed product info from Vector DB by ID or Name.
    """
    logging.info(f"Getting product details for: {product_id_or_name}")
    try:
        client = get_qdrant_client()
        
        # 1. Try numeric ID lookup first
        if str(product_id_or_name).isdigit():
            res = client.query_points(
                collection_name=COLLECTION_NAME,
                query_filter=models.Filter(
                    must=[models.FieldCondition(key="id", match=models.MatchValue(value=int(product_id_or_name)))]
                ),
                limit=1
            ).points
            if res:
                return res[0].payload
        
        # 2. Fallback to semantic search for name
        bi_encoder = get_models()
        query_vector = list(bi_encoder.embed([str(product_id_or_name)]))[0].tolist()
        
        res = client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            limit=1
        ).points
        
        if res:
            return res[0].payload
            
        return {"error": f"Product '{product_id_or_name}' not found in vector database."}
    except Exception as e:
        logging.error(f"Error getting product details from vector db: {e}")
        return {"error": str(e)}

if __name__ == "__main__":
    # Test block
    print("--- Testing Search ---")
    print(json.dumps(search_products_vector("comfortable for genz"), indent=2))
    
    print("\n--- Testing List ---")
    print(json.dumps(list_products_vector(limit=2), indent=2))
    
    print("\n--- Testing Details (ID) ---")
    print(json.dumps(get_product_details_vector(17), indent=2))
    
    print("\n--- Testing Details (Name) ---")
    print(json.dumps(get_product_details_vector("socks"), indent=2))
