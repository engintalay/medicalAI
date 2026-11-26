# routes/chat.py — 07 parçası: RAG retrieval + /api/chat + çok turlu sohbet
#
# Retrieval (services.rag.search) ve generation (_call_llm) ayrı fonksiyonlardır.
# Tıbbi guardrail her cevaba eklenir; tanı verilmez.

import asyncio
import json
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse as _FastJSONResponse
from pydantic import BaseModel

from config.loader import get_config_loader
from routes.auth import require_patient
from services import rag, vision
from services.measurements import extract_measurement_date, extract_measurements

router = APIRouter()
_config = get_config_loader()

GUARDRAIL = "Bu bilgi tanı yerine geçmez; doktorunuza danışın."
SYSTEM_PROMPT = (
    "Sen bir sağlık bilgilendirme asistanısın. Tanı koyma, ilaç önerme veya "
    "kesin tıbbi sonuç bildirme. Yalnızca RAG kayıtlarında yer alan bilgilere "
    "dayanarak açıklama yap. Kayıtlarda olmayan bir bilgiyi uydurma; "
    "belirsizlikte doktora danışılmasını öner."
)
PROVIDER_DEFAULTS = {
    "openai": "https://api.openai.com/v1",
    "ollama": "http://localhost:11434",
}
HTTP_HEADERS = {
    "Accept": "application/json",
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
}


class JSONResponse(_FastJSONResponse):
    def render(self, content):
        return super().render(jsonable_encoder(content))


class ChatRequest(BaseModel):
    message: str = ""
    conversation_id: int | None = None
    upload_id: int | None = None
    save_metrics: bool = True


def _sanitize(text: str, api_key: str) -> str:
    text = " ".join((text or "").split())[:200]
    if api_key:
        text = text.replace(api_key, "***")
    return text


def _llm_settings() -> dict:
    provider = str(_config.get("llm_provider", "openai") or "openai").strip().lower()
    model = str(_config.get("llm_model", "") or "").strip()
    api_key = str(_config.get("llm_api_key", "") or "").strip()
    base_url = str(_config.get("llm_base_url", "") or "").strip().rstrip("/")
    if not model or (provider != "ollama" and not api_key):
        raise ValueError("LLM yapılandırılmadı.")
    if not base_url:
        base_url = PROVIDER_DEFAULTS.get(provider, "")
    if not base_url:
        raise ValueError("LLM yapılandırılmadı.")
    parsed = urlparse(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("LLM yapılandırılmadı.")
    if parsed.username or parsed.password:
        raise ValueError("LLM yapılandırılmadı.")
    try:
        max_tokens = int(_config.get("llm_max_tokens", "256") or 256)
    except (TypeError, ValueError):
        max_tokens = 256
    try:
        timeout = float(_config.get("llm_timeout", "180") or 180)
    except (TypeError, ValueError):
        timeout = 180
    return {
        "provider": provider, "model": model, "api_key": api_key,
        "base_url": base_url + "/chat/completions",
        "max_tokens": max(16, min(max_tokens, 4096)),
        "timeout": max(15, min(timeout, 600)),
    }


def _call_llm(messages: list, settings: dict) -> str:
    """Ana LLM'e chat/completions isteği atar; cevap metnini döner."""
    headers = dict(HTTP_HEADERS)
    headers["Content-Type"] = "application/json"
    if settings["api_key"] and settings["provider"] != "ollama":
        headers["Authorization"] = "Bearer " + settings["api_key"]
    body = json.dumps({
        "model": settings["model"],
        "temperature": 0.2,
        "max_tokens": settings["max_tokens"],
        "messages": messages,
    }).encode("utf-8")
    request = Request(settings["base_url"], data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=settings["timeout"]) as response:
            raw = response.read(512 * 1024)
    except HTTPError as exc:
        detail = ""
        try:
            detail = _sanitize(exc.read(400).decode("utf-8", errors="replace"), settings["api_key"])
        except Exception:
            pass
        raise ValueError(f"LLM hatası (HTTP {exc.code}). {detail}".strip())
    except (URLError, TimeoutError) as exc:
        reason = getattr(exc, "reason", exc)
        raise ValueError(f"LLM erişilemedi: {_sanitize(str(reason), settings['api_key'])}")

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise ValueError("LLM geçersiz JSON döndürdü.")
    if not isinstance(payload, dict) or isinstance(payload.get("error"), dict):
        error = (payload.get("error") or {}) if isinstance(payload, dict) else {}
        raise ValueError(_sanitize(str(error.get("message") or "LLM hatası"), settings["api_key"]))
    choices = payload.get("choices") or []
    if not choices or not isinstance(choices, list):
        raise ValueError("LLM boş yanıt döndürdü.")
    first = choices[0] if isinstance(choices[0], dict) else {}
    content = (first.get("message") or {}).get("content") or first.get("text") or ""
    if isinstance(content, list):
        content = "\n".join(
            str(part.get("text") or "") if isinstance(part, dict) else str(part)
            for part in content
        )
    answer = str(content).strip()
    if not answer:
        raise ValueError("LLM boş yanıt döndürdü.")
    return answer


def _build_messages(query: str, sources: list, history: list) -> list:
    if sources:
        context = "\n\n".join(
            f"[{idx + 1}] kaynak={item['source']} (skor {item['score']}):\n{item['content']}"
            for idx, item in enumerate(sources)
        )
    else:
        context = "İlgili RAG kaydı bulunamadı."
    # Bazı modellerin (ör. medgemma) Jinja şablonu birden fazla system mesajını
    # ve user/assistant sırasını zorunlu kılar. Tüm sistem bağlamını tek mesaja
    # indirgeyip geçmişi normalleştiriyoruz; aksi halde sunucu 400 döner.
    system_content = SYSTEM_PROMPT + "\n\nRAG KAYITLARI:\n" + context
    history_messages = []
    for row in history:
        role = str(row[0] or '').strip().lower()
        content = str(row[1] or '').strip()
        if role not in ('user', 'assistant') or not content:
            continue
        if history_messages and history_messages[-1]['role'] == role:
            history_messages[-1]['content'] += '\n\n' + content
        else:
            history_messages.append({'role': role, 'content': content})

    # Şablonlar ilk mesajın user olmasını bekler; önce gelen assistant'ı at.
    while history_messages and history_messages[0]['role'] == 'assistant':
        history_messages.pop(0)

    # Sondaki user mesajını yeni soruya ekle (ardışık user olmasın).
    query_text = (query or '').strip()
    if history_messages and history_messages[-1]['role'] == 'user':
        trailing = history_messages.pop()['content']
        query_text = trailing + '\n\n' + query_text

    return [{"role": "system", "content": system_content}] + \
        history_messages + [{"role": "user", "content": query_text}]


def _get_conversation(conn, conversation_id: int, user_id: int):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT conversation_id, title, is_archived, archived_at FROM conversations "
            "WHERE conversation_id = %s AND user_id = %s",
            (conversation_id, user_id),
        )
        return cur.fetchone()


