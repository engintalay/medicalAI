# routes/chat.py — 07 parçası: RAG retrieval + /api/chat + çok turlu sohbet
#
# Retrieval (services.rag.search) ve generation (_call_llm) ayrı fonksiyonlardır.
# Tıbbi guardrail her cevaba eklenir; tanı verilmez.

import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse as _FastJSONResponse
from pydantic import BaseModel

from config.loader import get_config_loader
from routes.auth import require_patient
from services import rag

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
    message: str
    conversation_id: int | None = None


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
    return {
        "provider": provider, "model": model, "api_key": api_key,
        "base_url": base_url + "/chat/completions",
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
        "max_tokens": 512,
        "messages": messages,
    }).encode("utf-8")
    request = Request(settings["base_url"], data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=45) as response:
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
            "SELECT conversation_id, title FROM conversations "
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


@router.post("/api/chat", summary="RAG destekli sağlık sohbeti")
async def chat(body: ChatRequest, user: dict = Depends(require_patient)):
    query = (body.message or "").strip()
    if not query:
        return JSONResponse(status_code=400, content={"success": False, "error": "Mesaj boş olamaz."})

    try:
        settings = _llm_settings()
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})

    user_id = int(user["user_id"])
    conn = None
    try:
        conn = _config.connect_db()
        conversation_id = body.conversation_id
        if conversation_id is not None:
            if not _get_conversation(conn, conversation_id, user_id):
                return JSONResponse(
                    status_code=404,
                    content={"success": False, "error": "Konuşma bulunamadı."},
                )
            history = _history(conn, conversation_id)
        else:
            history = []

        try:
            top_k = int(_config.get("rag_top_k", "5") or 5)
        except (TypeError, ValueError):
            top_k = 5
        sources = rag.search(conn, user_id, query, top_k=top_k, threshold=0.25)

        answer = _call_llm(_build_messages(query, sources, history), settings)
        if GUARDRAIL not in answer:
            answer = answer.rstrip() + "\n\n" + GUARDRAIL

        # LLM başarılıysa mesajları kaydet (önce yazılmaz).
        if conversation_id is None:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO conversations (user_id, title) VALUES (%s, %s) "
                    "RETURNING conversation_id",
                    (user_id, query[:60]),
                )
                conversation_id = cur.fetchone()[0]
        _save_messages(conn, conversation_id, query, answer)
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
            },
        })
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


@router.get("/api/conversations", summary="Konuşma Listesi")
async def list_conversations(user: dict = Depends(require_patient)):
    conn = None
    try:
        conn = _config.connect_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT conversation_id, title, created_at FROM conversations "
                "WHERE user_id = %s ORDER BY conversation_id DESC",
                (int(user["user_id"]),),
            )
            rows = cur.fetchall()
        return JSONResponse(status_code=200, content={"success": True, "data": [
            {"id": r[0], "title": r[1], "created_at": r[2]} for r in rows
        ]})
    except Exception as exc:
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
