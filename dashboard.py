import os
import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pymongo import MongoClient
from fastapi_ipware import IpWare
import time

app = FastAPI()
ipware = IpWare()

MONGO_URI = os.getenv("MONGO_URI")
if MONGO_URI:
    client = MongoClient(MONGO_URI)
    db = client["parallex"]
    verification_sessions = db["verification_sessions"]
    verified_users = db["verified_users"]
else:
    print("WARNING: No MONGO_URI found.")
    verification_sessions = None
    verified_users = None

def render_template(filename: str, context: dict = None):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, "templates", filename)
    with open(file_path, "r", encoding="utf-8") as f:
        html = f.read()
    if context:
        for key, value in context.items():
            html = html.replace(f"{{{{ {key} }}}}", value)
    return HTMLResponse(html)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return render_template("index.html")

@app.get("/terms", response_class=HTMLResponse)
async def terms(request: Request):
    return render_template("terms.html")

# ==========================================
# WEB VERIFICATION ENGINE
# ==========================================
@app.get("/verify/{guild_id}", response_class=HTMLResponse)
async def verify_page(request: Request, guild_id: str, session: str = None, user: str = None):
    if not session or not user or verification_sessions is None:
        return render_template("verify_invalid.html", {"GUILD_ID": guild_id})
        
    try:
        # 1. Check if the session exists
        record = verification_sessions.find_one({"_id": str(session)})
        if not record:
            return render_template("verify_invalid.html", {"GUILD_ID": guild_id})

        # 2. Check if it has already been used
        if record.get("used"):
            return render_template("verify_invalid.html", {"GUILD_ID": guild_id})

        # 3. Check if it has expired (2 minutes = 120 seconds)
        created_at = record.get("created_at", 0)
        if time.time() - created_at > 120:
            verification_sessions.delete_one({"_id": str(session)})
            return render_template("verify_invalid.html", {"GUILD_ID": guild_id})

        # 4. Grab the IP
        ip_result = ipware.get_client_ip(request)
        ip = ip_result[0] if ip_result else "Unknown_IP"
        
        # 5. Check for Alt Accounts
        if verified_users is not None and ip != "Unknown_IP":
            existing_alt = verified_users.find_one({"guild_id": guild_id, "ip": ip})
            if existing_alt and str(existing_alt.get("user_id")) != str(user):
                return render_template("verify_failed.html", {
                    "REASON": "Your IP address is linked to another verified account. Alt accounts are not allowed.",
                    "GUILD_ID": guild_id
                })
                
            verified_users.update_one(
                {"guild_id": guild_id, "user_id": str(user)},
                {"$set": {"ip": ip}},
                upsert=True
            )

        # 6. Mark as USED and verified
        verification_sessions.update_one(
            {"_id": str(session)},
            {"$set": {"verified": True, "used": True}}
        )
        
        print(f"✅ Verified {user} (IP: {ip})")
    except Exception as e:
        print(f"❌ Database Error: {e}")
        return HTMLResponse(f"<h1 style='color:red; text-align:center; margin-top:50px;'>An error occurred.</h1>")
        
    return render_template("verify_success.html", {"GUILD_ID": guild_id})

@app.get("/ping")
async def ping():
    return {"status": "ok", "database": "connected" if verification_sessions is not None else "disconnected"}
