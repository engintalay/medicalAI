# routes/admin.py

import asyncio
import base64
import json
import os
import re
import struct
import time
import zlib
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
from models.health import (
    HealthMetricCreate,
    HealthMetricUpdate,
    HealthMetricResponse,
    HealthMetricDefinitionCreate,
    HealthMetricDefinitionUpdate,
    format_metric_response,
    format_metric_list,
)
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
        'llm_max_tokens', 'llm_timeout', 'llm_thinking',
        'llm_vision_supported', 'vision_llm_enabled',
        'vision_llm_provider', 'vision_llm_model', 'vision_llm_api_key', 'vision_llm_base_url',
        'vision_max_tokens', 'vision_timeout', 'vision_thinking',
        'embedding_model', 'rag_top_k', 'rag_chunk_size', 'rag_overlap',
        'upload_dir', 'max_upload_mb', 'admin_default_password', 'jwt_secret',
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


def _sanitize_llm_detail(raw: bytes, api_key: str) -> str:
    """Sunucu hata metninden API anahtarını temizler."""
    detail = raw.decode('utf-8', errors='replace')
    detail = ' '.join(detail.split())[:200]
    if api_key:
        detail = detail.replace(api_key, '***')
    return detail


def _test_image_data_url() -> str:
    """Test için stdlib ile 64x64 kırmızı PNG üretir (harici bağımlılık yok)."""
    width = height = 64
    row = b'\x00' + bytes((220, 30, 40)) * width
    raw = row * height

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack('>I', len(data)) + tag + data +
                struct.pack('>I', zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = (b'\x89PNG\r\n\x1a\n' +
           chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)) +
           chunk(b'IDAT', zlib.compress(raw)) +
           chunk(b'IEND', b''))
    return 'data:image/png;base64,' + base64.b64encode(png).decode('ascii')


