import os
import logging
import json
from qdrant_client import QdrantClient
from qdrant_client import models
from sentence_transformers import SentenceTransformer, CrossEncoder
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Configurations ---
COLLECTION_NAME = "products"
BI_ENCODER_MODEL = "all-MiniLM-L6-v2"
CROSS_ENCODER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"

# Qdrant Setup
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY")
QDRANT_URL = os.getenv("QDRANT_CLUSTER_KEY")

# Initialize models (cached)
_bi_encoder = None
_cross_encoder = None
_qdrant_client = None

def get_qdrant_client():
    global _qdrant_client
    if _qdrant_client is None:
        _qdrant_client = QdrantClient(url=QDRANT_URL, api_key=QDRANT_API_KEY)
    return _qdrant_client

def get_models():
    global _bi_encoder, _cross_encoder
    if _bi_encoder is None:
        logging.info(f"Loading Bi-Encoder: {BI_ENCODER_MODEL}")
        _bi_encoder = SentenceTransformer(BI_ENCODER_MODEL)
    if _cross_encoder is None:
        logging.info(f"Loading Cross-Encoder: {CROSS_ENCODER_MODEL}")
        _cross_encoder = CrossEncoder(CROSS_ENCODER_MODEL)
    return _bi_encoder, _cross_encoder

def search_products_vector(query: str, max_price: float = None, category_id: int = None, in_stock: bool = True, top_k: int = 5):
    """
    Semantic search for products with metadata filtering and cross-encoder re-ranking.
    """
    logging.info(f"Vector search for: '{query}' (max_price: {max_price}, cat: {category_id}, in_stock: {in_stock})")
    
    try:
        client = get_qdrant_client()
        bi_encoder, cross_encoder = get_models()
        
        # 1. Generate Query Vector
        query_vector = bi_encoder.encode(query).tolist()
        
        # 2. Build Filters
        must_conditions = []
        if in_stock:
            must_conditions.append(models.FieldCondition(key="in_stock", match=models.MatchValue(value=True)))
        
        if max_price is not None:
            must_conditions.append(models.FieldCondition(key="price", range=models.Range(lte=float(max_price))))
            
        if category_id is not None:
            must_conditions.append(models.FieldCondition(key="category_ids", match=models.MatchValue(value=int(category_id))))
            
        filter_obj = models.Filter(must=must_conditions) if must_conditions else None
        
        # 3. Retrieve Candidates from Qdrant
        search_results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            query_filter=filter_obj,
            limit=20 # Candidate pool for reranking
        ).points
        
        if not search_results:
            return []
            
        # 4. Re-rank results with Cross-Encoder
        # Prepare (query, doc) pairs
        candidates = []
        for res in search_results:
            payload = res.payload
            # We use name + description for evaluation
            doc_text = f"{payload.get('name')}. {payload.get('description')}"
            candidates.append({
                "payload": payload,
                "doc_text": doc_text,
                "score": res.score # Initial semantic score
            })
            
        # Compute Cross-Encoder scores
        model_inputs = [[query, c["doc_text"]] for c in candidates]
        cross_scores = cross_encoder.predict(model_inputs)
        
        # Assign cross-scores
        for i, score in enumerate(cross_scores):
            candidates[i]["cross_score"] = float(score)
            
        # Sort by cross-score descending
        candidates.sort(key=lambda x: x["cross_score"], reverse=True)
        
        # 5. Format and Return Top K (Applying Threshold)
        final_results = []
        for c in candidates[:top_k]:
            if c["cross_score"] <= 2:
                # Results are sorted, so we can stop if we hit a score below the threshold
                break
                
            p = c["payload"]
            final_results.append({
                "id": p.get("id"),
                "name": p.get("name"),
                "price": p.get("price"),
                "in_stock": p.get("in_stock"),
                "image": p.get("image"),
                "description": p.get("description"),
                "is_variation": p.get("is_variation"),
                "parent_id": p.get("parent_id"),
                "attributes": p.get("attributes"),
                "relevance_score": c["cross_score"]
            })
            
        return final_results
        
    except Exception as e:
        logging.error(f"Error in vector search: {e}")
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
                "in_stock": p.payload.get("in_stock"),
                "image": p.payload.get("image")
            } for p in res]

        # 3. Case: Brand Filter + Semantic Query
        bi_encoder, cross_encoder = get_models()
        query_vector = bi_encoder.encode(query).tolist()
        
        search_results = client.query_points(
            collection_name=COLLECTION_NAME,
            query=query_vector,
            query_filter=filter_obj,
            limit=20
        ).points
        
        if not search_results:
            return []
            
        # Re-rank with Cross-Encoder
        candidates = []
        for res in search_results:
            payload = res.payload
            doc_text = f"{payload.get('name')}. {payload.get('description')}"
            candidates.append({"payload": payload, "doc_text": doc_text})
            
        model_inputs = [[query, c["doc_text"]] for c in candidates]
        cross_scores = cross_encoder.predict(model_inputs)
        
        for i, score in enumerate(cross_scores):
            candidates[i]["cross_score"] = float(score)
            
        candidates.sort(key=lambda x: x["cross_score"], reverse=True)
        
        return [{
            "id": c["payload"].get("id"),
            "name": c["payload"].get("name"),
            "price": c["payload"].get("price"),
            "in_stock": c["payload"].get("in_stock"),
            "image": c["payload"].get("image")
        } for c in candidates[:top_k] if c["cross_score"] > 2] # Score threshold
        
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
        bi_encoder, _ = get_models()
        query_vector = bi_encoder.encode(str(product_id_or_name)).tolist()
        
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