def _history(conn, conversation_id: int, limit: int = 10) -> list:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT role, content FROM ("
            "  SELECT role, content, created_at, message_id FROM conversation_messages "
            "  WHERE conversation_id = %s ORDER BY message_id DESC LIMIT %s"
            ") AS last_messages ORDER BY message_id ASC",
            (conversation_id, limit),
        )
        return cur.fetchall()


def _save_messages(conn, conversation_id: int, query: str, answer: str):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO conversation_messages (conversation_id, role, content) "
            "VALUES (%s, 'user', %s), (%s, 'assistant', %s)",
            (conversation_id, query, conversation_id, answer),
        )


ATTACHMENT_PROMPT = (
    "Bu tıbbi ölçüm görselini/bağı belgesini dikkatle oku. Tansiyon cihazıysa: "
    "en üst köşedeki gg/aa tarihi ölçüm tarihidir; SYS etiketi yanındaki büyük üst sayı "
    "sistolik, DIA yanındaki orta sayı diyastolik, PULSE yanındaki alt sayı nabızdır. "
    "Etiketleri sayılarla birebir eşleştir; sayıları yer değiştirme. Ekranda yıl yoksa "
    "yıl uydurma. Varsa ilaç adı, etken madde, kullanma talimatı, doz, uyarılar, yan "
    "etkiler ve etkileşimler başlıklarını koru. Önce şu satırları ver: "
    "'Tarih: gg/aa', 'Sistolik: ### mmHg', 'Diyastolik: ## mmHg', 'Nabız: ## bpm'. "
    "Ardından kalan metni aktar. Tanı veya öneri ekleme."
)


def _upload_filename(conn, upload_id: int, user_id: int) -> str:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT original_name FROM user_uploads WHERE upload_id = %s AND user_id = %s",
            (upload_id, user_id),
        )
        row = cur.fetchone()
    return row[0] if row else "dosya"