def _chat_completion_probe(
    provider: str, base_url: str, api_key: str, model: str, image_url: str | None = None,
    thinking: bool = False,
) -> dict:
    """LLM'e ping (veya görsel) gönderir; cevap süresini ve metni döner."""
    endpoint_base = base_url
    if provider == 'ollama' and not endpoint_base.endswith('/v1'):
        endpoint_base += '/v1'

    if image_url:
        user_content = [
            {'type': 'text', 'text': 'Bu görselin ana rengi nedir? Sadece renk adını yazın.'},
            {'type': 'image_url', 'image_url': {'url': image_url}},
        ]
    else:
        user_content = 'Ping. Lütfen sadece "pong" yazın.'

    payload = {
        'model': model,
        'temperature': 0,
        # Yerel 27B modellerde 256 token dakikalar sürebilir; ping için 64 yeterli.
        'max_tokens': 64,
        'messages': [{'role': 'user', 'content': user_content}],
    }
    if not thinking:
        if provider in ('custom', 'ollama'):
            payload['reasoning_effort'] = 'none'
            payload['chat_template_kwargs'] = {'enable_thinking': False}
        elif provider == 'openai':
            payload['reasoning_effort'] = 'none'
    headers = dict(LLM_HTTP_HEADERS)
    headers['Content-Type'] = 'application/json'
    if api_key and provider != 'ollama':
        headers['Authorization'] = 'Bearer ' + api_key

    request = UrlRequest(
        endpoint_base + '/chat/completions',
        data=json.dumps(payload).encode('utf-8'),
        headers=headers,
        method='POST',
    )
    started = time.perf_counter()
    try:
        timeout = float(_config.get('llm_timeout', '180') or 180)
    except (TypeError, ValueError):
        timeout = 180
    try:
        with urlopen(request, timeout=max(30, min(timeout, 600))) as response:
            raw = response.read(256 * 1024)
    except HTTPError as exc:
        detail = ''
        try:
            detail = _sanitize_llm_detail(exc.read(400), api_key)
        except Exception:
            pass
        message = 'LLM yanıt vermedi (HTTP %s).' % exc.code
        if detail:
            message += ' Sunucu: ' + detail
        raise ValueError(message)
    except (URLError, TimeoutError) as exc:
        reason = getattr(exc, 'reason', exc)
        raise ValueError('LLM erişilemedi: ' + str(reason)[:160])

    latency_ms = round((time.perf_counter() - started) * 1000)
    try:
        payload = json.loads(raw.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        raise ValueError('LLM geçersiz JSON döndürdü.')

    if not isinstance(payload, dict):
        raise ValueError('LLM beklenmeyen bir yanıt döndürdü.')
    if isinstance(payload.get('error'), dict):
        raise ValueError('LLM hatası: ' + str(payload['error'].get('message') or '')[:200])
    choices = payload.get('choices') or []
    if not choices or not isinstance(choices, list):
        raise ValueError('LLM boş yanıt döndürdü.')

    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get('message') or {}
    content = message.get('content') or first.get('text') or ''
    if not content:
        content = message.get('reasoning_content') or first.get('reasoning_content') or ''
    if isinstance(content, list):
        content = '\n'.join(
            str(part.get('text') or '') if isinstance(part, dict) else str(part)
            for part in content
        )
    reply = re.sub(r'<think>.*?</think>', '', str(content), flags=re.S | re.I).strip()[:200]
    if not reply:
        raise ValueError('LLM boş metin döndürdü.')

    return {
        'ok': True,
        'reply': reply,
        'latency_ms': latency_ms,
        'model': model,
        'base_url': base_url,
        'test': 'vision' if image_url else 'text',
    }


def _prepare_llm_test(body):
    """Ortak doğrulama. (params, None) veya (None, JSONResponse) döner."""
    if not isinstance(body, dict):
        return None, JSONResponse(status_code=422, content={
            'success': False, 'error': 'JSON gövdesi gerekli.'
        })

    scope = str(body.get('scope') or 'primary').strip().lower()
    provider = str(body.get('provider') or 'openai').strip().lower()
    base_url = str(body.get('base_url') or '')
    api_key = str(body.get('api_key') or '').strip()
    model = str(body.get('model') or '').strip()

    if scope not in ('primary', 'vision'):
        return None, JSONResponse(status_code=400, content={
            'success': False, 'error': 'Geçersiz scope: ' + scope
        })
    if provider not in LLM_SUPPORTED_PROVIDERS:
        return None, JSONResponse(status_code=400, content={
            'success': False, 'error': 'Desteklenmeyen sağlayıcı: ' + provider
        })

    if not api_key:
        api_key = _config.get('llm_api_key' if scope == 'primary' else 'vision_llm_api_key') or ''
    if not model:
        model = _config.get('llm_model' if scope == 'primary' else 'vision_llm_model') or ''
    if not model:
        return None, JSONResponse(status_code=400, content={
            'success': False, 'error': 'Test için model seçilmedi.'
        })

    try:
        resolved = _resolve_llm_base_url(provider, base_url)
    except ValueError as exc:
        return None, JSONResponse(status_code=400, content={'success': False, 'error': str(exc)})

    if provider != 'ollama' and not api_key:
        return None, JSONResponse(status_code=400, content={
            'success': False, 'error': 'API anahtarı boş. Anahtarı girin veya önce kaydedin.'
        })

    return {
        'scope': scope, 'provider': provider, 'base_url': resolved,
        'api_key': api_key, 'model': model,
        'thinking': str(_config.get('llm_thinking' if scope == 'primary' else 'vision_thinking', 'false') or 'false').lower() == 'true',
    }, None


async def _run_llm_probe(params: dict, image_url: str | None = None) -> JSONResponse:
    try:
        result = await asyncio.to_thread(
            _chat_completion_probe,
            params['provider'], params['base_url'], params['api_key'], params['model'],
            image_url, params.get('thinking', False),
        )
    except ValueError as exc:
        return JSONResponse(status_code=502, content={
            'success': False, 'error': str(exc), 'data': {'ok': False}
        })
    except Exception as exc:
        return JSONResponse(status_code=502, content={
            'success': False, 'error': 'LLM testi başarısız: ' + str(exc)[:160],
            'data': {'ok': False},
        })
    return JSONResponse(status_code=200, content={'success': True, 'data': result})


@admin_router.post("/llm/test", summary="LLM Cevap Testi")
async def test_llm(request: Request):
    """Formdaki (kaydedilmemiş olabilen) ayarlarla LLM'e ping atar."""
    try:
        body = await request.json()
    except Exception:
        body = None
    params, error = _prepare_llm_test(body)
    if error:
        return error
    return await _run_llm_probe(params)


@admin_router.post("/llm/test-vision", summary="LLM Görsel Testi")
async def test_vision_llm(request: Request):
    """Formdaki ayarlarla LLM'e sentetik bir görsel gönderip vision desteğini sınar.

    Ana model (primary) için de kullanılabilir; `llm_vision_supported` ayarını
    doğrulamak amacıyla iki kartta da ayrı buton bulunur.
    """
    try:
        body = await request.json()
    except Exception:
        body = None
    params, error = _prepare_llm_test(body)
    if error:
        return error
    return await _run_llm_probe(params, image_url=_test_image_data_url())


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

def _optional_number(value, label: str):
    """Form alanlarından gelen sayıyı normalize eder; boşsa None."""
    if value is None or value == '':
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(label + ' sayı olmalı')


@admin_router.post("/users", summary="Yeni Kullanıcı Oluştur")
async def create_user(request: Request):
    """Admin veya hasta rolünde yeni kullanıcı oluşturur (bcrypt şifre)."""
    try:
        data = await request.json()
    except Exception:
        data = None
    if not isinstance(data, dict):
        data = {}

    try:
        birth_year = _optional_number(data.get('birth_year'), 'Doğum yılı')
        result = auth_service.admin_create_user(
            email=data.get('email', ''),
            password=data.get('password', ''),
            full_name=data.get('full_name', ''),
            role=data.get('role', 'patient'),
            height_cm=_optional_number(data.get('height_cm'), 'Boy'),
            weight_kg=_optional_number(data.get('weight_kg'), 'Kilo'),
            birth_year=int(birth_year) if birth_year is not None else None,
            city=data.get('city'),
            is_active=data.get('is_active', True) is not False,
        )
    except ValueError as exc:
        return JSONResponse(status_code=400, content={
            'success': False, 'error': str(exc)
        })
    except Exception as exc:
        return JSONResponse(status_code=503, content={
            'success': False, 'error': f'Kullanıcı oluşturulamadı: {exc}'
        })

    if not result.get('success'):
        return JSONResponse(status_code=400, content={
            'success': False, 'error': result.get('message', 'Kullanıcı oluşturulamadı')
        })
    return JSONResponse(status_code=201, content={
        'success': True,
        'message': result.get('message'),
        'data': result.get('user'),
    })


@admin_router.patch("/users/{user_id}", summary="Kullanıcıyı Aktifleştir / Pasife Al")
async def update_user_status(user_id: int, request: Request):
    """Kendi hesabı ve son aktif admin korunur."""
    try:
        data = await request.json()
    except Exception:
        data = None
    if not isinstance(data, dict) or not isinstance(data.get('is_active'), bool):
        return JSONResponse(status_code=400, content={
            'success': False, 'error': 'is_active boolean olmalı'
        })

    header = request.headers.get('Authorization', '')
    actor = {}
    if header.startswith('Bearer '):
        actor = auth_service.verify_token(header[7:], role='admin').get('user') or {}

    try:
        result = auth_service.admin_set_active(
            user_id, data['is_active'], actor.get('user_id')
        )
    except Exception as exc:
        return JSONResponse(status_code=503, content={
            'success': False, 'error': f'Kullanıcı durumu güncellenemedi: {exc}'
        })

    if not result.get('success'):
        return JSONResponse(status_code=400, content={
            'success': False, 'error': result.get('message', 'İşlem başarısız')
        })
    return JSONResponse(status_code=200, content={
        'success': True,
        'message': result.get('message'),
        'data': result.get('user'),
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

# --- 5. HEALTH METRICS ENDPOINTS ---

def _get_conn():
    """Yeni bir PostgreSQL bağlantısı açar (config loader'dan okunan ayarlar)."""
    return psycopg2.connect(
        host=_config.get('db_host', 'localhost'),
        port=int(_config.get('db_port', '5432')),
        dbname=_config.get('db_name', 'medical_ai'),
        user=_config.get('db_user', 'medical_user'),
        password=_config.get('db_password', '')
    )


DEFINITION_CATEGORIES = {
    "blood_pressure", "pulse", "weight", "glucose", "temperature", "spo2", "other"
}


def _definition_dict(row):
    return {
        "id": row[0], "metric_key": row[1], "label": row[2], "unit": row[3] or "",
        "category": row[4], "min_value": float(row[5]) if row[5] is not None else None,
        "max_value": float(row[6]) if row[6] is not None else None,
        "is_active": row[7], "created_at": row[8], "updated_at": row[9],
    }


def _definition_error(metric_key, label, category, min_value, max_value):
    if not re.fullmatch(r"[a-z0-9_]{1,50}", metric_key or ""):
        return "Metrik key yalnızca küçük harf, sayı ve alt çizgi içerebilir."
    if not (label or "").strip():
        return "Metrik etiketi zorunludur."
    if category not in DEFINITION_CATEGORIES:
        return "Geçersiz metrik kategorisi."
    if min_value is not None and max_value is not None and min_value > max_value:
        return "Minimum değer maksimum değerden büyük olamaz."
    return None


@health_router.get("/metric-definitions", summary="Metrik Tanımları")
async def list_metric_definitions(include_inactive: bool = False):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT definition_id, metric_key, label, unit, category, min_value, max_value, "
                "is_active, created_at, updated_at FROM health_metric_definitions "
                "WHERE (%s OR is_active = TRUE) ORDER BY category, label",
                (bool(include_inactive),),
            )
            rows = cur.fetchall()
        return JSONResponse(status_code=200, content={
            "success": True, "data": [_definition_dict(row) for row in rows]
        })
    finally:
        conn.close()


@health_router.post("/metric-definitions", summary="Metrik Tanımı Ekle")
async def create_metric_definition(body: HealthMetricDefinitionCreate):
    metric_key = body.metric_key.strip().lower()
    label = body.label.strip()
    error = _definition_error(metric_key, label, body.category, body.min_value, body.max_value)
    if error:
        return JSONResponse(status_code=400, content={"success": False, "error": error})
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO health_metric_definitions "
                "(metric_key, label, unit, category, min_value, max_value, is_active) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s) "
                "RETURNING definition_id, metric_key, label, unit, category, min_value, max_value, "
                "is_active, created_at, updated_at",
                (metric_key, label, body.unit, body.category, body.min_value, body.max_value, body.is_active),
            )
            row = cur.fetchone()
        conn.commit()
        return JSONResponse(status_code=201, content={"success": True, "data": _definition_dict(row)})
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return JSONResponse(status_code=400, content={"success": False, "error": "Bu metrik key zaten mevcut."})
    finally:
        conn.close()


@health_router.patch("/metric-definitions/{definition_id}", summary="Metrik Tanımını Güncelle")
async def update_metric_definition(definition_id: int, body: HealthMetricDefinitionUpdate):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT definition_id, metric_key, label, unit, category, min_value, max_value, "
                "is_active, created_at, updated_at FROM health_metric_definitions WHERE definition_id = %s",
                (definition_id,),
            )
            row = cur.fetchone()
            if not row:
                return JSONResponse(status_code=404, content={"success": False, "error": "Metrik tanımı bulunamadı."})
            current = _definition_dict(row)
            metric_key = (body.metric_key if body.metric_key is not None else current["metric_key"]).strip().lower()
            label = (body.label if body.label is not None else current["label"]).strip()
            category = body.category if body.category is not None else current["category"]
            min_value = body.min_value if "min_value" in body.model_fields_set else current["min_value"]
            max_value = body.max_value if "max_value" in body.model_fields_set else current["max_value"]
            is_active = body.is_active if body.is_active is not None else current["is_active"]
            unit = body.unit if "unit" in body.model_fields_set else current["unit"]
            error = _definition_error(metric_key, label, category, min_value, max_value)
            if error:
                return JSONResponse(status_code=400, content={"success": False, "error": error})
            cur.execute(
                "UPDATE health_metric_definitions SET metric_key=%s, label=%s, unit=%s, category=%s, "
                "min_value=%s, max_value=%s, is_active=%s, updated_at=NOW() WHERE definition_id=%s "
                "RETURNING definition_id, metric_key, label, unit, category, min_value, max_value, "
                "is_active, created_at, updated_at",
                (metric_key, label, unit, category, min_value, max_value, is_active, definition_id),
            )
            updated = cur.fetchone()
        conn.commit()
        return JSONResponse(status_code=200, content={"success": True, "data": _definition_dict(updated)})
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        return JSONResponse(status_code=400, content={"success": False, "error": "Bu metrik key zaten mevcut."})
    finally:
        conn.close()


