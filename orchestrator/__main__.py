from .app import PORT, app
import uvicorn
print(f"Lend orchestrator + dashboard: http://127.0.0.1:{PORT}   approve button: http://127.0.0.1:{PORT}/button", flush=True)
uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
