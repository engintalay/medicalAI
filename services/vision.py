# services/vision.py — 05 parçası: dosyadan metin çıkarma adaptörü
#
# OpenAI uyumlu `chat/completions` üzerinden PDF/görsel -> metin.
# Yeni Python bağımlılığı yok: urllib + asyncio.to_thread kullanılır.
# API anahtarı, model adı ve dosya yolu asla loglara yazılmaz.

import asyncio
import base64
import json
import re
import zlib
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import psycopg2

from config.loader import get_config_loader

_config = get_config_loader()

PROVIDER_DEFAULTS = {
    "openai": "https://api.openai.com/v1",
    "ollama": "http://localhost:11434",
}
SUPPORTED_PROVIDERS = {"openai", "custom", "ollama"}

# Cloudflare Error 1010: Python varsayılan User-Agent engellenir.
HTTP_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}

DEFAULT_PROMPT = (
    "Aşağıdaki tıbbi belge/görseldeki yazılı metni olduğu gibi, "
    "varsa sayfa sayfa çıkar. Tanı koyma veya yorum ekleme. "
    "Okunamayan kısımları belirt. Çıktıyı Markdown başlık, liste ve tabloları kullanarak düzenle. "
    "Görselde olmayan başlık veya yer tutucu uydurma."
)


class VisionError(Exception):
    """Kullanıcıya güvenle gösterilebilecek hata."""

    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _db():
    return psycopg2.connect(
        host=_config.get("db_host", "localhost"),
        port=int(_config.get("db_port", "5432")),
        dbname=_config.get("db_name", "medical_ai"),
        user=_config.get("db_user", "medical_user"),
        password=_config.get("db_password", ""),
    )


def _flag(key: str) -> bool:
    return str(_config.get(key, "false") or "false").strip().lower() == "true"


def _resolve_base_url(provider: str, base_url: str) -> str:
    resolved = (base_url or "").strip().rstrip("/")
    if not resolved:
        resolved = PROVIDER_DEFAULTS.get(provider, "")
    if provider == "custom" and not resolved:
        raise VisionError("OpenAI uyumlu sağlayıcı için API Base URL zorunludur.")
    if not resolved:
        raise VisionError("Görsel okuma için API Base URL belirlenmedi.")

    parsed = urlparse(resolved)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise VisionError("API Base URL geçerli bir http(s) adresi olmalıdır.")
    return resolved


