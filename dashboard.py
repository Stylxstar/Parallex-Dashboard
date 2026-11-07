import os
import json
import httpx
from pathlib import Path
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
# Change this secret in the future to something random
app.add_middleware(SessionMiddleware, secret_key="super-secret-parallex-key-change-me")
templates = Jinja2Templates(directory="templates")

# --- CONFIGURATION (WE WILL FILL THIS LATER ON RENDER) ---
CLIENT_ID = os.getenv("CLIENT_ID", "YOUR_CLIENT_ID_HERE")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:8000/callback")

DISCORD_API_BASE = "https://discord.com/api/v10"

# --- DATABASE (For local testing) ---
DATA_DIR = Path("data")
CONFIG_PATH = DATA_DIR / "verify_config.json"

def load_db():
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

def save_db(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

# ==========================================
# ROUTES
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = request.session.get("user")
    return templates.TemplateResponse("index.html", {"request": request, "user": user})

@app.get("/login")
async def login():
    auth_url = (
        f"{DISCORD_API_BASE}/oauth2/authorize?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}&response_type=code&scope=identify%20guilds"
    )
    return RedirectResponse(auth_url)

@app.get("/callback")
async def callback(request: Request, code: str):
    data = {
        "client_id": CLIENT_ID, "client_secret": CLIENT_SECRET,
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI,
    }
    async with httpx.AsyncClient() as client:
        res = await client.post(f"{DISCORD_API_BASE}/oauth2/token", data=data)
        token = res.json().get("access_token")
        if not token: return HTMLResponse("Login failed. Check client secrets.")
        
        headers = {"Authorization": f"Bearer {token}"}
        user_res = await client.get(f"{DISCORD_API_BASE}/users/@me", headers=headers)
        user = user_res.json()
        
        guilds_res = await client.get(f"{DISCORD_API_BASE}/users/@me/guilds", headers=headers)
        guilds = [g for g in guilds_res.json() if (int(g["permissions"]) & 0x8) == 0x8 or (int(g["permissions"]) & 0x20) == 0x20]

    request.session["user"] = {"id": user["id"], "username": user["username"], "guilds": guilds}
    return RedirectResponse("/dashboard")

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user = request.session.get("user")
    if not user: return RedirectResponse("/")
    return templates.TemplateResponse("dashboard.html", {"request": request, "user": user})

@app.get("/manage/{guild_id}", response_class=HTMLResponse)
async def manage_server(request: Request, guild_id: str):
    user = request.session.get("user")
    if not user: return RedirectResponse("/")
    
    guild_name = next((g["name"] for g in user["guilds"] if g["id"] == guild_id), "Unknown Server")
    db = load_db()
    config = db.get(guild_id, {})
    
    return templates.TemplateResponse("manage.html", {
        "request": request, "user": user, "guild_name": guild_name, "config": config, "guild_id": guild_id
    })

@app.post("/manage/{guild_id}")
async def save_settings(request: Request, guild_id: str, verified_role: str = Form(None), log_channel: str = Form(None)):
    user = request.session.get("user")
    if not user: return RedirectResponse("/")
    
    db = load_db()
    if guild_id not in db: db[guild_id] = {}
    
    db[guild_id]["verified_role_id"] = int(verified_role) if verified_role and verified_role.isdigit() else None
    db[guild_id]["log_channel_id"] = int(log_channel) if log_channel and log_channel.isdigit() else None
    
    save_db(db)
    return RedirectResponse(f"/manage/{guild_id}?saved=true", status_code=303)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/")
