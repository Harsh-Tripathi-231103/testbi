# main.py
# Secure Azure AI Foundry Chat API for Power BI – UNIVERSAL & CLOUD-READY (2025+)

import time
import requests
import sys
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional

# ========================= NEW: Azure Identity (install once: pip install azure-identity) =========================
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import ClientAuthenticationError

# ========================= Logging =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(name)

app = FastAPI(title="Azure AI Foundry Chat API for Power BI")

# ========================= CORS =========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # TODO: restrict in production
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# ========================= Azure AI Foundry Config =========================
ENDPOINT     = "https://rbhu-foundry-2.services.ai.azure.com"
PROJECT_NAME = "rbhu-foundry"
AGENT_ID     = "asst_3x7W3aW4wyU7zQjGyJMZtuxM"
API_VERSION  = "2025-05-01"
BASE_URL     = f"{ENDPOINT}/api/projects/{PROJECT_NAME}/threads"

# ========================= UNIVERSAL TOKEN PROVIDER (WORKS EVERYWHERE) =========================
logger.info("Setting up Azure authentication (az login or Managed Identity)...")

try:
    credential = DefaultAzureCredential()
    # Test once at startup
    token = credential.get_token("https://ai.azure.com/.default")
    app.state.credential = credential
    logger.info("Azure authentication ready! (using your az login or cloud identity)")
except ClientAuthenticationError:
    logger.critical("Authentication failed! Run 'az login' or deploy with Managed Identity enabled.")
    sys.exit(1)
except Exception as e:
    logger.critical(f"Unexpected auth setup error: {e}")
    sys.exit(1)

def get_headers():
    """Returns fresh headers with a valid token on every call"""
    try:
        token = app.state.credential.get_token("https://ai.azure.com/.default").token
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    except Exception as e:
        logger.error(f"Failed to refresh token: {e}")
        raise RuntimeError("Authentication token expired and could not be refreshed")

# ========================= Pydantic Models =========================
class ChatRequest(BaseModel):
    userQuery: str
    context: Optional[str] = None
    userId: Optional[str] = None

class ChatResponse(BaseModel):
    answer: str

# ========================= Helper Functions (unchanged logic, only uses get_headers()) =========================
def create_thread() -> str:
    response = requests.post(f"{BASE_URL}?api-version={API_VERSION}", headers=get_headers(), timeout=30)
    response.raise_for_status()
    return response.json()["id"]

def send_message(thread_id: str, content: str):
    url = f"{BASE_URL}/{thread_id}/messages?api-version={API_VERSION}"
    payload = {"role": "user", "content": content}
    response = requests.post(url, headers=get_headers(), json=payload, timeout=30)
    response.raise_for_status()

def start_run(thread_id: str) -> str:
    url = f"{BASE_URL}/{thread_id}/runs?api-version={API_VERSION}"
    payload = {"assistant_id": AGENT_ID}
    response = requests.post(url, headers=get_headers(), json=payload, timeout=30)
    response.raise_for_status()
    return response.json()["id"]

def poll_run(thread_id: str, run_id: str, max_wait_seconds: int = 90):
    url = f"{BASE_URL}/{thread_id}/runs/{run_id}?api-version={API_VERSION}"
    start_time = time.time()

    while True:
        if time.time() - start_time > max_wait_seconds:
            raise TimeoutError("Agent took too long to respond")

        response = requests.get(url, headers=get_headers(), timeout=30)
        response.raise_for_status()
        data = response.json()
        status = data.get("status")

        if status in ["completed", "failed", "cancelled", "expired"]:
            if status != "completed":
                error_msg = data.get("error", {}).get("message", "Unknown error")
                raise RuntimeError(f"Agent run failed: {status} - {error_msg}")
            return

        time.sleep(1.5)

def get_latest_reply(thread_id: str) -> str:
    response = requests.get(f"{BASE_URL}/{thread_id}/messages?api-version={API_VERSION}", headers=get_headers(), timeout=30)
    response.raise_for_status()
    messages = response.json().get("data", [])

    for msg in messages:
        if msg.get("role") == "assistant":
            content_blocks = msg.get("content", [])
            if content_blocks and "text" in content_blocks[0] and "value" in content_blocks[0]["text"]:
                return content_blocks[0]["text"]["value"]
    return "No response from agent."

# ========================= Endpoints =========================
@app.get("/")
def health():
    return {"status": "ok", "service": "Azure AI Foundry Chat API", "ready": True}

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    user_query = request.userQuery.strip()
    if not user_query:
        raise HTTPException(status_code=400, detail="userQuery is required and cannot be empty")

    logger.info(f"Query from userId={request.userId or 'anonymous'}: {user_query}")

    try:
        thread_id = create_thread()
        send_message(thread_id, user_query)
        run_id = start_run(thread_id)
        poll_run(thread_id, run_id)
        agent_reply = get_latest_reply(thread_id)
        return ChatResponse(answer=agent_reply)

    except requests.exceptions.RequestException as e:
        logger.error(f"HTTP error: {e}")
        raise HTTPException(status_code=502, detail="Failed to connect to AI agent")
    except TimeoutError:
        raise HTTPException(status_code=504, detail="Agent took too long to respond")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# ========================= Run Server =========================
if name == "main":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=3000, reload=True, log_level="info")