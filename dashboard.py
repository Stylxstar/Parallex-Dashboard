import os
import time
import hashlib
import logging
from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import HTMLResponse, JSONResponse
from pymongo import MongoClient
from fastapi_ipware import IpWare

logger = logging.getLogger("parallex.web")
logging.basicConfig(level=logging.INFO)

app = FastAPI()
ipware = IpWare()
START_TIME = time.time()

MONGO_URI = os.getenv("MONGO_URI")
if MONGO_URI:
    client = MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
    db = client["parallex"]
    verification_sessions = db["verification_sessions"]
    verified_users = db["verified_users"]
else:
    client = None
    verification_sessions = None
    verified_users = None

def render_template(filename: str, context: dict = None):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, "templates", filename)
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            html = f.read()
    except FileNotFoundError:
        return HTMLResponse(f"<h1>Missing template: {filename}</h1>", status_code=500)
    
    if context:
        for key, value in context.items():
            html = html.replace(f"{{{{ {key} }}}}", str(value))
            
    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"}
    )

def get_real_ip(request: Request) -> str:
    for header in ("CF-Connecting-IP", "X-Real-IP", "True-Client-IP", "X-Client-IP", "X-Forwarded-For"):
        raw = request.headers.get(header)
        if raw:
            first = raw.split(",")[0].strip().replace('"', "").replace("for=", "")
            if first and first.lower() not in ("unknown", "null", ""):
                return first[:64]
    try:
        ip_result = ipware.get_client_ip(request)
        if ip_result and ip_result[0]: return str(ip_result[0])[:64]
    except: pass
    return "Unknown_IP"

# ==========================================
# ROUTES
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return render_template("index.html")

@app.get("/terms", response_class=HTMLResponse)
async def terms(request: Request):
    return render_template("terms.html")

@app.get("/ping")
async def ping():
    return JSONResponse({"status": "ok", "uptime": int(time.time() - START_TIME)})

# --- DOUBLE COUNTER STYLE API CHECK ---
@app.post("/api/check-verification")
async def check_verification(request: Request):
    """Called via JS on the loading screen before showing success."""
    data = await request.json()
    session_id = data.get("session")
    user_id = data.get("user")
    browser_fp = data.get("fingerprint") # We can pass screen res / UA hash
    
    if not session_id or not user_id or verification_sessions is None:
        return JSONResponse({"status": "invalid"})

    record = verification_sessions.find_one({"_id": str(session_id)})
    if not record or record.get("used"):
        return JSONResponse({"status": "invalid"})

    ip = get_real_ip(request)
    
    # STRICT ALT CHECK: Check IP + Browser Fingerprint
    if verified_users is not None:
        existing_alt = verified_users.find_one({
            "$or": [
                {"ip": ip, "user_id": {"$ne": str(user_id)}},
                {"fingerprint": browser_fp, "user_id": {"$ne": str(user_id)}} if browser_fp else {"_id": "dummy"}
            ],
            "guild_id": data.get("guild_id")
        })

        if existing_alt:
            matched_alt_id = str(existing_alt.get("user_id"))
            # Block session
            verification_sessions.update_one(
                {"_id": str(session_id)},
                {"$set": {
                    "blocked": True, 
                    "blocked_reason": "Alt Account / VPN Detected", 
                    "alt_id": matched_alt_id,
                    "used": True
                }}
            )
            return JSONResponse({"status": "blocked", "reason": "Alt Account detected."})

        # Save User Data
        verified_users.update_one(
            {"guild_id": data.get("guild_id"), "user_id": str(user_id)},
            {"$set": {"ip": ip, "fingerprint": browser_fp, "verified_at": time.time()}},
            upsert=True
        )

    # Success
    verification_sessions.update_one(
        {"_id": str(session_id)},
        {"$set": {"verified": True, "used": True, "verified_at": time.time()}}
    )
    return JSONResponse({"status": "success"})


@app.get("/verify/{guild_id}", response_class=HTMLResponse)
async def verify_page(request: Request, guild_id: str, session: str = None, user: str = None, channel: str = None):
    if not session or not user or verification_sessions is None:
        return render_template("verify_invalid.html", {"GUILD_ID": guild_id, "CHANNEL_ID": channel or "0"})
        
    record = verification_sessions.find_one({"_id": str(session)})
    if not record or record.get("used"):
        return render_template("verify_invalid.html", {"GUILD_ID": guild_id, "CHANNEL_ID": channel or "0"})

    # Immediately serve the Success Page but it will wait for JS to tell it if it's an alt.
    return render_template("verify_success.html", {
        "GUILD_ID": guild_id, 
        "CHANNEL_ID": channel or "0",
        "SESSION_ID": session,
        "USER_ID": user
    })
