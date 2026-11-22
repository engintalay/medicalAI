# routes/admin.py

import asyncio
import json
import os
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request as UrlRequest, urlopen

import psycopg2
import redis
from fastapi import APIRouter, Body, Request
from fastapi.responses import JSONResponse as _FastJSONResponse
from fastapi.encoders import jsonable_encoder


class JSONResponse(_FastJSONResponse):
    """datetime/Decimal gibi tipleri otomatik JSON'a çeviren JSONResponse."""

    def render(self, content) -> bytes:
        return super().render(jsonable_encoder(content))


from config.loader import get_config_loader
from config.auth_service import auth_service
from models.health import HealthMetricCreate, HealthMetricUpdate, HealthMetricResponse, format_metric_response, format_metric_list
from routines.health import (
    create_health_metric,
    get_health_metrics,
    get_health_metric_by_id,
    update_health_metric,
    delete_health_metric,
    get_health_stats
)

# Router
admin_router = APIRouter(prefix="/admin/api", tags=["Admin"])

# HealthMetrics Router
health_router = APIRouter(prefix="/admin/api/health", tags=["Health Metrics"])

# Config Loader
_config = get_config_loader()

# Gizli değerler (API'de maskelenir, UI'da düzenlenirken boş gösterilir)
SECRET_KEYS = {
    'db_password',
    'redis_password',
    'llm_api_key',
    'vision_llm_api_key',
    'admin_default_password',
    'jwt_secret',
}