@health_router.delete("/metric-definitions/{definition_id}", summary="Metrik Tanımını Sil")
async def delete_metric_definition(definition_id: int):
    conn = _get_conn()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT metric_key FROM health_metric_definitions WHERE definition_id=%s", (definition_id,))
            row = cur.fetchone()
            if not row:
                return JSONResponse(status_code=404, content={"success": False, "error": "Metrik tanımı bulunamadı."})
            cur.execute("SELECT 1 FROM health_metrics WHERE metric_name=%s LIMIT 1", (row[0],))
            if cur.fetchone():
                return JSONResponse(status_code=400, content={
                    "success": False, "error": "Bu metrik kullanıldığı için silinemez; pasife alabilirsiniz."
                })
            cur.execute("DELETE FROM health_metric_definitions WHERE definition_id=%s", (definition_id,))
        conn.commit()
        return JSONResponse(status_code=200, content={"success": True, "message": "Metrik tanımı silindi."})
    finally:
        conn.close()


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


# --- 6. UPLOAD İSTATİSTİKLERİ ---

@admin_router.get("/uploads/stats", summary="Kullanıcı Bazlı Disk Kullanım İstatistikleri")
async def get_upload_stats(request: Request):
    """Dosya depolama istatistiklerini kullanıcı bazında döner.

    Yalnızca toplamlar ve dağılımlar döner; fiziksel dosya yolu/paylaşılmaz.
    """
    conn = None
    cur = None
    try:
        conn = _get_conn()
        cur = conn.cursor()

        cur.execute("""
            SELECT COUNT(*),
                   COALESCE(SUM(size_bytes), 0),
                   COUNT(DISTINCT user_id),
                   COALESCE(AVG(size_bytes), 0)
            FROM user_uploads
        """)
        total_files, total_bytes, users_with_uploads, avg_bytes = cur.fetchone()

        cur.execute("""
            SELECT CASE
                       WHEN mime_type = 'application/pdf' THEN 'pdf'
                       WHEN mime_type LIKE 'image/%' THEN 'image'
                       WHEN mime_type = 'text/plain' THEN 'text'
                       ELSE 'other'
                   END AS file_type,
                   COUNT(*),
                   COALESCE(SUM(size_bytes), 0)
            FROM user_uploads
            GROUP BY file_type
            ORDER BY COUNT(*) DESC
        """)
        by_type = [
            {'type': r[0], 'count': r[1], 'bytes': r[2]}
            for r in cur.fetchall()
        ]

        cur.execute("""
            SELECT user_id,
                   COUNT(*) FILTER (WHERE mime_type = 'application/pdf') AS pdf,
                   COUNT(*) FILTER (WHERE mime_type LIKE 'image/%') AS image,
                   COUNT(*) FILTER (WHERE mime_type = 'text/plain') AS text,
                   COUNT(*) FILTER (WHERE mime_type IS NULL
                                      OR (mime_type <> 'application/pdf'
                                          AND mime_type NOT LIKE 'image/%'
                                          AND mime_type <> 'text/plain')) AS other
            FROM user_uploads
            GROUP BY user_id
        """)
        type_rows = cur.fetchall()

        cur.execute("""
            SELECT u.user_id, u.email, u.full_name,
                   COUNT(up.upload_id) AS file_count,
                   COALESCE(SUM(up.size_bytes), 0) AS total_bytes,
                   MAX(up.upload_date) AS last_upload
            FROM users u
            LEFT JOIN user_uploads up ON up.user_id = u.user_id
            GROUP BY u.user_id, u.email, u.full_name
            HAVING COUNT(up.upload_id) > 0
            ORDER BY total_bytes DESC, file_count DESC
        """)
        by_user = []
        for user_id, email, full_name, file_count, user_bytes, last_upload in cur.fetchall():
            types = next((r for r in type_rows if r[0] == user_id), None)
            by_user.append({
                'user_id': user_id,
                'email': email,
                'full_name': full_name,
                'file_count': file_count,
                'total_bytes': user_bytes,
                'last_upload': last_upload,
                'types': {
                    'pdf': types[1] if types else 0,
                    'image': types[2] if types else 0,
                    'text': types[3] if types else 0,
                    'other': types[4] if types else 0,
                },
            })

        cur.execute("""
            SELECT up.upload_id, u.email, u.full_name, up.original_name,
                   up.size_bytes, up.upload_date
            FROM user_uploads up
            JOIN users u ON u.user_id = up.user_id
            ORDER BY up.upload_date DESC
            LIMIT 10
        """)
        recent = [
            {
                'id': r[0], 'email': r[1], 'full_name': r[2],
                'filename': r[3], 'size': r[4], 'uploaded_at': r[5],
            }
            for r in cur.fetchall()
        ]

        return JSONResponse(status_code=200, content={
            'success': True,
            'data': {
                'summary': {
                    'total_files': total_files,
                    'total_bytes': total_bytes,
                    'users_with_uploads': users_with_uploads,
                    'avg_bytes': avg_bytes,
                },
                'by_type': by_type,
                'by_user': by_user,
                'recent': recent,
            },
        })
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={'success': False, 'error': f'Disk istatistikleri alınamadı: {exc}'},
        )
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


