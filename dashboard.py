import os
import json
import httpx
from pathlib import Path
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.middleware.sessions import SessionMiddleware

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key="super-secret-parallex-key-change-me")

CLIENT_ID = os.getenv("CLIENT_ID", "YOUR_CLIENT_ID_HERE")
CLIENT_SECRET = os.getenv("CLIENT_SECRET", "YOUR_CLIENT_SECRET_HERE")
REDIRECT_URI = os.getenv("REDIRECT_URI", "http://localhost:8000/callback")

DISCORD_API_BASE = "https://discord.com/api/v10"

# Data paths
DATA_DIR = Path("data")
CONFIG_PATH = DATA_DIR / "verify_config.json"

def load_db():
    if not CONFIG_PATH.exists():
        return {}
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))

def save_db(data):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

# Custom HTML Reader (Bypasses Jinja2 completely)
def render_template(filename: str, context: dict):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, "templates", filename)
    with open(file_path, "r", encoding="utf-8") as f:
        html = f.read()
    
    # Simple string replacement for variables
    for key, value in context.items():
        if isinstance(value, str):
            html = html.replace(f"{{{{ {key} }}}}", value)
    return HTMLResponse(html)

# ==========================================
# ROUTES
# ==========================================

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    user = request.session.get("user")
    # If logged in, show dashboard link, else show login link
    login_html = '<a href="/dashboard" class="bg-green-500 hover:bg-green-600 px-6 py-3 rounded-lg font-semibold transition">Go to Dashboard</a>' if user else '<a href="/login" class="bg-indigo-500 hover:bg-indigo-600 px-6 py-3 rounded-lg font-semibold transition">Login with Discord</a>'
    
    return render_template("index.html", {"LOGIN_BUTTON": login_html})

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
    
    # Build the server cards
    cards = ""
    for guild in user["guilds"]:
        cards += f'''
        <a href="/manage/{guild['id']}" class="glass p-6 rounded-2xl flex items-center gap-5 hover:bg-white/10 hover:-translate-y-1 transition duration-300 group cursor-pointer border-t border-t-white/10">
            <div class="w-16 h-16 bg-gradient-to-br from-indigo-500/40 to-purple-500/40 rounded-xl flex items-center justify-center font-bold text-2xl group-hover:scale-110 transition">
                {guild['name'][0]}
            </div>
            <div class="flex-1">
                <h3 class="font-bold text-lg text-white mb-1 group-hover:text-indigo-300 transition">{guild['name']}</h3>
                <p class="text-sm text-gray-400 flex items-center gap-1">Manage Settings <span class="group-hover:translate-x-1 transition">&rarr;</span></p>
            </div>
        </a>
        '''
    
    return render_template("dashboard.html", {"USERNAME": user['username'], "SERVER_CARDS": cards})

@app.get("/manage/{guild_id}", response_class=HTMLResponse)
async def manage_server(request: Request, guild_id: str):
    user = request.session.get("user")
    if not user: return RedirectResponse("/")
    
    guild_name = next((g["name"] for g in user["guilds"] if g["id"] == guild_id), "Unknown Server")
    db = load_db()
    config = db.get(guild_id, {})
    
    return render_template("manage.html", {
        "GUILD_NAME": guild_name, 
        "GUILD_ID": guild_id,
        "VERIFIED_ROLE": str(config.get('verified_role_id', '')),
        "LOG_CHANNEL": str(config.get('log_channel_id', ''))
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
