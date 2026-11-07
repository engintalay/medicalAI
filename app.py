# --- app.py ---
# Denetçi Eylemi: Main FastAPI App (Basamak 5 Entegrasyonu)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# --- Import Config Loader (Basamak 3) ---
from config.loader import get_config_loader

# --- Import Routes (Basamak 4 & 5) ---
# Faz 1: Admin API (auth/config/users/monitoring) — prefix /admin/api
from routes import admin as admin_routes
# Faz 0: HTML pages (dashboard/login/logout)
from admin import routes as admin_html_routes

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

# --- Faz 1: Admin API Routes (mounted directly; prefix /admin/api) ---
# auth/login, auth/logout, config, config/{key}, users, monitoring, utils/secret
app.include_router(admin_routes.admin_router)

# --- Faz 1: Health Metrics Routes (mounted directly; prefix /admin/api/health) ---
app.include_router(health_router)

# --- Admin HTML Pages (Faz 0; prefix "" so pages match frontend nav URLs) ---
html_router = admin_html_routes.html_router
app.include_router(html_router)
# --- Admin Static Files ---
app.mount("/admin/static", StaticFiles(directory=admin_static_dir), name="admin_static")

# --- Admin Panel Static Files ---
app.mount("/admin_panel", StaticFiles(directory=admin_panel_dir), name="admin_panel")

# --- Health Check ---
@app.get("/health")
async def health_check():
    """Health Check"""
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
