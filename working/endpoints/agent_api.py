from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional, Dict, Any
import logging
import sys
import os

# Ensure the parent 'working' directory is in the path so we can import modules
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from orchestrator_gemini import GeminiOrchestrator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="WooCommerce Chatbot Agent API")

# Enable CORS for the frontend widget widget
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize the orchestrator globally so session memory persists in the python process
orchestrator = GeminiOrchestrator()

class SessionContext(BaseModel):
    is_logged_in: bool
    session_id: str
    user_id: Optional[int] = None

class ChatRequest(BaseModel):
    message: str
    session_context: SessionContext
    
class ChatResponse(BaseModel):
    response: str

@app.get("/health")
async def health_check():
    return {"status": "ok"}
    
@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    try:
        # Pass both input and context to orchestrator
        context_dict = req.session_context.dict()
        reply = orchestrator.handle_query(user_input=req.message, session_context=context_dict)
        return ChatResponse(response=reply)
    except Exception as e:
        logger.error(f"Error handling chat request: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    # Start the FastAPI app
    uvicorn.run(app, host="0.0.0.0", port=8000)
