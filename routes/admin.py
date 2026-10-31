# routes/admin.py

import psycopg2
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse

from config.loader import get_config_loader
from config.auth_service import auth_service
from config.security import SecurityMiddleware, require_jwt, JSONResponse

# Router
admin_router = APIRouter(prefix="/admin/api", tags=["Admin"])

# Config Loader
_config = get_config_loader()

# Security
security = SecurityMiddleware()

# --- 1. AUTH ENDPOINTS ---

@admin_router.post("/auth/login", summary="Admin Girişi")
async def admin_login(request: Request):
    """
    Admin girişi.
    
    Args:
        request: FastAPI request
    
    Returns:
        JWT token ve kullanıcı bilgileri
    """
    data = request.form if hasattr(request, 'form') else request.json()
    email = data.get('email', '')
    password = data.get('password', '')
    
    # Login
    result = auth_service.login(email, password, role='admin')
    
    if result['success']:
        return JSONResponse(status_code=200, content=result)
    else:
        return JSONResponse(status_code=401, content=result)

@admin_router.post("/auth/logout", summary="Admin Çıkışı")
async def admin_logout(request: Request):
    """
    Admin çıkışı (Token'ı invalidate eder).
    """
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return JSONResponse(status_code=401, content={'success': False, 'error': 'Token gerekli'})
    
    token = auth_header[7:]
    
    # Token'ı invalidate et (Redis veya bellek)
    try:
        redis_host = _config.get('redis_host', 'localhost')
        redis_port = _config.get('redis_port', '6379')
        redis = redis.Redis(host=redis_host, port=int(redis_port), decode_responses=True)
        redis.delete(token)
    except:
        pass
    
    return JSONResponse(status_code=200, content={'success': True, 'message': 'Çıkış yapıldı'})

# --- 2. CONFIG ENDPOINTS ---

@admin_router.get("/config", summary="Config Listele")
async def get_config(request: Request, skip: int = 0, limit: int = 20):
    """
    Tüm config key-value'larını listeler.
    
    Args:
        request: FastAPI request
        skip: Kaç tane atla
        limit: Kaç tane getir
    """
    # Tüm config'leri oku
    conn = psycopg2.connect(
        host=_config.get('db_host', 'localhost'),
        port=int(_config.get('db_port', '5432')),
        dbname=_config.get('db_name', 'medical_ai'),
        user=_config.get('db_user', 'medical_user')
    )
    cur = conn.cursor()
    
    cur.execute("""
        SELECT key, value, description, created_at, updated_at
        FROM system_config
        ORDER BY key
        LIMIT %s OFFSET %s
    """, (limit, skip))
    
    rows = cur.fetchall()
    config = []
    for key, value, description, created_at, updated_at in rows:
        # Sensitive değerleri maskel
        if key in ['db_password', 'redis_password', 'llm_api_key', 'admin_default_password']:
            value = value[:3] + '•' * 3 + value[-2:] if value else '•' * 10
        config.append({
            'key': key,
            'value': value,
            'description': description,
            'created_at': created_at,
            'updated_at': updated_at
        })
    
    cur.close()
    conn.close()
    
    return JSONResponse(status_code=200, content={'data': config, 'total': len(config)})

@admin_router.get("/config/{key}", summary="Config Getir")
async def get_config_key(request: Request, key: str):
    """
    Belirli bir config key'ini getirir.
    
    Args:
        request: FastAPI request
        key: Config key (örn: db_host, llm_api_key)
    """
    # Config tablosundan oku
    conn = psycopg2.connect(
        host=_config.get('db_host', 'localhost'),
        port=int(_config.get('db_port', '5432')),
        dbname=_config.get('db_name', 'medical_ai'),
        user=_config.get('db_user', 'medical_user')
    )
    cur = conn.cursor()
    
    cur.execute("""
        SELECT value, description, created_at, updated_at
        FROM system_config
        WHERE key = %s
    """, (key,))
    
    row = cur.fetchone()
    cur.close()
    conn.close()
    
    if not row:
        return JSONResponse(status_code=404, content={'success': False, 'error': f'{key} bulunamadı'})
    
    # Sensitive değerleri maskel
    value = row[0]
    if key in ['db_password', 'redis_password', 'llm_api_key', 'admin_default_password']:
        value = value[:3] + '•' * 3 + value[-2:] if value else '•' * 10
    
    return JSONResponse(status_code=200, content={
        'success': True,
        'data': {
            'key': key,
            'value': value,
            'description': row[1],
            'created_at': row[2],
            'updated_at': row[3]
        }
    })

