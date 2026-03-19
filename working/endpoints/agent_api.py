from fastapi import FastAPI, HTTPException, BackgroundTasks, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import logging
import sys
import os
import time

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from orchestrator_gemini import GeminiOrchestrator
from sync_vector_db import sync_products

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="WooCommerce Chatbot Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sessions: dict = {}
session_timestamps: dict = {}
SESSION_TTL = 3600  # 1 hour

# Track sync status so you can poll it
sync_status = {
    "running":    False,
    "last_run":   None,
    "last_result": None,
}

class SessionContext(BaseModel):
    is_logged_in: bool = False
    session_id:   Optional[str] = ""
    user_id:      Optional[int] = None
    wc_nonce:     Optional[str] = ""

class ChatRequest(BaseModel):
    message:         str
    session_context: SessionContext = SessionContext()

class ChatResponse(BaseModel):
    response: str

# ─── Health ───────────────────────────────────────────────────────────────────
@app.get("/health")
async def health_check():
    return {
        "status":          "ok",
        "active_sessions": len(sessions),
        "woo_url":         os.getenv("WOO_URL", "not set"),
        "last_sync":       sync_status["last_run"],
        "sync_result":     sync_status["last_result"],
    }

# ─── Chat ─────────────────────────────────────────────────────────────────────
@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    req: ChatRequest,
    x_woochat_store_url:        Optional[str] = Header(None),
    x_woochat_consumer_key:     Optional[str] = Header(None),
    x_woochat_consumer_secret:  Optional[str] = Header(None),
):
    try:
        session_id = req.session_context.session_id or "default"
        now        = time.time()

        # Clean up expired sessions
        expired = [sid for sid, ts in session_timestamps.items()
                   if now - ts > SESSION_TTL]
        for sid in expired:
            sessions.pop(sid, None)
            session_timestamps.pop(sid, None)
            logger.info(f"Expired session: {sid}")

        if session_id not in sessions:
            logger.info(f"Creating new orchestrator for session: {session_id}")
            sessions[session_id] = GeminiOrchestrator()

        session_timestamps[session_id] = now

        context_dict = req.session_context.model_dump()

        # ✅ Multi-tenant: inject per-store credentials from WordPress headers
        if x_woochat_store_url or x_woochat_consumer_key or x_woochat_consumer_secret:
            context_dict["store_config"] = {
                "woo_url":         x_woochat_store_url     or "",
                "consumer_key":    x_woochat_consumer_key  or "",
                "consumer_secret": x_woochat_consumer_secret or "",
            }
            logger.info(f"📦 Store config received from headers: {x_woochat_store_url}")
        else:
            context_dict["store_config"] = None  # use .env fallback
            logger.info("⚠️  No store headers — falling back to .env credentials")

        reply = sessions[session_id].handle_query(
            user_input=req.message,
            session_context=context_dict
        )
        return ChatResponse(response=reply)
    except Exception as e:
        logger.error(f"Error handling chat request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

# ─── Session clear ────────────────────────────────────────────────────────────
@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    if session_id in sessions:
        del sessions[session_id]
        session_timestamps.pop(session_id, None)
        return {"status": "cleared", "session_id": session_id}
    return {"status": "not_found", "session_id": session_id}

# ─── Sync ─────────────────────────────────────────────────────────────────────
def run_sync():
    """Runs in background — does not block the HTTP response."""
    sync_status["running"] = True
    sync_status["last_run"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    try:
        logger.info("🔄 Vector DB sync started...")
        sync_products()
        sync_status["last_result"] = "success"
        logger.info("✅ Vector DB sync complete")
    except Exception as e:
        sync_status["last_result"] = f"error: {str(e)}"
        logger.error(f"❌ Sync failed: {e}", exc_info=True)
    finally:
        sync_status["running"] = False

@app.post("/sync")
async def trigger_sync(
    background_tasks: BackgroundTasks,
    x_sync_secret:    Optional[str] = Header(None),
):
    """
    Trigger a vector DB re-sync.

    Security: requires X-Sync-Secret header matching SYNC_SECRET env var.
    Set SYNC_SECRET in Railway variables.

    Called by:
      - WooCommerce webhook (product updated/created/deleted)
      - Manual curl
      - Cron job
    """
    # ── Validate secret ────────────────────────────────────────────────────
    sync_secret = os.getenv("SYNC_SECRET", "")
    if sync_secret and x_sync_secret != sync_secret:
        raise HTTPException(status_code=401, detail="Invalid sync secret.")

    # ── Prevent concurrent syncs ───────────────────────────────────────────
    if sync_status["running"]:
        return {
            "status":   "already_running",
            "message":  "Sync is already in progress.",
            "last_run": sync_status["last_run"],
        }

    # ── Fire sync in background — returns immediately ──────────────────────
    background_tasks.add_task(run_sync)

    return {
        "status":  "started",
        "message": "Sync started in background. Check /health for result.",
    }

@app.get("/sync/status")
async def sync_status_check():
    """Poll this to check if a sync is running or see the last result."""
    return {
        "running":     sync_status["running"],
        "last_run":    sync_status["last_run"],
        "last_result": sync_status["last_result"],
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)