from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import logging
import sys
import os

# Ensure the parent 'working' directory is in the path so we can import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from orchestrator_gemini import GeminiOrchestrator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="WooCommerce Chatbot Agent API")

# Enable CORS for the frontend widget
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Per-session orchestrator registry
# Each visitor gets their own GeminiOrchestrator with isolated memory
sessions: dict = {}

class SessionContext(BaseModel):
    is_logged_in: bool = False
    session_id: Optional[str] = ""
    user_id: Optional[int] = None
    wc_nonce: Optional[str] = ""

class ChatRequest(BaseModel):
    message: str
    session_context: SessionContext = SessionContext()

class ChatResponse(BaseModel):
    response: str

@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "active_sessions": len(sessions),
        "woo_url": os.getenv("WOO_URL", "not set")
    }

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    try:
        session_id = req.session_context.session_id or "default"

        if session_id not in sessions:
            logger.info(f"Creating new orchestrator for session: {session_id}")
            sessions[session_id] = GeminiOrchestrator()

        context_dict = req.session_context.model_dump()
        reply = sessions[session_id].handle_query(
            user_input=req.message,
            session_context=context_dict
        )
        return ChatResponse(response=reply)
    except Exception as e:
        logger.error(f"Error handling chat request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/session/{session_id}")
async def clear_session(session_id: str):
    """Clear a specific session — useful when visitor logs out"""
    if session_id in sessions:
        del sessions[session_id]
        return {"status": "cleared", "session_id": session_id}
    return {"status": "not_found", "session_id": session_id}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)