def _save_measurements(conn, user_id: int, text: str) -> list:
    """Çıkarılan ölçümleri aynı transaction içinde health_metrics'a yazar."""
    recorded = []
    measured_at = extract_measurement_date(text) or datetime.now(timezone.utc)
    for item in extract_measurements(text):
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO health_metrics (user_id, metric_name, value, unit, recorded_at) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING metric_id, recorded_at",
                (user_id, item["name"], item["value"], item["unit"], measured_at),
            )
            row = cur.fetchone()
        recorded.append({
            "id": row[0],
            "name": item["name"],
            "value": item["value"],
            "unit": item["unit"],
            "recorded_at": row[1],
        })
    return recorded


@router.post("/api/chat", summary="RAG destekli sağlık sohbeti (dosya destekli)")
async def chat(body: ChatRequest, user: dict = Depends(require_patient)):
    query = (body.message or "").strip()
    upload_id = body.upload_id
    if not query and upload_id is None:
        return JSONResponse(status_code=400, content={"success": False, "error": "Mesaj veya dosya gerekli."})

    try:
        settings = _llm_settings()
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})

    user_id = int(user["user_id"])
    conn = None
    attachment = None
    recorded_metrics = []
    try:
        conn = _config.connect_db()
        conversation_id = body.conversation_id
        if conversation_id is not None:
            conversation = _get_conversation(conn, conversation_id, user_id)
            if not conversation:
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "error": "Konuşma bulunamadı."},
                )
            if conversation[2]:
                return JSONResponse(status_code=400, content={
                    "success": False, "error": "Arşivlenmiş sohbete mesaj eklemek için önce arşivden çıkarın."
                })
            history = _history(conn, conversation_id)
        else:
            history = []

        extracted_text = ""
        if upload_id is not None:
            try:
                result = await vision.extract_text(
                    upload_id, user_id, prompt=ATTACHMENT_PROMPT
                )
            except vision.VisionError as exc:
                if conn:
                    conn.rollback()
                return JSONResponse(
                    status_code=exc.status_code,
                    content={"success": False, "error": str(exc)},
                )
            extracted_text = str(result.get("text") or "").strip()
            filename = _upload_filename(conn, upload_id, user_id)
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE user_uploads SET extracted_text = %s, extracted_at = NOW(), "
                    "extraction_source = %s WHERE upload_id = %s AND user_id = %s",
                    (extracted_text, str(result.get("source") or ""), upload_id, user_id),
                )
            attachment = {
                "upload_id": upload_id,
                "filename": filename,
                "extracted_text": extracted_text,
                "source": result.get("source"),
                "model_used": bool(result.get("model_used")),
            }
            attachment_block = (
                f"[YÜKLENEN DOSYA: {filename}]\n{extracted_text[:12000]}"
            )
            prompt_query = (query + "\n\n" if query else "") + attachment_block
            stored_query = (query + "\n\n" if query else "") + attachment_block
        else:
            prompt_query = query
            stored_query = query

        try:
            top_k = int(_config.get("rag_top_k", "5") or 5)
        except (TypeError, ValueError):
            top_k = 5
        retrieval_query = query or extracted_text[:600]
        sources = await asyncio.to_thread(
            rag.search, conn, user_id, retrieval_query, top_k=top_k, threshold=0.25
        )

        answer = await asyncio.to_thread(
            _call_llm, _build_messages(prompt_query, sources, history), settings
        )
        if GUARDRAIL not in answer:
            answer = answer.rstrip() + "\n\n" + GUARDRAIL

        # LLM başarılıysa mesajları ve doğrulanmış ölçümleri aynı transaction'da kaydet.
        if conversation_id is None:
            title_source = query or (attachment["filename"] if attachment else prompt_query)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO conversations (user_id, title) VALUES (%s, %s) "
                    "RETURNING conversation_id",
                    (user_id, title_source[:60]),
                )
                conversation_id = cur.fetchone()[0]
        if attachment and body.save_metrics:
            recorded_metrics = _save_measurements(conn, user_id, extracted_text)
        _save_messages(conn, conversation_id, stored_query, answer)
        conn.commit()

        return JSONResponse(status_code=200, content={
            "success": True,
            "data": {
                "answer": answer,
                "sources": [
                    {"source": item["source"], "score": item["score"]}
                    for item in sources
                ],
                "conversation_id": conversation_id,
                "attachment": attachment,
                "recorded_metrics": recorded_metrics,
            },
        })
    except vision.VisionError as exc:
        if conn:
            conn.rollback()
        return JSONResponse(status_code=exc.status_code, content={"success": False, "error": str(exc)})
    except ValueError as exc:
        if conn:
            conn.rollback()
        return JSONResponse(status_code=502, content={"success": False, "error": str(exc)})
    except Exception as exc:
        if conn:
            conn.rollback()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"Sohbet başarısız: {_sanitize(str(exc), settings['api_key'])}"},
        )
    finally:
        if conn:
            conn.close()