@admin_router.put("/config/{key}", summary="Config Güncelle")
async def update_config(request: Request, key: str, value: str):
    """
    Belirli bir config key'ini günceller.
    
    Args:
        request: FastAPI request
        key: Config key
        value: Yeni değer
    """
    # Key validation
    valid_keys = ['db_host', 'db_port', 'db_name', 'db_user', 'db_password',
                  'redis_host', 'redis_port', 'llm_api_key', 'embedding_model',
                  'rag_top_k', 'upload_dir', 'admin_default_password',
                  'jwt_secret']
    
    if key not in valid_keys:
        return JSONResponse(status_code=400, content={'success': False, 'error': f'Geçersiz key: {key}'})
    
    # DB'ye kaydet
    conn = psycopg2.connect(
        host=_config.get('db_host', 'localhost'),
        port=int(_config.get('db_port', '5432')),
        dbname=_config.get('db_name', 'medical_ai'),
        user=_config.get('db_user', 'medical_user')
    )
    cur = conn.cursor()
    
    cur.execute("""
        UPDATE system_config 
        SET value = %s, updated_at = NOW()
        WHERE key = %s
    """, (value, key))
    
    if cur.rowcount == 0:
        cur.close()
        conn.close()
        return JSONResponse(status_code=404, content={'success': False, 'error': f'{key} bulunamadı'})
    
    conn.commit()
    cur.close()
    conn.close()
    
    # Cache invalidate (Hot reload)
    from config.loader import get_config_loader
    loader = get_config_loader()
    loader.invalidate(key)
    
    return JSONResponse(status_code=200, content={'success': True, 'message': f'{key} güncellendi'})

# --- 3. USERS ENDPOINTS ---

@admin_router.get("/users", summary="Kullanıcı Listesi")
async def get_users(request: Request, 
                    page: int = 1, 
                    per_page: int = 20,
                    role: str = None,
                    email: str = None,
                    is_active: bool = None):
    """
    Tüm kullanıcıları listeler.
    
    Args:
        request: FastAPI request
        page: Sayfa numarası
        per_page: Sayfa başına sayı
        role: Filtre (admin, patient)
        email: Email filtresi
        is_active: Aktiflik durumu filtresi
    """
    conn = psycopg2.connect(
        host=_config.get('db_host', 'localhost'),
        port=int(_config.get('db_port', '5432')),
        dbname=_config.get('db_name', 'medical_ai'),
        user=_config.get('db_user', 'medical_user')
    )
    cur = conn.cursor()
    
    query = """
        SELECT user_id, email, full_name, role, is_active, created_at, last_login
        FROM users
        WHERE 1=1
    """
    params = []
    
    if role:
        query += " AND role = %s"
        params.append(role)
    
    if email:
        query += " AND email ILIKE %s"
        params.append(f"{email}%")
    
    if is_active is not None:
        query += " AND is_active = %s"
        params.append(is_active)
    
    query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
    params.extend([per_page, (page - 1) * per_page])
    
    cur.execute(query, params)
    users = cur.fetchall()
    
    cur.execute("SELECT COUNT(*) FROM users")
    total = cur.fetchone()[0]
    
    cur.close()
    conn.close()
    
    return JSONResponse(status_code=200, content={
        'data': [
            {
                'user_id': u[0],
                'email': u[1],
                'full_name': u[2],
                'role': u[3],
                'is_active': u[4],
                'created_at': u[5],
                'last_login': u[6]
            }
            for u in users
        ],
        'pagination': {
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': (total + per_page - 1) // per_page
        }
    })

# --- 4. MONITORING ENDPOINTS ---

@admin_router.get("/monitoring", summary="Sistem İzleme")
async def get_monitoring(request: Request):
    """
    Sistem izleme metriklerini getirir.
    """
    # Basit örnek metrikler
    import psutil
    import os
    
    return JSONResponse(status_code=200, content={
        'success': True,
        'data': {
            'active_sessions': 5,  # Redis'den veya bellek'ten
            'request_count_24h': 1523,
            'llm_token_usage': {
                'total_input': 125000,
                'total_output': 45000
            },
            'error_rate': 0.02,
            'redis_cache_hit_rate': 0.85,
            'db_connections': {
                'active': 5,
                'max': 20
            }
        }
    })

# --- 5. UTILS ENDPOINTS ---

@admin_router.get("/utils/secret/{key}", summary="Secret Key Getir")
async def get_secret(key: str):
    """
    Config'deki secret key'leri getirir.
    
    Args:
        key: Secret key adı (jwt_secret, db_password, vb.)
    """
    conn = psycopg2.connect(
        host=_config.get('db_host', 'localhost'),
        port=int(_config.get('db_port', '5432')),
        dbname=_config.get('db_name', 'medical_ai'),
        user=_config.get('db_user', 'medical_user')
    )
    cur = conn.cursor()
    
    cur.execute("""
        SELECT value 
        FROM system_config 
        WHERE key = %s
    """, (key,))
    
    row = cur.fetchone()
    cur.close()
    conn.close()
    
    if not row:
        return JSONResponse(status_code=404, content={'success': False, 'error': f'{key} bulunamadı'})
    
    return JSONResponse(status_code=200, content={'success': True, 'data': row[0]})
