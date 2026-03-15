from fastapi import FastAPI, HTTPException, BackgroundTasks, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import logging
import sys
import os
import time

# Ensure imports from parent 'working' directory work
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))
from orchestrator_phi3 import Orchestrator
from sync_vector_db import sync_products

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="WooCommerce Chatbot (Phi-3 Local) API")

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

# Track sync status
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
    action:   Optional[str] = None

@app.get("/health")
async def health_check():
    return {
        "status":          "ok",
        "orchestrator":    "phi3",
        "active_sessions": len(sessions),
    }

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    try:
        session_id = req.session_context.session_id or "default"
        now        = time.time()

        # Clean up expired sessions
        expired = [sid for sid, ts in session_timestamps.items() if now - ts > SESSION_TTL]
        for sid in expired:
            sessions.pop(sid, None)
            session_timestamps.pop(sid, None)

        if session_id not in sessions:
            logger.info(f"Creating new Phi-3 orchestrator for session: {session_id}")
            sessions[session_id] = Orchestrator()

        session_timestamps[session_id] = now
        
        reply = sessions[session_id].handle_query(
            user_input=req.message,
            session_context=req.session_context.model_dump()
        )
        
        # Simple action detection logic for Phi-3 (if not in response)
        action = None
        if "login" in reply.lower() and "prompt" in reply.lower():
            action = "prompt_login"
        
        return ChatResponse(response=reply, action=action)
    except Exception as e:
        logger.error(f"Error handling chat request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    if session_id in sessions:
        del sessions[session_id]
        session_timestamps.pop(session_id, None)
        return {"status": "cleared"}
    return {"status": "not_found"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
