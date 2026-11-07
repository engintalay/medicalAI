# --- app.py ---
# Denetçi Eylemi: Main FastAPI App (Basamak 5 Entegrasyonu)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# --- Import Config Loader (Basamak 3) ---
from config.loader import get_config_loader

# --- Import Routes (Basamak 4 & 5) ---
from routes import auth
from admin import routes as admin_routes

# --- Faz 1: Health Metrics Routes (routes/admin.py) ---
from routes.admin import health_router

# --- FastAPI App ---
app = FastAPI(title="Medical AI Admin Panel", version="1.0.0")

# --- Static Files ---
static_dir = "static"
admin_static_dir = "admin/static" if __import__('os').path.exists("admin/static") else "static"
admin_panel_dir = "templates"
admin_html_dir = "admin/static" if __import__('os').path.exists("admin/static") else "admin/static"

# --- Root Path ---
@app.get("/")
async def root():
    """Root Path - Redirect to Admin Panel"""
    return FileResponse("templates/admin.html")

# --- Admin Panel Routes ---
admin_router = admin_routes.admin_router
html_router = admin_routes.html_router

# --- API Routes ---
admin_router.include_router(auth.router)
admin_router.include_router(admin_routes.router)

# --- Faz 1: Health Metrics Routes (mounted directly; prefix /admin/api/health) ---
app.include_router(health_router)

# --- Admin HTML Pages ---
app.include_router(html_router)
# --- Admin Static Files ---
app.mount("/admin/static", StaticFiles(directory=admin_static_dir), name="admin_static")

# --- Admin Panel Static Files ---
app.mount("/admin_panel", StaticFiles(directory=admin_panel_dir), name="admin_panel")

# --- Default Config Loader ---
@app.get("/admin/api/config")
async def get_config():
    """GET /admin/api/config - Tüm Config Ayarlarını Listele (Fallback)"""
    loader = get_config_loader()
    config_dict = {}
    default_keys = ["llm_api_key", "llm_model", "rag_top_k", "rag_chunk_size", "rag_overlap"]
    for key in default_keys:
        config_dict[key] = loader.get(key, "")
    return config_dict

# --- Health Check ---
@app.get("/health")
async def health_check():
    """Health Check"""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
