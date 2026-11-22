# --- app.py ---
# Medical AI - FastAPI uygulaması (Admin Panel + Health Metrics API)

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

# --- Config & Auth ---
from config.auth_service import auth_service

# --- Routers ---
from routes import admin as admin_routes
from routes.auth import router as patient_auth_router
from routes.admin import health_router

# --- FastAPI App ---
app = FastAPI(title="Medical AI Admin Panel", version="1.0.0")

# --- Static Files ---
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Admin API JWT Guard ---
# /admin/api/auth/login dışındaki tüm admin API çağrıları geçerli bir admin
# JWT'si gerektirir. Login endpoint'i token ürettiği için muaf tutulur.
@app.middleware("http")
async def admin_api_auth_guard(request: Request, call_next):
    path = request.url.path
    if path.startswith("/admin/api") and not path.startswith("/admin/api/auth/login"):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"success": False, "error": "Yetkilendirme token'ı gerekli"},
            )
        try:
            token = auth_header[7:]
            if auth_service.is_token_revoked(token):
                return JSONResponse(
                    status_code=401,
                    content={"success": False, "error": "Token geçersiz kılınmış (çıkış yapılmış)"},
                )
            result = auth_service.verify_token(token, role="admin")
        except Exception as exc:  # DB erişilemezse 500 yerine anlaşılır hata
            return JSONResponse(
                status_code=503,
                content={"success": False, "error": f"Token doğrulanamadı: {exc}"},
            )
        user = result.get("user") or {}
        if result.get("success") and not user.get("is_active", True):
            return JSONResponse(
                status_code=401,
                content={"success": False, "error": "Kullanıcı pasif durumda"},
            )
        if not result.get("success"):
            return JSONResponse(
                status_code=401,
                content={"success": False, "error": result.get("message", "Geçersiz token")},
            )
    return await call_next(request)


# --- Hasta API JWT Guard ---
# /api/auth/* kayıt ve giriş endpoint'leri token üretir; muaf tutulur.
# Admin token'ı hasta endpoint'lerinde kullanılamaz (role="patient" zorunlu).
@app.middleware("http")
async def patient_api_auth_guard(request: Request, call_next):
    path = request.url.path
    public_paths = ("/api/auth/login", "/api/auth/register")
    if path.startswith("/api") and path not in public_paths:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return JSONResponse(
                status_code=401,
                content={"success": False, "error": "Yetkilendirme token'ı gerekli"},
            )
        try:
            token = auth_header[7:]
            if auth_service.is_token_revoked(token):
                return JSONResponse(
                    status_code=401,
                    content={"success": False, "error": "Token geçersiz kılınmış (çıkış yapılmış)"},
                )
            result = auth_service.verify_token(token, role="patient")
        except Exception as exc:
            return JSONResponse(
                status_code=503,
                content={"success": False, "error": f"Token doğrulanamadı: {exc}"},
            )
        user = result.get("user") or {}
        if result.get("success") and not user.get("is_active", True):
            return JSONResponse(
                status_code=401,
                content={"success": False, "error": "Kullanıcı pasif durumda"},
            )
        if not result.get("success"):
            return JSONResponse(
                status_code=401,
                content={"success": False, "error": result.get("message", "Geçersiz token")},
            )
    return await call_next(request)


# --- API Routes ---
app.include_router(patient_auth_router)
app.include_router(admin_routes.admin_router)
app.include_router(health_router)


# --- Admin Pages (tek bir SPA kabuğu) ---
def _static_tag(filename: str) -> str:
    """Statik dosyanın değişim zamanını sürüm anahtarı olarak döndürür.

    Tarayıcının eski admin.js/admin.css'i önbellekten servis etmesini önler.
    """
    try:
        return str(int((Path("static") / filename).stat().st_mtime))
    except OSError:
        return "0"


def _render_page(filename: str) -> HTMLResponse:
    html = Path("templates") / filename
    content = html.read_text(encoding="utf-8")
    for asset in ("admin.css", "admin.js", "login.js"):
        content = content.replace(
            "/static/" + asset + '"',
            "/static/" + asset + "?v=" + _static_tag(asset) + '"',
        )
    return HTMLResponse(content)


def _admin_page() -> HTMLResponse:
    return _render_page("admin.html")


@app.get("/", include_in_schema=False)
async def root():
    """Kök adres -> admin panele yönlendir."""
    return RedirectResponse(url="/admin", status_code=307)


@app.get("/admin", include_in_schema=False)
async def admin_dashboard():
    return _admin_page()


@app.get("/admin/config", include_in_schema=False)
async def admin_config_page():
    return _admin_page()


@app.get("/admin/llm", include_in_schema=False)
async def admin_llm_page():
    return _admin_page()


@app.get("/admin/users", include_in_schema=False)
async def admin_users_page():
    return _admin_page()


@app.get("/admin/health", include_in_schema=False)
async def admin_health_page():
    return _admin_page()


@app.get("/admin/monitoring", include_in_schema=False)
async def admin_monitoring_page():
    return _admin_page()


@app.get("/admin/db-config", include_in_schema=False)
async def admin_db_config_page():
    return _admin_page()


@app.get("/admin/login", include_in_schema=False)
async def admin_login_page():
    return _render_page("login.html")


@app.get("/admin/logout", include_in_schema=False)
async def admin_logout_page():
    """Sayfa üzerinden çıkış: istemci token'larını temizleyip login'e döner."""
    return HTMLResponse(
        """<!DOCTYPE html>
<html lang="tr"><head><meta charset="utf-8"><title>Çıkış</title></head>
<body>
<script>
try {
  localStorage.removeItem('admin_token');
  localStorage.removeItem('admin_user');
} finally {
  window.location.replace('/admin/login');
}
</script>
</body></html>"""
    )


# --- Health Check ---
@app.get("/health")
async def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
