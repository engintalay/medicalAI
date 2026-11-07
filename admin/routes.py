# --- admin/routes.py ---
# Denetçi Eylemi: Basamak 5 (Admin Panel API Routes)

import os
from typing import Optional
from fastapi import APIRouter, Depends, Request, Query, HTTPException
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

# --- Import Config Loader & Auth (Basamak 3 & 4 ile Bağlantı) ---
from config.loader import get_config_loader
from routes.auth import get_current_user, create_access_token, get_jwt_secret

# Router Tanımları
router = APIRouter()
admin_router = APIRouter(prefix="/admin")
admin_html_router = APIRouter(prefix="")

# --- Combined HTML Router (Basamak 6 & 7) ---
# Prefix "" so pages match the frontend nav links (/admin, /admin/login, /admin/logout)
html_router = APIRouter(prefix="")

# --- Request Modelleri ---
class ConfigUpdate(BaseModel):
    key: str
    value: str

class SQLExecuteRequest(BaseModel):
    sql: str

class SQLTemplate(BaseModel):
    name: str
    sql: str

# --- Helper Functions ---
def get_admin_user(request: Request):
    """Admin User Middleware (Basamak 4 ile Entegre)"""
    current_user = get_current_user(request)
    return current_user

def get_db_connection():
    """PostgreSQL Bağlantı (Basamak 2 ile Entegre)"""
    loader = get_config_loader()
    host = loader.get("db_host") or "localhost"
    port = loader.get("db_port") or "5432"
    dbname = loader.get("db_name") or "medicalai"
    user = loader.get("db_user") or "postgres"
    password = loader.get("db_password") or "postgres"
    
    import psycopg2
    conn = psycopg2.connect(host=host, port=port, dbname=dbname, user=user, password=password)
    return conn

# --- API Endpoints ---

@router.get("/admin/api/config")
async def get_config():
    """GET /admin/api/config - Tüm Config Ayarlarını Listele"""
    loader = get_config_loader()
    config_dict = {}
    # Basit config key listesi (system_config tablosu yerine)
    default_keys = ["llm_api_key", "llm_model", "rag_top_k", "rag_chunk_size", "rag_overlap"]
    for key in default_keys:
        config_dict[key] = loader.get(key, "")
    return config_dict

@router.put("/admin/api/config")
async def update_config(config: ConfigUpdate, request: Request):
    """PUT /admin/api/config - Config Güncelle"""
    loader = get_config_loader()
    loader._cache[config.key] = config.value
    return {"status": "success", "key": config.key, "value": config.value}

@router.post("/admin/api/sql/execute")
async def execute_sql(sql: SQLExecuteRequest, request: Request):
    """POST /admin/api/sql/execute - SQL Çalıştır"""
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(sql.sql)
            if cur.description:
                columns = [desc[0] for desc in cur.description]
                rows = cur.fetchall()
                result = {"columns": columns, "rows": rows}
            else:
                result = {"rows": []}
        return result
    except Exception as e:
        return {"error": str(e)}
    finally:
        conn.close()

@router.get("/admin/api/sql/templates")
async def get_sql_templates():
    """GET /admin/api/sql/templates - SQL Şablonları Listele"""
    templates = [
        {"name": "get_users", "sql": "SELECT * FROM users"},
        {"name": "get_config", "sql": "SELECT * FROM system_config"},
    ]
    return templates

@router.get("/admin/api/users")
async def get_users(request: Request):
    """GET /admin/api/users - Kullanıcı Listesi"""
    loader = get_config_loader()
    admin_username = loader.get("admin_username") or "admin"
    admin_email = loader.get("admin_email") or "admin@example.com"
    return [
        {"username": admin_username, "email": admin_email, "role": "admin"}
    ]

@router.get("/admin/api/monitoring")
async def get_monitoring(request: Request):
    """GET /admin/api/monitoring - Monitoring Dashboard"""
    loader = get_config_loader()
    db_status = "connected" if loader.get("db_host") else "disconnected"
    redis_status = "connected" if loader.get("redis_host") else "disconnected"
    return {
        "db": {"status": db_status, "host": loader.get("db_host"), "port": loader.get("db_port")},
        "redis": {"status": redis_status, "host": loader.get("redis_host"), "port": loader.get("redis_port")},
        "config": {"loaded": True, "keys": len(loader.get("config_cache", {}))},
    }

