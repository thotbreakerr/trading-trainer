# Start the backend. No --reload: a reload restart would kill in-memory replay
# sessions and duplicate the Market Day poller; restart this script instead.
& "$PSScriptRoot\.venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
