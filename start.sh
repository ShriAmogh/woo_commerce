#!/bin/bash
set -e

echo "=========================================="
echo " Starting WooCommerce Chatbot Test Bed "
echo "=========================================="

# Check if ports are already in use and kill them
echo "Cleaning up existing processes on ports 8000 and 8080..."
lsof -ti :8000 | xargs kill -9 2>/dev/null || true
lsof -ti :8080 | xargs kill -9 2>/dev/null || true

# Check if .venv exists
if [ ! -d ".venv" ]; then
    echo "Virtual environment not found at .venv"
    exit 1
fi

# Ensure dependencies for FastAPI are installed
echo "Checking backend dependencies..."
.venv/bin/pip install -q fastapi uvicorn pydantic

echo "Starting FastAPI Agent Backend on port 8000..."
# Run FastAPI in the background
.venv/bin/python working/endpoints/agent_api.py &
FASTAPI_PID=$!

echo "Starting Frontend HTTP Server on port 8080..."
# Serve the widget folder on port 8080
cd working/widget && ../../.venv/bin/python -m http.server 8080 &
HTTP_PID=$!

echo "=========================================="
echo "🚀 Backend running at:   http://localhost:8000/chat"
echo "🌐 Frontend running at: http://localhost:8080/index.html"
echo "Press Ctrl+C to stop both servers."
echo "=========================================="

# Trap SIGINT and SIGTERM to kill both background processes
trap "echo 'Stopping servers...'; kill $FASTAPI_PID $HTTP_PID; exit 0" SIGINT SIGTERM

# Wait indefinitely until interrupted
wait
