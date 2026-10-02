#!/usr/bin/env bash

echo "========================================================"
echo "Starting Thai Speech-to-Text System (Backend + Frontend)"
echo "========================================================"

# Virtual environment setup
if [ ! -f "backend/venv/bin/python" ] && [ ! -f "backend/venv/Scripts/python.exe" ]; then
    echo "[Backend] Creating virtual environment in backend/venv..."
    python3 -m venv backend/venv || python -m venv backend/venv
    echo "[Backend] Installing requirements..."
    source backend/venv/bin/activate 2>/dev/null || source backend/venv/Scripts/activate
    pip install -r backend/requirements.txt
fi

echo "[1/2] Starting Python FastAPI Backend on http://localhost:8000 ..."
(
  source backend/venv/bin/activate 2>/dev/null || source backend/venv/Scripts/activate
  cd backend && uvicorn main:app --port 8000 --reload
) &
BACKEND_PID=$!

echo "[2/2] Starting Next.js Frontend on http://localhost:3000 ..."
npm run dev &
FRONTEND_PID=$!

trap "kill $BACKEND_PID $FRONTEND_PID; exit" SIGINT SIGTERM EXIT

wait
