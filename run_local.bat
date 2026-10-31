@echo off
REM Starts the notebook in editing mode on http://127.0.0.1:8000
set APP_MODE=local
python -m uvicorn main:app --reload --port 8000