def _mask_secret(value: str) -> str:
    if not value:
        return '•' * 10
    if len(value) <= 5:
        return '•' * 10
    return value[:3] + '•' * 3 + value[-2:]

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
    # Frontend gonderi JSON; form verisi icin de destekle.
    # (Request.json / Request.form async metotlerdir -> await gerektirir)
    try:
        data = await request.json()
    except Exception:
        form = await request.form()
        data = dict(form)
    if not isinstance(data, dict):
        data = {}
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
    Admin çıkışı: token'ı Redis kara listesine ekler.
    """
    auth_header = request.headers.get('Authorization', '')
    if not auth_header.startswith('Bearer '):
        return JSONResponse(status_code=401, content={'success': False, 'error': 'Token gerekli'})

    token = auth_header[7:]
    revoked = auth_service.revoke_token(token)

    return JSONResponse(status_code=200, content={
        'success': True,
        'message': 'Çıkış yapıldı',
        'revoked': revoked,
    })

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
        user=_config.get('db_user', 'medical_user'),
        password=_config.get('db_password', '')
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
        is_secret = key in SECRET_KEYS
        # Sensitive değerleri maskele
        if is_secret:
            value = _mask_secret(value)
        config.append({
            'key': key,
            'value': value,
            'description': description,
            'is_secret': is_secret,
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
        user=_config.get('db_user', 'medical_user'),
        password=_config.get('db_password', '')
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
    is_secret = key in SECRET_KEYS
    value = row[0]
    if is_secret:
        value = _mask_secret(value)
    
    return JSONResponse(status_code=200, content={
        'success': True,
        'data': {
            'key': key,
            'value': value,
            'description': row[1],
            'is_secret': is_secret,
            'created_at': row[2],
            'updated_at': row[3]
        }
    })

@admin_router.put("/config/{key}", summary="Config Güncelle")
async def update_config(request: Request, key: str, value: str = None):
    """
    Belirli bir config key'ini günceller.

    Değer JSON gövdesinden ({ "value": "..." }) veya query parametresinden
    (?value=...) okunabilir. Frontend JSON gövdesi gönderir.

    Args:
        request: FastAPI request
        key: Config key
        value: Yeni değer (query param, opsiyonel)
    """
    # JSON gövdesi desteği (frontend {value} gönderiyor)
    if value is None:
        try:
            body = await request.json()
        except Exception:
            body = None
        if isinstance(body, dict):
            value = body.get('value')

    if value is None:
        return JSONResponse(
            status_code=422,
            content={'success': False, 'error': 'Yeni değer gerekli (JSON: {"value": "..."})'}
        )

    value = str(value)

    # Key validation
    valid_keys = {
        'db_host', 'db_port', 'db_name', 'db_user', 'db_password',
        'redis_host', 'redis_port', 'redis_password', 'redis_username',
        'llm_api_key', 'llm_model', 'llm_provider', 'llm_base_url',
        'llm_vision_supported', 'vision_llm_enabled',
        'vision_llm_provider', 'vision_llm_model', 'vision_llm_api_key', 'vision_llm_base_url',
        'embedding_model', 'rag_top_k', 'rag_chunk_size', 'rag_overlap',
        'upload_dir', 'admin_default_password', 'jwt_secret',
    }

    if key not in valid_keys:
        return JSONResponse(status_code=400, content={'success': False, 'error': f'Geçersiz key: {key}'})

    # DB'ye kaydet
    conn = psycopg2.connect(
        host=_config.get('db_host', 'localhost'),
        port=int(_config.get('db_port', '5432')),
        dbname=_config.get('db_name', 'medical_ai'),
        user=_config.get('db_user', 'medical_user'),
        password=_config.get('db_password', '')
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
    
    # Cache'i güncelle (hot reload)
    loader = get_config_loader()
    loader.set(key, value)
    
    return JSONResponse(status_code=200, content={'success': True, 'message': f'{key} güncellendi'})


# --- 2b. LLM MODEL LİSTELEME ENDPOINT'İ ---

LLM_PROVIDER_DEFAULTS = {
    'openai': 'https://api.openai.com/v1',
    'ollama': 'http://localhost:11434',
}
LLM_SUPPORTED_PROVIDERS = {'openai', 'custom', 'ollama'}

# Bazı sağlayıcılar (Cloudflare arkasındaki llama.cpp sunucuları gibi) Python
# varsayılan User-Agent'ını Error 1010 ile engeller. Tarayıcı benzeri bir
# başlık göndererek model listesinin alınmasını sağlıyoruz.
LLM_HTTP_HEADERS = {
    'Accept': 'application/json',
    'User-Agent': (
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 '
        '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    ),
}


def _resolve_llm_base_url(provider: str, base_url: str) -> str:
    """Base URL'i çözer ve doğrular. Boşsa sağlayıcı varsayılanını kullanır."""
    resolved = (base_url or '').strip().rstrip('/')
    if not resolved:
        resolved = LLM_PROVIDER_DEFAULTS.get(provider, '')
    if not resolved:
        raise ValueError('OpenAI uyumlu (custom) sağlayıcı için API Base URL zorunludur.')

    parsed = urlparse(resolved)
    if parsed.scheme not in ('http', 'https') or not parsed.netloc:
        raise ValueError('API Base URL geçerli bir http(s) adresi olmalıdır.')
    if parsed.username or parsed.password:
        raise ValueError('API Base URL kullanıcı adı/şifre içeremez; kimlik bilgilerini API anahtarı alanına girin.')
    return resolved


def _extract_models(payload, provider: str):
    """Sağlayıcı yanıtından model kimliklerini çıkarır."""
    if isinstance(payload, dict) and isinstance(payload.get('error'), dict):
        message = payload['error'].get('message') or 'Bilinmeyen API hatası'
        raise ValueError(str(message)[:300])
    if not isinstance(payload, dict):
        raise ValueError('API beklenmeyen bir yanıt döndürdü.')

    if provider == 'ollama':
        entries = payload.get('models') or []
        field = 'name'
    else:
        entries = payload.get('data') or []
        field = 'id'

    if not isinstance(entries, list):
        raise ValueError('API model listesi beklenen biçimde değil.')

    models = []
    for entry in entries:
        value = None
        if isinstance(entry, dict):
            value = entry.get(field)
        elif isinstance(entry, str):
            value = entry
        if value:
            value = str(value).strip()
            if value and value not in models:
                models.append(value)

    if not models:
        raise ValueError('API bu yapılandırma ile herhangi bir model döndürmedi.')
    return sorted(models)[:500]


