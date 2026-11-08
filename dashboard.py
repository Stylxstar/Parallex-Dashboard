import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from pymongo import MongoClient

app = FastAPI()

MONGO_URI = os.getenv("MONGO_URI")
if MONGO_URI:
    client = MongoClient(MONGO_URI)
    db = client["parallex"]
    verification_sessions = db["verification_sessions"]
else:
    print("WARNING: No MONGO_URI found.")
    verification_sessions = None

def render_template(filename: str, context: dict = None):
    base_dir = os.path.dirname(os.path.abspath(__file__))
    file_path = os.path.join(base_dir, "templates", filename)
    with open(file_path, "r", encoding="utf-8") as f:
        html = f.read()
    if context:
        for key, value in context.items():
            html = html.replace(f"{{{{ {key} }}}}", value)
    return HTMLResponse(html)

# ==========================================
# LANDING PAGE
# ==========================================
@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return render_template("index.html")

# ==========================================
# WEB VERIFICATION ENGINE
# ==========================================
@app.get("/verify/{guild_id}", response_class=HTMLResponse)
async def verify_page(request: Request, guild_id: str, session: str = None, user: str = None):
    if not session:
        return HTMLResponse("<h1 style='color:red; text-align:center; margin-top:50px;'>Invalid Link. Please use the button in Discord.</h1>")
        
    if verification_sessions is None:
        return HTMLResponse("<h1 style='color:red; text-align:center; margin-top:50px;'>Database connection error. Contact staff.</h1>")
        
    try:
        verification_sessions.update_one(
            {"_id": str(session)},
            {"$set": {"verified": True, "user_id": str(user), "guild_id": str(guild_id)}},
            upsert=True
        )
        print(f"✅ Verified session {session}")
    except Exception as e:
        print(f"❌ Database Error: {e}")
        return HTMLResponse(f"<h1 style='color:red; text-align:center; margin-top:50px;'>An error occurred: {e}</h1>")
        
    return render_template("verify_success.html")

@app.get("/ping")
async def ping():
    return {"status": "ok", "database": "connected" if verification_sessions is not None else "disconnected"}
