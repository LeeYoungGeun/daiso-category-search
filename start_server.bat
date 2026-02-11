@echo off
cd c:\Users\301\dev\daiso-category-search
c:\Users\301\dev\daiso-category-search\venv\Scripts\python.exe -m uvicorn backend.api:app --host 0.0.0.0 --port 8000 --reload > server_output.txt 2>&1