@router.get("/api/conversations", summary="Konuşma Listesi / Arama")
async def list_conversations(
    q: str = "",
    include_archived: bool = False,
    archived: bool | None = None,
    user: dict = Depends(require_patient),
):
    query = (q or "").strip()
    pattern = "%" + query + "%"
    conn = None
    try:
        conn = _config.connect_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT c.conversation_id, c.title, c.created_at,
                       c.is_archived, c.archived_at
                FROM conversations c
                WHERE c.user_id = %s
                  AND (%s OR c.is_archived = FALSE)
                  AND (%s IS NULL OR c.is_archived = %s)
                  AND (
                    %s = '' OR c.title ILIKE %s OR EXISTS (
                      SELECT 1 FROM conversation_messages m
                      WHERE m.conversation_id = c.conversation_id
                        AND m.content ILIKE %s
                    )
                  )
                ORDER BY c.conversation_id DESC
                LIMIT 200
                """,
                (int(user["user_id"]), bool(include_archived), archived, archived,
                 query, pattern, pattern),
            )
            rows = cur.fetchall()
        return JSONResponse(status_code=200, content={"success": True, "data": [
            {
                "id": r[0], "title": r[1], "created_at": r[2],
                "is_archived": r[3], "archived_at": r[4],
            }
            for r in rows
        ]})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)[:160]})
    finally:
        if conn:
            conn.close()


@router.patch("/api/conversations/{conversation_id}/archive", summary="Sohbeti Arşivle / Geri Yükle")
async def archive_conversation(
    conversation_id: int,
    payload: dict,
    user: dict = Depends(require_patient),
):
    archived = payload.get("archived")
    if not isinstance(archived, bool):
        return JSONResponse(status_code=400, content={
            "success": False, "error": "archived boolean olmalı"
        })
    conn = None
    try:
        conn = _config.connect_db()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE conversations SET is_archived = %s, archived_at = "
                "CASE WHEN %s THEN NOW() ELSE NULL END "
                "WHERE conversation_id = %s AND user_id = %s "
                "RETURNING conversation_id, is_archived, archived_at",
                (archived, archived, conversation_id, int(user["user_id"])),
            )
            row = cur.fetchone()
        if not row:
            conn.rollback()
            return JSONResponse(status_code=404, content={
                "success": False, "error": "Konuşma bulunamadı."
            })
        conn.commit()
        return JSONResponse(status_code=200, content={
            "success": True,
            "data": {"id": row[0], "is_archived": row[1], "archived_at": row[2]},
        })
    except Exception as exc:
        if conn:
            conn.rollback()
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)[:160]})
    finally:
        if conn:
            conn.close()


@router.delete("/api/conversations/{conversation_id}", summary="Sohbeti Sil")
async def delete_conversation(conversation_id: int, user: dict = Depends(require_patient)):
    conn = None
    try:
        conn = _config.connect_db()
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM conversations WHERE conversation_id = %s AND user_id = %s "
                "RETURNING conversation_id",
                (conversation_id, int(user["user_id"])),
            )
            row = cur.fetchone()
        if not row:
            conn.rollback()
            return JSONResponse(status_code=404, content={
                "success": False, "error": "Konuşma bulunamadı."
            })
        conn.commit()
        return JSONResponse(status_code=200, content={
            "success": True, "message": "Sohbet silindi.", "data": {"id": row[0]}
        })
    except Exception as exc:
        if conn:
            conn.rollback()
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)[:160]})
    finally:
        if conn:
            conn.close()


@router.get("/api/conversations/{conversation_id}", summary="Konuşma Detayı")
async def get_conversation(conversation_id: int, user: dict = Depends(require_patient)):
    conn = None
    try:
        conn = _config.connect_db()
        if not _get_conversation(conn, conversation_id, int(user["user_id"])):
            return JSONResponse(status_code=404, content={"success": False, "error": "Konuşma bulunamadı."})
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role, content, created_at FROM conversation_messages "
                "WHERE conversation_id = %s ORDER BY message_id ASC",
                (conversation_id,),
            )
            rows = cur.fetchall()
        return JSONResponse(status_code=200, content={"success": True, "data": {
            "id": conversation_id,
            "messages": [
                {"role": r[0], "content": r[1], "created_at": r[2]} for r in rows
            ],
        }})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)[:160]})
    finally:
        if conn:
            conn.close()