def _load_upload(upload_id: int, user_id: int):
    conn = None
    cur = None
    try:
        conn = _db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT file_path, mime_type, original_name
            FROM user_uploads
            WHERE upload_id = %s AND user_id = %s
            """,
            (upload_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            raise VisionError(f"upload_id {upload_id} bulunamadı.", 404)
        return row
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


def _max_bytes() -> int:
    try:
        return max(1, int(float(_config.get("max_upload_mb", "20")) * 1024 * 1024))
    except (TypeError, ValueError):
        return 20 * 1024 * 1024


def _pdf_streams(data: bytes):
    """PDF stream bloklarını (ASCII85/Flate gerekirse açılmış) üretir."""
    for match in re.finditer(rb"stream\r?\n(.*?)endstream", data, re.S):
        chunk = match.group(1).strip()
        candidates = [chunk]
        if chunk.endswith(b"~>"):
            try:
                candidates.insert(0, base64.a85decode(chunk, adobe=True))
            except ValueError:
                pass
        for candidate in candidates:
            try:
                yield zlib.decompress(candidate)
                break
            except zlib.error:
                if candidate is candidates[-1]:
                    yield candidate


def _unescape_pdf_string(raw: bytes) -> str:
    raw = raw.replace(b"\\n", b"\n").replace(b"\\r", b"\r").replace(b"\\t", b"\t")
    raw = raw.replace(b"\\(", b"(").replace(b"\\)", b")").replace(b"\\\\", b"\\")
    return raw.decode("latin-1", errors="replace")


def _extract_pdf_text(data: bytes):
    """Metin tabanlı PDF'leri standart kütüphane ile okur.

    Tarayan (görsel) PDF'lerde metin bulunamaz; çağıran vision LLM'e düşer.
    """
    chunks = []
    for stream in _pdf_streams(data):
        if b"BT" not in stream and b"Tj" not in stream and b"TJ" not in stream:
            continue
        parts = []
        for literal in re.finditer(rb"\((?:\\.|[^\\()])*\)", stream):
            value = _unescape_pdf_string(literal.group(0)[1:-1])
            if value.strip():
                parts.append(value)
        if parts:
            chunks.append(" ".join(parts))
    text = "\n".join(chunks).strip()
    if len(text) < 20:
        return None
    return {"text": text, "pages": _page_count(data, "application/pdf"),
            "source": "local_pdf", "model_used": False}


def _page_count(data: bytes, mime: str) -> int:
    if mime == "application/pdf":
        # '/Type /Page' sayfa nesnelerini sayar; '/Pages' kökü hariç tutulur.
        return max(1, len(re.findall(rb"/Type\s*/Page(?!s)", data)))
    return 1


def _parse_reply(payload) -> str:
    if not isinstance(payload, dict):
        raise VisionError("LLM beklenmeyen bir yanıt döndürdü.", 502)
    if isinstance(payload.get("error"), dict):
        message = payload["error"].get("message") or "Bilinmeyen API hatası"
        raise VisionError("LLM hatası: " + str(message)[:200], 502)

    choices = payload.get("choices") or []
    if not choices or not isinstance(choices, list):
        raise VisionError("LLM metin döndürmedi.", 502)

    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") or {}
    content = message.get("content")
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict) and part.get("text"):
                parts.append(str(part["text"]))
        content = "\n".join(parts)
    if not content:
        content = first.get("text") or message.get("reasoning_content") or first.get("reasoning_content")
    if not isinstance(content, str) or not content.strip():
        raise VisionError("LLM boş metin döndürdü.", 502)
    return re.sub(r"<think>.*?</think>", "", content, flags=re.S | re.I).strip()


def _sanitize_detail(raw: bytes, api_key: str) -> str:
    detail = raw.decode("utf-8", errors="replace")
    detail = " ".join(detail.split())[:200]
    if api_key:
        detail = detail.replace(api_key, "***")
    return detail


def _call_completions(
    provider: str,
    base_url: str,
    api_key: str,
    model: str,
    data_url: str,
    prompt: str,
    thinking: bool = False,
) -> str:
    endpoint_base = base_url
    if provider == "ollama" and not endpoint_base.endswith("/v1"):
        endpoint_base += "/v1"
    url = endpoint_base + "/chat/completions"

    try:
        max_tokens = int(_config.get("vision_max_tokens", "1024") or 1024)
    except (TypeError, ValueError):
        max_tokens = 1024
    try:
        timeout = float(_config.get("vision_timeout", "180") or 180)
    except (TypeError, ValueError):
        timeout = 180
    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": max(64, min(max_tokens, 8192)),
        "messages": [
            {"role": "system", "content": "Sen bir belge metni çıkarma asistanısın."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": data_url}},
                ],
            },
        ],
    }
    if not thinking:
        if provider in ("custom", "ollama"):
            payload["reasoning_effort"] = "none"
            payload["chat_template_kwargs"] = {"enable_thinking": False}
        elif provider == "openai":
            payload["reasoning_effort"] = "none"
    headers = dict(HTTP_HEADERS)
    headers["Content-Type"] = "application/json"
    if api_key and provider != "ollama":
        headers["Authorization"] = "Bearer " + api_key

    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=max(30, min(timeout, 600))) as response:
            raw = response.read(8 * 1024 * 1024)
    except HTTPError as exc:
        detail = ""
        try:
            detail = _sanitize_detail(exc.read(400), api_key)
        except Exception:
            pass
        message = f"Görsel okuma başarısız (HTTP {exc.code})."
        if detail:
            message += " Sunucu: " + detail
        raise VisionError(message, 502)
    except (URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        raise VisionError("Vision LLM'e ulaşılamadı: " + str(reason)[:160], 502)

    try:
        return _parse_reply(json.loads(raw.decode("utf-8")))
    except (ValueError, UnicodeDecodeError):
        raise VisionError("LLM geçersiz JSON döndürdü.", 502)


def _resolve_config(api_key: str | None):
    """Hangi LLM'in kullanılacağını belirler (ana vision önce gelir)."""
    primary_vision = _flag("llm_vision_supported")
    vision_enabled = _flag("vision_llm_enabled")
    if not primary_vision and not vision_enabled:
        raise VisionError("Görsel okuma için LLM yapılandırılmadı.")

    if primary_vision:
        return {
            "provider": (_config.get("llm_provider", "openai") or "openai"),
            "model": (_config.get("llm_model", "") or ""),
            "api_key": api_key or (_config.get("llm_api_key", "") or ""),
            "base_url": (_config.get("llm_base_url", "") or ""),
            "source": "primary_llm",
            "thinking": _flag("llm_thinking"),
        }
    return {
        "provider": (_config.get("vision_llm_provider", "openai") or "openai"),
        "model": (_config.get("vision_llm_model", "") or ""),
        "api_key": api_key or (_config.get("vision_llm_api_key", "") or ""),
        "base_url": (_config.get("vision_llm_base_url", "") or ""),
        "source": "vision_llm",
        "thinking": _flag("vision_thinking"),
    }