# --- 7. UTILS ENDPOINTS ---

@admin_router.get("/utils/secret/{key}", summary="Secret Key Durumu")
async def get_secret(key: str):
    """
    Secret'ın var olup olmadığını ve maskelenmiş değerini döner.

    Güvenlik kuralı (11): gizli değer hiçbir API yanıtında düz metin dönmez.
    Cache (hot reload) birincil kaynaktır; DB yalnızca fallback'dir.
    """
    value = _config.get(key)
    if value is None:
        conn = None
        try:
            conn = psycopg2.connect(
                host=_config.get('db_host', 'localhost'),
                port=int(_config.get('db_port', '5432')),
                dbname=_config.get('db_name', 'medical_ai'),
                user=_config.get('db_user', 'medical_user'),
                password=_config.get('db_password', ''),
            )
            with conn.cursor() as cur:
                cur.execute("SELECT value FROM system_config WHERE key = %s", (key,))
                row = cur.fetchone()
            if row:
                value = row[0]
                _config.set(key, value)
        except Exception:
            value = None
        finally:
            if conn:
                conn.close()

    if value is None:
        return JSONResponse(status_code=404, content={'success': False, 'error': f'{key} bulunamadı'})

    is_secret = key in SECRET_KEYS
    return JSONResponse(status_code=200, content={
        'success': True,
        'data': {
            'key': key,
            'is_secret': is_secret,
            'has_value': bool(value),
            'value': _mask_secret(str(value)) if is_secret else str(value),
        },
    })


# --- 8. BAĞLANTI TEST ENDPOINT'LERİ ---

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