def _fetch_models_from_api(provider: str, base_url: str, api_key: str):
    """Model listesini senkron olarak çeker (threadpool içinde çağrılır)."""
    resolved = _resolve_llm_base_url(provider, base_url)

    if provider == 'ollama':
        url = resolved + '/api/tags'
        headers = dict(LLM_HTTP_HEADERS)
    else:
        if not api_key:
            raise ValueError('API anahtarı boş. Anahtarı girin veya önce kaydedin.')
        url = resolved + '/models'
        headers = dict(LLM_HTTP_HEADERS)
        headers['Authorization'] = 'Bearer ' + api_key

    request = UrlRequest(url, headers=headers, method='GET')
    try:
        with urlopen(request, timeout=10) as response:
            raw = response.read(1024 * 1024)
    except HTTPError as exc:
        detail = ''
        try:
            detail = exc.read(300).decode('utf-8', errors='replace')
            detail = ' '.join(detail.split())[:160]
        except Exception:
            pass
        message = 'Model listesi alınamadı (HTTP %s).' % exc.code
        if detail:
            message += ' Sunucu: ' + detail
        message += ' API anahtarını ve base URL değerini kontrol edin.'
        raise ValueError(message)
    except URLError as exc:
        raise ValueError('Model listesine ulaşılamadı: %s' % str(exc.reason)[:200])
    except TimeoutError:
        raise ValueError('Model listesi zaman aşımına uğradı (10 sn).')

    try:
        payload = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise ValueError('API geçersiz JSON döndürdü.')

    return {'models': _extract_models(payload, provider), 'base_url': resolved}