def extract_text_from_data(
    data: bytes,
    mime: str,
    prompt: str | None = None,
    api_key: str | None = None,
) -> dict:
    """Dosya baytlarından metin çıkarır; DB/user_uploads bağımlılığı yoktur."""
    settings = _resolve_config(api_key)
    mime = (mime or "").split(";")[0].strip().lower()
    if mime == "text/plain":
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = data.decode("utf-8", errors="replace")
        return {"text": text.strip(), "pages": 1, "source": "local_text", "model_used": False}

    if mime not in ("application/pdf", "image/jpeg", "image/png", "image/webp"):
        raise VisionError("Bu dosya tipi görsel okuma için desteklenmiyor.")

    if mime == "application/pdf":
        local = _extract_pdf_text(data)
        if local:
            return local

    provider = settings["provider"]
    if provider not in SUPPORTED_PROVIDERS:
        raise VisionError("Desteklenmeyen LLM sağlayıcısı.")
    base_url = _resolve_base_url(provider, settings["base_url"])
    model = str(settings["model"]).strip()
    if not model:
        raise VisionError("Görsel okuma için LLM modeli seçilmedi.")

    key = str(settings["api_key"] or "").strip()
    if provider != "ollama" and not key:
        raise VisionError("LLM API anahtarı boş. Anahtarı girin veya önce kaydedin.")

    data_url = "data:" + mime + ";base64," + base64.b64encode(data).decode("ascii")
    text = _call_completions(
        provider,
        base_url,
        key,
        model,
        data_url,
        prompt or DEFAULT_PROMPT,
        thinking=settings.get("thinking", False),
    )
    return {
        "text": text,
        "pages": _page_count(data, mime),
        "source": settings["source"],
        "model_used": True,
    }


def _extract_sync(upload_id: int, user_id: int, api_key: str | None, prompt: str | None):
    path, mime, _original_name = _load_upload(upload_id, user_id)

    file_path = Path(path)
    try:
        data = file_path.read_bytes()
    except OSError:
        # Dosya yolu hata mesajına yazılmaz.
        raise VisionError("Dosya okunamadı.", 404)

    if len(data) > _max_bytes():
        raise VisionError("Dosya boyutu görsel okuma sınırını aşıyor.")
    return extract_text_from_data(data, mime, prompt=prompt, api_key=api_key)


async def extract_text(
    upload_id: int,
    user_id: int,
    api_key: str | None = None,
    prompt: str | None = None,
) -> dict:
    """JWT'den gelen user_id ile dosyayı doğrular, LLM'den metin çıkarır.

    api_key kaydedilmeden kullanılabilir; boşsa DB'deki ilgili anahtar kullanılır.
    """
    return await asyncio.to_thread(_extract_sync, upload_id, user_id, api_key, prompt)
