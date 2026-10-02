@echo off
echo ========================================================
echo Starting Thai Speech-to-Text System (Backend + Frontend)
echo ========================================================

:: Check for backend virtual environment
if not exist "backend\venv\Scripts\python.exe" (
    echo [Backend] Virtual environment not found in backend\venv.
    echo [Backend] Creating virtual environment...
    python -m venv backend\venv
    if %errorlevel% neq 0 (
        echo [Backend] Failed to create virtual environment with 'python'. Trying 'py'...
        py -m venv backend\venv
    )
    echo [Backend] Installing requirements...
    call backend\venv\Scripts\pip install -r backend\requirements.txt
)

echo [1/2] Starting Python FastAPI Backend on http://localhost:8000 ...
start "Thai STT - Backend" cmd /k "cd backend && call venv\Scripts\activate && set PYTHONUTF8=1 && set PYTHONIOENCODING=utf-8 && uvicorn main:app --port 8000 --reload"

echo [2/2] Starting Next.js Frontend on http://localhost:3000 ...
start "Thai STT - Frontend" cmd /k "npm run dev"

echo ========================================================
echo Both services are starting in separate terminal windows.
echo Frontend URL: http://localhost:3000
echo Backend API Docs: http://localhost:8000/docs
echo ========================================================