@admin_router.post("/llm/models", summary="LLM Modellerini Listele")
async def list_llm_models(request: Request):
    """
    API anahtarı ve base URL ile sağlayıcıdan model listesini çeker.

    İstekte yeni bir api_key gönderilirse o kullanılır; gönderilmezse kayıtlı
    anahtar kullanılır. Yeni anahtar bu istekle birlikte kaydedilmez.
    """
    try:
        body = await request.json()
    except Exception:
        body = None
    if not isinstance(body, dict):
        return JSONResponse(status_code=422, content={
            'success': False, 'error': 'JSON gövdesi gerekli.'
        })

    scope = str(body.get('scope') or 'primary').strip().lower()
    provider = str(body.get('provider') or 'openai').strip().lower()
    base_url = str(body.get('base_url') or '')
    # Formda yeni yazılmış anahtar varsa o kullanılır; aksi halde kayıtlı anahtar.
    api_key = str(body.get('api_key') or '').strip()

    if scope not in ('primary', 'vision'):
        return JSONResponse(status_code=400, content={
            'success': False, 'error': 'Geçersiz scope: ' + scope
        })
    if provider not in LLM_SUPPORTED_PROVIDERS:
        return JSONResponse(status_code=400, content={
            'success': False,
            'error': 'Bu sağlayıcı için model listeleme desteklenmiyor: ' + provider
        })

    if not api_key:
        api_key = _config.get('llm_api_key' if scope == 'primary' else 'vision_llm_api_key') or ''

    try:
        result = await asyncio.to_thread(_fetch_models_from_api, provider, base_url, api_key)
    except ValueError as exc:
        return JSONResponse(status_code=400, content={'success': False, 'error': str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=502, content={
            'success': False, 'error': 'Model listesi alınamadı: ' + str(exc)[:200]
        })

    return JSONResponse(status_code=200, content={'success': True, 'data': result})


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
        user=_config.get('db_user', 'medical_user'),
        password=_config.get('db_password', '')
    )
    cur = conn.cursor()
    
    query = """
        SELECT user_id, email, full_name, role, is_active, created_at, last_login
        FROM users
        WHERE 1=1
    """
    params = []
    conditions = []
    
    if role:
        conditions.append("role = %s")
        params.append(role)
    
    if email:
        conditions.append("email ILIKE %s")
        params.append(f"%{email}%")
    
    if is_active is not None:
        conditions.append("is_active = %s")
        params.append(is_active)

    if conditions:
        query += " AND " + " AND ".join(conditions)

    count_query = "SELECT COUNT(*) FROM users"
    if conditions:
        count_query += " WHERE " + " AND ".join(conditions)
    cur.execute(count_query, params)
    total = cur.fetchone()[0]

    query += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
    params.extend([per_page, (page - 1) * per_page])
    
    cur.execute(query, params)
    users = cur.fetchall()
    
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

    PostgreSQL/Redis bağlantı durumu, veritabanı bağlantı havuzu ve
    CPU/bellek/disk gibi gerçek sunucu metriklerini döner.
    """
    import psutil

    db_info = {
        'connected': False,
        'host': _config.get('db_host', 'localhost'),
        'port': _config.get('db_port', '5432'),
        'name': _config.get('db_name', ''),
    }
    redis_info = {
        'connected': False,
        'host': _config.get('redis_host', 'localhost'),
        'port': _config.get('redis_port', '6379'),
    }
    active_connections = 0
    max_connections = 0
    active_sessions = 0

    # --- PostgreSQL ---
    try:
        started = time.perf_counter()
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT COUNT(*) FROM pg_stat_activity WHERE datname = current_database()"
            )
            active_connections = cur.fetchone()[0]
            cur.execute("SHOW max_connections")
            max_connections = int(cur.fetchone()[0])
            cur.execute(
                "SELECT COUNT(*) FROM users WHERE last_login >= NOW() - INTERVAL '24 hours'"
            )
            active_sessions = cur.fetchone()[0]
            cur.execute("SELECT version()")
            version = cur.fetchone()[0]
            cur.close()
        finally:
            conn.close()
        db_info.update({
            'connected': True,
            'latency_ms': round((time.perf_counter() - started) * 1000, 2),
            'version': (version.split(' ')[1] if version and len(version.split(' ')) > 1 else version or ''),
        })
    except Exception as exc:
        db_info['error'] = str(exc)

    # --- Redis ---
    try:
        started = time.perf_counter()
        redis_port = int(_config.get('redis_port', '6379'))
        redis_password = _config.get('redis_password') or os.getenv('REDIS_PASSWORD') or None
        redis_username = os.getenv('REDIS_USERNAME') or None
        r = redis.Redis(
            host=_config.get('redis_host', 'localhost'),
            port=redis_port,
            password=redis_password,
            username=redis_username,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        ping = r.ping()
        stats = r.info('stats') or {}
        hits = int(stats.get('keyspace_hits', 0) or 0)
        misses = int(stats.get('keyspace_misses', 0) or 0)
        cache_hit_rate = (hits / (hits + misses)) if (hits + misses) else 0.0
        redis_info.update({
            'connected': bool(ping),
            'latency_ms': round((time.perf_counter() - started) * 1000, 2),
            'cache_hit_rate': cache_hit_rate,
        })
    except Exception as exc:
        cache_hit_rate = 0.0
        redis_info['error'] = str(exc)

    # --- Sunucu kaynakları ---
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage('/')
    boot_time = psutil.boot_time()
    process = psutil.Process(os.getpid())

    llm_api_key = (_config.get('llm_api_key') or '').strip()

    return JSONResponse(status_code=200, content={
        'success': True,
        'data': {
            'active_sessions': active_sessions,
            # Uygulama içi istek sayacı henüz tutulmuyor.
            'request_count_24h': 0,
            'llm_token_usage': {'total_input': 0, 'total_output': 0},
            'error_rate': 0.0,
            'redis_cache_hit_rate': cache_hit_rate,
            'db_connections': {
                'active': active_connections,
                'max': max_connections,
            },
            'database': db_info,
            'redis': redis_info,
            'llm': {
                'configured': bool(llm_api_key),
                'model': _config.get('llm_model', '') or '',
            },
            'system': {
                'cpu_percent': psutil.cpu_percent(interval=None),
                'process_cpu_percent': process.cpu_percent(interval=None),
                'memory_percent': memory.percent,
                'memory_used_mb': round(memory.used / (1024 * 1024), 1),
                'memory_total_mb': round(memory.total / (1024 * 1024), 1),
                'disk_percent': disk.percent,
                'disk_used_gb': round(disk.used / (1024 ** 3), 1),
                'disk_total_gb': round(disk.total / (1024 ** 3), 1),
                'uptime_hours': round((time.time() - boot_time) / 3600, 1),
                'process_memory_mb': round(process.memory_info().rss / (1024 * 1024), 1),
            },
        }
    })

# --- 6. HEALTH METRICS ENDPOINTS ---

def _get_conn():
    """Yeni bir PostgreSQL bağlantısı açar (config loader'dan okunan ayarlar)."""
    return psycopg2.connect(
        host=_config.get('db_host', 'localhost'),
        port=int(_config.get('db_port', '5432')),
        dbname=_config.get('db_name', 'medical_ai'),
        user=_config.get('db_user', 'medical_user'),
        password=_config.get('db_password', '')
    )


@health_router.post("/metrics", summary="Health Metric Ekle")
async def create_health_metric_endpoint(
    request: Request,
    user_id: int,
    metrics: HealthMetricCreate = Body(...),
):
    """Yeni bir sağlık metrik kaydı ekler.

    Query: user_id (kaydı hangi kullanıcıya bağlayacağını belirtir)
    Body: {metric_name, value, unit, recorded_at?}
    """
    try:
        conn = _get_conn()
        try:
            value = float(metrics.value)
            created_id = create_health_metric(
                conn, user_id, metrics.metric_name, value,
                metrics.unit, metrics.recorded_at
            )
            metric = get_health_metric_by_id(conn, created_id, user_id)
            return JSONResponse(status_code=201, content={'success': True, 'data': metric})
        finally:
            conn.close()
    except Exception as e:
        return JSONResponse(status_code=500, content={'success': False, 'error': str(e)})


@health_router.get("/metrics", summary="Health Metric Listele")
async def list_health_metrics(
    request: Request,
    user_id: int,
    metric_name: str = None,
    page: int = 1,
    limit: int = 50,
):
    """Kullanıcının sağlık metriklerini listeler (sayfalı).

    Query: user_id, metric_name?, page, limit
    """
    try:
        conn = _get_conn()
        try:
            metrics, total = get_health_metrics(
                conn, user_id, metric_name,
                limit=int(limit), offset=(page - 1) * int(limit)
            )
            return JSONResponse(status_code=200, content={
                'success': True,
                'data': format_metric_list(metrics),
                'pagination': {
                    'page': page,
                    'per_page': limit,
                    'total': total,
                    'total_pages': (total + limit - 1) // limit if limit else 0,
                },
            })
        finally:
            conn.close()
    except Exception as e:
        return JSONResponse(status_code=500, content={'success': False, 'error': str(e)})


@health_router.get("/metrics/{metric_id}", summary="Health Metric Getir")
async def get_health_metric_endpoint(
    request: Request,
    metric_id: int,
    user_id: int,
):
    """Tek bir sağlık metrikini getirir (kullanıcı sahiplik kontrolü)."""
    try:
        conn = _get_conn()
        try:
            metric = get_health_metric_by_id(conn, metric_id, user_id)
            if not metric:
                return JSONResponse(status_code=404, content={'success': False, 'error': f'metric_id {metric_id} bulunamadı'})
            return JSONResponse(status_code=200, content={'success': True, 'data': metric})
        finally:
            conn.close()
    except Exception as e:
        return JSONResponse(status_code=500, content={'success': False, 'error': str(e)})


@health_router.put("/metrics/{metric_id}", summary="Health Metric Güncelle")
async def update_health_metric_endpoint(
    request: Request,
    metric_id: int,
    user_id: int,
    metrics: HealthMetricUpdate = Body(...),
):
    """Mevcut bir sağlık metrikini günceller (kullanıcı sahiplik kontrolü)."""
    try:
        conn = _get_conn()
        try:
            updated = update_health_metric(
                conn, metric_id, user_id,
                metrics.metric_name, metrics.value, metrics.unit, metrics.recorded_at
            )
            if not updated:
                return JSONResponse(status_code=404, content={'success': False, 'error': f'metric_id {metric_id} bulunamadı'})
            metric = get_health_metric_by_id(conn, metric_id, user_id)
            return JSONResponse(status_code=200, content={'success': True, 'data': metric})
        finally:
            conn.close()
    except Exception as e:
        return JSONResponse(status_code=500, content={'success': False, 'error': str(e)})


@health_router.delete("/metrics/{metric_id}", summary="Health Metric Sil")
async def delete_health_metric_endpoint(
    request: Request,
    metric_id: int,
    user_id: int,
):
    """Bir sağlık metrikini siler (kullanıcı sahiplik kontrolü)."""
    try:
        conn = _get_conn()
        try:
            deleted = delete_health_metric(conn, metric_id, user_id)
            if not deleted:
                return JSONResponse(status_code=404, content={'success': False, 'error': f'metric_id {metric_id} bulunamadı'})
            return JSONResponse(status_code=200, content={'success': True, 'message': f'metric_id {metric_id} silindi'})
        finally:
            conn.close()
    except Exception as e:
        return JSONResponse(status_code=500, content={'success': False, 'error': str(e)})


@health_router.get("/stats", summary="Health İstatistikleri")
async def health_stats_endpoint(
    request: Request,
    user_id: int,
    metric_name: str = None,
    days: int = 30,
):
    """Kullanıcının sağlık metrik istatistiklerini getirir.

    Query: user_id, metric_name?, days (varsayılan 30)
    """
    try:
        conn = _get_conn()
        try:
            stats = get_health_stats(conn, user_id, metric_name, int(days))
            return JSONResponse(status_code=200, content={'success': True, 'data': stats})
        finally:
            conn.close()
    except Exception as e:
        return JSONResponse(status_code=500, content={'success': False, 'error': str(e)})


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
        user=_config.get('db_user', 'medical_user'),
        password=_config.get('db_password', '')
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


# --- 7. BAĞLANTI TEST ENDPOINT'LERİ ---

@admin_router.post("/utils/test-db", summary="PostgreSQL Bağlantı Testi")
async def test_db_connection():
    """Mevcut config ile PostgreSQL bağlantısını test eder."""
    started = time.perf_counter()
    try:
        conn = _get_conn()
        try:
            cur = conn.cursor()
            cur.execute("SELECT current_database(), current_user, version()")
            database, user, version = cur.fetchone()
            cur.close()
        finally:
            conn.close()

        return JSONResponse(status_code=200, content={
            'success': True,
            'data': {
                'database': database,
                'user': user,
                'version': (version.split(' ')[1] if version and len(version.split(' ')) > 1 else version or ''),
                'latency_ms': round((time.perf_counter() - started) * 1000, 2),
            }
        })
    except Exception as exc:
        return JSONResponse(status_code=503, content={
            'success': False,
            'error': f'PostgreSQL bağlantı hatası: {exc}',
        })


@admin_router.post("/utils/test-redis", summary="Redis Bağlantı Testi")
async def test_redis_connection():
    """Mevcut config ile Redis bağlantısını test eder."""
    started = time.perf_counter()
    try:
        redis_password = _config.get('redis_password') or os.getenv('REDIS_PASSWORD') or None
        redis_username = os.getenv('REDIS_USERNAME') or None
        client = redis.Redis(
            host=_config.get('redis_host', 'localhost'),
            port=int(_config.get('redis_port', '6379')),
            password=redis_password,
            username=redis_username,
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        pong = client.ping()

        return JSONResponse(status_code=200, content={
            'success': True,
            'data': {
                'ping': 'PONG' if pong else 'FAIL',
                'latency_ms': round((time.perf_counter() - started) * 1000, 2),
            }
        })
    except Exception as exc:
        return JSONResponse(status_code=503, content={
            'success': False,
            'error': f'Redis bağlantı hatası: {exc}',
        })