# --- HTML Admin UI (Basamak 6 için) ---
@html_router.get("/admin")
async def admin_html():
    """GET /admin - HTML Admin Panel"""
    loader = get_config_loader()
    config = loader.get("config_cache", {})
    llm_api_key = config.get("llm_api_key") or "default_llm_key"
    llm_model = config.get("llm_model") or "default_model"
    rag_top_k = config.get("rag_top_k") or 3
    rag_chunk_size = config.get("rag_chunk_size") or 500
    rag_overlap = config.get("rag_overlap") or 100
    
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Medical AI Admin Panel</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
            body {{ font-family: Arial, sans-serif; background: #f4f4f4; padding: 20px; }}
            .container {{ max-width: 800px; margin: auto; background: white; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }}
            h1 {{ color: #333; border-bottom: 2px solid #4CAF50; padding-bottom: 10px; }}
            .config-group {{ background: #f9f9f9; padding: 10px; margin: 10px 0; border-radius: 4px; }}
            .config-group h3 {{ margin: 0 0 10px; color: #4CAF50; }}
            .form-group {{ margin: 10px 0; }}
            .form-group label {{ display: block; font-weight: bold; margin-bottom: 5px; }}
            .form-group input {{ width: 100%; padding: 8px; border: 1px solid #ccc; border-radius: 4px; }}
            .btn {{ background: #4CAF50; color: white; padding: 10px 15px; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; }}
            .btn:hover {{ background: #45a049; }}
            .status {{ padding: 10px; margin: 10px 0; border-radius: 4px; }}
            .status.connected {{ background: #d4edda; color: #155724; }}
            .status.disconnected {{ background: #f8d7da; color: #721c24; }}
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Medical AI Admin Panel</h1>
            
            <div class="status connected">✅ Sistem Bağlantıları Aktif</div>
            
            <div class="config-group">
                <h3>LLM Konfigürasyonu</h3>
                <div class="form-group">
                    <label for="llm_api_key">LLM API Key:</label>
                    <input type="text" id="llm_api_key" value="{llm_api_key}" placeholder="Güncel LLM API Key">
                </div>
                <div class="form-group">
                    <label for="llm_model">LLM Model:</label>
                    <input type="text" id="llm_model" value="{llm_model}" placeholder="Güncel LLM Model">
                </div>
            </div>
            
            <div class="config-group">
                <h3>RAG Konfigürasyonu</h3>
                <div class="form-group">
                    <label for="rag_top_k">RAG Top K:</label>
                    <input type="number" id="rag_top_k" value="{rag_top_k}" min="1" max="100">
                </div>
                <div class="form-group">
                    <label for="rag_chunk_size">RAG Chunk Size (char):</label>
                    <input type="number" id="rag_chunk_size" value="{rag_chunk_size}" min="100" max="2000">
                </div>
                <div class="form-group">
                    <label for="rag_overlap">RAG Overlap (char):</label>
                    <input type="number" id="rag_overlap" value="{rag_overlap}" min="10" max="500">
                </div>
            </div>
            
            <div class="form-group">
                <button class="btn" onclick="saveConfig()">💾 Kaydet</button>
            </div>
            
            <div class="config-group">
                <h3>SQL Test</h3>
                <div class="form-group">
                    <label for="sql_test">SQL Test:</label>
                    <input type="text" id="sql_test" value="SELECT 1 as test" placeholder="SQL Test">
                </div>
                <button class="btn" onclick="testSQL()">🧪 SQL Test Çalıştır</button>
            </div>
            
            <script>
                async function saveConfig() {{
                    fetch('/admin/api/config', {{
                        method: 'PUT',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{
                            key: 'llm_api_key',
                            value: document.getElementById('llm_api_key').value
                        }})
                    }}).then(r => r.json()).then(data => alert('✅ ' + JSON.stringify(data)));
                    fetch('/admin/api/config', {{
                        method: 'PUT',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{
                            key: 'llm_model',
                            value: document.getElementById('llm_model').value
                        }})
                    }}).then(r => r.json()).then(data => alert('✅ ' + JSON.stringify(data)));
                    fetch('/admin/api/config', {{
                        method: 'PUT',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{
                            key: 'rag_top_k',
                            value: document.getElementById('rag_top_k').value
                        }})
                    }}).then(r => r.json()).then(data => alert('✅ ' + JSON.stringify(data)));
                    fetch('/admin/api/config', {{
                        method: 'PUT',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{
                            key: 'rag_chunk_size',
                            value: document.getElementById('rag_chunk_size').value
                        }})
                    }}).then(r => r.json()).then(data => alert('✅ ' + JSON.stringify(data)));
                    fetch('/admin/api/config', {{
                        method: 'PUT',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{
                            key: 'rag_overlap',
                            value: document.getElementById('rag_overlap').value
                        }})
                    }}).then(r => r.json()).then(data => alert('✅ ' + JSON.stringify(data)));
                }}
                
                async function testSQL() {{
                    fetch('/admin/api/sql/execute', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{ sql: document.getElementById('sql_test').value }})
                    }}).then(r => r.json()).then(data => alert('✅ ' + JSON.stringify(data)));
                }}
            </script>
        </div>
    </body>
    </html>
    """

# --- Login Page ---
@html_router.get("/admin/login")
async def login_html():
    """GET /admin/login - HTML Login Page"""
    return f"""
    <!DOCTYPE html>
    <html>
    <head>
        <title>Medical AI - Giriş</title>
        <meta name="viewport" content="width=device-width,initial-scale=1">
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{ font-family: 'Inter', -apple-system, sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); min-height: 100vh; display: flex; align-items: center; justify-content: center; }}
            .login-container {{ background: white; padding: 40px; border-radius: 16px; box-shadow: 0 20px 60px rgba(0,0,0,0.3); width: 100%; max-width: 400px; text-align: center; }}
            .login-header {{ margin-bottom: 30px; }}
            .login-header h2 {{ font-size: 28px; color: #333; margin-bottom: 8px; }}
            .login-header p {{ color: #666; font-size: 14px; }}
            .form-group {{ margin-bottom: 20px; text-align: left; }}
            .form-group label {{ display: block; font-weight: 600; margin-bottom: 8px; color: #333; font-size: 14px; }}
            .form-group input {{ width: 100%; padding: 14px 16px; border: 2px solid #e0e0e0; border-radius: 8px; font-size: 15px; transition: all 0.3s; }}
            .form-group input:focus {{ border-color: #667eea; outline: none; box-shadow: 0 0 0 3px rgba(102,126,234,0.2); }}
            .login-btn {{ width: 100%; padding: 14px; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; border: none; border-radius: 8px; font-size: 16px; font-weight: 600; cursor: pointer; transition: all 0.3s; }}
            .login-btn:hover {{ transform: translateY(-2px); box-shadow: 0 8px 20px rgba(102,126,234,0.4); }}
            .login-btn:active {{ transform: translateY(0); }}
            .remember-forgot {{ display: flex; justify-content: space-between; margin-top: 20px; text-align: left; }}
            .remember-forgot a {{ color: #667eea; text-decoration: none; font-size: 13px; }}
            .remember-forgot a:hover {{ text-decoration: underline; }}
            .divider {{ margin: 25px 0; color: #999; font-size: 13px; }}
            .footer {{ margin-top: 30px; color: #999; font-size: 12px; }}
            .footer a {{ color: #667eea; text-decoration: none; }}
            .footer a:hover {{ text-decoration: underline; }}
            .spinner {{ display: none; border: 3px solid rgba(255,255,255,0.3); border-radius: 50%; border-top-color: white; width: 20px; height: 20px; animation: spin 1s linear infinite; margin: 0 auto; }}
            @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
        </style>
    </head>
    <body>
        <div class="login-container">
            <div class="login-header">
                <h2>Medical AI</h2>
                <p>Yönetici Girişi</p>
            </div>
            
            <form id="loginForm" onsubmit="handleLogin(event)">
                <div class="form-group">
                    <label for="email">E-posta</label>
                    <input type="email" id="email" name="email" required placeholder="admin@medicalai.com">
                </div>
                
                <div class="form-group">
                    <label for="password">Şifre</label>
                    <input type="password" id="password" name="password" required placeholder="********">
                </div>
                
                <button type="submit" class="login-btn" id="loginBtn">
                    <span class="btn-text">Giriş Yap</span>
                    <div class="spinner"></div>
                </button>
                
                <div class="remember-forgot">
                    <label><input type="checkbox"> Beni Hatırla</label>
                    <a href="#">Şifremi Unuttum?</a>
                </div>
            </form>
            
            <div class="divider">veya</div>
            
            <div class="footer">
                <p>&copy; 2024 Medical AI - Tüm Hakları Saklıdır</p>
            </div>
        </div>
        
        <script>
            async function handleLogin(event) {{
                event.preventDefault();
                const email = document.getElementById('email').value;
                const password = document.getElementById('password').value;
                const btn = document.getElementById('loginBtn');
                const btnText = btn.querySelector('.btn-text');
                const spinner = btn.querySelector('.spinner');
                
                btnText.style.display = 'none';
                spinner.style.display = 'block';
                
                try {{
                    const response = await fetch('/admin/api/auth/login', {{
                        method: 'POST',
                        headers: {{ 'Content-Type': 'application/json' }},
                        body: JSON.stringify({{
                            email: email,
                            password: password
                        }})
                    }});
                    
                    const data = await response.json();
                    
                    if (data.access_token) {{
                        localStorage.setItem('access_token', data.access_token);
                        localStorage.setItem('user_email', email);
                        window.location.href = '/admin';
                    }} else {{
                        alert('Giriş Hatası: ' + (data.detail || 'Bilinmeyen hata'));
                        btnText.style.display = 'block';
                        spinner.style.display = 'none';
                    }}
                }} catch (error) {{
                    alert('Giriş hatası: ' + error.message);
                    btnText.style.display = 'block';
                    spinner.style.display = 'none';
                }}
            }}
        </script>
    </body>
    </html>
    """

# --- Logout Handler ---
@html_router.get("/admin/logout")
async def logout(request: Request):
    """GET /admin/logout - Çıkış Yap"""
    # Clear client-side tokens
    # In a real app, you might want to invalidate the session on the server too
    return RedirectResponse(url="/admin/login", status_code=303)