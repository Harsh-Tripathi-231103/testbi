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

# ========================= Azure Identity =========================
from azure.identity import DefaultAzureCredential
from azure.core.exceptions import ClientAuthenticationError

# ========================= Logging =========================
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)   # ✅ FIXED

# ========================= FastAPI App =========================
app = FastAPI(title="Azure AI Foundry Chat API for Power BI")

# ========================= CORS =========================
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
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

# ========================= UNIVERSAL TOKEN PROVIDER =========================
logger.info("Setting up Azure authentication...")

try:
    credential = DefaultAzureCredential()
    token = credential.get_token("https://ai.azure.com/.default")
    app.state.credential = credential
    logger.info("Azure authentication ready!")
except ClientAuthenticationError:
    logger.critical("Azure authentication failed. Ensure AZURE_CLIENT_ID, SECRET & TENANT are set.")
    sys.exit(1)
except Exception as e:
    logger.critical(f"Unexpected auth error: {e}")
    sys.exit(1)

def get_headers():
    """Fetch fresh Azure token for each request."""
    try:
        token = app.state.credential.get_token("https://ai.azure.com/.default").token
        return {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
    except Exception as e:
        logger.error(f"Token refresh error: {e}")
        raise RuntimeError("Failed to refresh Azure token")

# ========================= Pydantic Models =========================
class ChatRequest(BaseModel):
    userQuery: str
    context: Optional[str] = None
    userId: Optional[str] = None

class ChatResponse(BaseModel):
    answer: str

# ========================= Helper Functions =========================
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

# ========================= API Endpoints =========================
@app.get("/")
def health():
    return {"status": "ok", "service": "Azure AI Foundry Chat API", "ready": True}

@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    user_query = request.userQuery.strip()
    if not user_query:
        raise HTTPException(status_code=400, detail="userQuery cannot be empty")

    logger.info(f"Query from {request.userId or 'anonymous'}: {user_query}")

    try:
        thread_id = create_thread()
        send_message(thread_id, user_query)
        run_id = start_run(thread_id)
        poll_run(thread_id, run_id)
        agent_reply = get_latest_reply(thread_id)
        return ChatResponse(answer=agent_reply)

    except requests.exceptions.RequestException as e:
        logger.error(f"HTTP error: {e}")
        raise HTTPException(status_code=502, detail="Failed to connect to Azure agent")

    except TimeoutError:
        raise HTTPException(status_code=504, detail="Agent timed out")

    except Exception as e:
        logger.error(f"Unexpected backend error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# ========================= Local Dev Server (ignored by Render) =========================
if __name__ == "__main__":    # ✅ FIXED
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=3000, reload=False)
