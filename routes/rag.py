# routes/rag.py — 06 parçası: RAG ingestion API
#
# Alias'lar 01-shared-contracts.md'den: /api/rag/ingest ve /api/rag/add-document.
# user_id her zaman JWT'den alınır; istek gövdesinden kabul edilmez.

import asyncio

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse as _FastJSONResponse
from pydantic import BaseModel

from config.auth_service import auth_service
from config.loader import get_config_loader
from routes.auth import require_patient
from services import rag, vision, web_import

router = APIRouter()
_config = get_config_loader()


class JSONResponse(_FastJSONResponse):
    def render(self, content):
        return super().render(jsonable_encoder(content))


class IngestRequest(BaseModel):
    source: str
    text: str
    chunk_size: int = 800
    overlap: int = 100


class IngestUrlRequest(BaseModel):
    source: str
    text: str


class UrlImportRequest(BaseModel):
    source: str
    url: str


class RagContentUpdate(BaseModel):
    source: str
    content: str


RAG_FILE_PROMPT = (
    "Bu ilaç prospektüsü/belgesindeki metni olduğu gibi çıkar. İlaç adı, etken madde, "
    "kullanma talimatı, doz, uyarılar, yan etkiler ve etkileşimler varsa başlıklarını koru. "
    "Çıktıyı Markdown başlık, liste ve tabloları kullanarak düzenle. Özetleme veya yorum ekleme."
)


def _ingest(body: IngestRequest, user_id: int) -> JSONResponse:
    if not (body.text or "").strip():
        return JSONResponse(status_code=400, content={"success": False, "error": "Metin boş olamaz"})
    conn = None
    try:
        conn = _config.connect_db()
        result = rag.ingest(
            conn, user_id, body.source, body.text,
            chunk_size=body.chunk_size, overlap=body.overlap,
        )
        conn.commit()
        return JSONResponse(status_code=200, content={"success": True, "data": result})
    except ValueError as exc:
        if conn:
            conn.rollback()
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
    except Exception as exc:
        if conn:
            conn.rollback()
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": f"RAG ingestion başarısız: {str(exc)[:160]}"},
        )
    finally:
        if conn:
            conn.close()


def _ingest_text_sync(source: str, text: str, user_id, metadata: dict) -> dict:
    source = (source or "").strip()
    if not source:
        raise ValueError("Kaynak adı boş olamaz")
    if not (text or "").strip():
        raise ValueError("İçerik boş")
    conn = None
    try:
        conn = _config.connect_db()
        result = rag.ingest(
            conn, user_id, source, text,
            chunk_size=800, overlap=100, metadata=metadata,
        )
        conn.commit()
        return result
    except Exception:
        if conn:
            conn.rollback()
        raise
    finally:
        if conn:
            conn.close()


def _upload_and_ingest_sync(source, filename, data, mime, user_id):
    if not (source or "").strip():
        return JSONResponse(status_code=400, content={"success": False, "error": "Kaynak adı gerekli"})
    mime = (mime or "").split(";")[0].strip().lower()
    if mime not in ("application/pdf", "text/plain"):
        return JSONResponse(status_code=400, content={
            "success": False, "error": "RAG'a yalnızca PDF veya TXT yüklenebilir."
        })
    try:
        limit = max(1, int(float(_config.get("max_upload_mb", "20")) * 1024 * 1024))
    except (TypeError, ValueError):
        limit = 20 * 1024 * 1024
    if len(data) > limit:
        return JSONResponse(status_code=413, content={
            "success": False, "error": "Dosya boyutu config sınırını aşıyor."
        })
    try:
        extracted = vision.extract_text_from_data(data, mime, prompt=RAG_FILE_PROMPT)
        result = _ingest_text_sync(
            source, extracted["text"], user_id,
            {"filename": filename or "dosya", "scope": "public" if user_id is None else "user"},
        )
        return JSONResponse(status_code=200, content={"success": True, "data": {
            **result,
            "filename": filename,
            "pages": extracted.get("pages"),
            "source": extracted.get("source"),
            "model_used": extracted.get("model_used"),
            "characters": len(extracted["text"]),
        }})
    except vision.VisionError as exc:
        return JSONResponse(status_code=exc.status_code, content={"success": False, "error": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={
            "success": False, "error": "RAG yükleme başarısız: " + str(exc)[:160]
        })


def _import_url_sync(source, url, user_id):
    try:
        page = web_import.fetch_url_text(url)
        text = f"{page['title']}\nKaynak: {page['url']}\n\n{page['text']}"
        result = _ingest_text_sync(
            source, text, user_id,
            {"url": page["url"], "title": page["title"],
             "scope": "public" if user_id is None else "user"},
        )
        return JSONResponse(status_code=200, content={"success": True, "data": {
            **result, "title": page["title"], "url": page["url"],
            "characters": page["characters"],
        }})
    except web_import.WebImportError as exc:
        return JSONResponse(status_code=exc.status_code, content={"success": False, "error": str(exc)})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={
            "success": False, "error": "URL içeriği RAG'a eklenemedi: " + str(exc)[:160]
        })


def _public_source_detail_sync(source: str):
    conn = None
    try:
        conn = _config.connect_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT doc_id, content, metadata, created_at FROM rag_documents "
                "WHERE source_type = %s AND user_id IS NULL ORDER BY doc_id",
                (source,),
            )
            rows = cur.fetchall()
        if not rows:
            return None
        chunks = []
        for row in rows:
            metadata = row[2] if isinstance(row[2], dict) else {}
            chunks.append({
                "id": row[0], "content": row[1], "metadata": metadata, "created_at": row[3],
            })
        return {
            "source": source,
            "text": "\n\n".join(row[1] for row in rows),
            "chunks": chunks,
            "metadata": chunks[0]["metadata"] if chunks else {},
        }
    finally:
        if conn:
            conn.close()


def _replace_public_source_sync(source: str, content: str, metadata: dict | None = None):
    try:
        result = _ingest_text_sync(
            source, content, None,
            {**(metadata or {}), "scope": "public", "edited": True},
        )
        return JSONResponse(status_code=200, content={"success": True, "data": result})
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
    except Exception as exc:
        return JSONResponse(status_code=500, content={
            "success": False, "error": "Yeniden indexleme başarısız: " + str(exc)[:160]
        })


@router.post("/api/rag/ingest", summary="RAG İçerik Ekle")
@router.post("/api/rag/add-document", include_in_schema=False)
async def rag_ingest(body: IngestRequest, user: dict = Depends(require_patient)):
    """Metni parçalar, yerel modelle embedding üretir ve rag_documents'a yazar."""
    return await asyncio.to_thread(_ingest, body, int(user["user_id"]))


@router.post("/api/rag/ingest-url", summary="RAG URL/Research İçerik Ekle")
async def rag_ingest_url(body: IngestUrlRequest, user: dict = Depends(require_patient)):
    """`ingest` ile aynı akış; research tarafı için sabit chunk ayarları kullanır."""
    return await asyncio.to_thread(
        _ingest,
        IngestRequest(source=body.source, text=body.text, chunk_size=800, overlap=100),
        int(user["user_id"]),
    )


@router.post("/api/rag/upload", summary="RAG'a PDF/TXT Yükle")
async def rag_upload(
    source: str = Form(...),
    file: UploadFile = File(...),
    user: dict = Depends(require_patient),
):
    data = await file.read()
    return await asyncio.to_thread(
        _upload_and_ingest_sync, source, file.filename, data, file.content_type,
        int(user["user_id"]),
    )


@router.post("/api/rag/import-url", summary="RAG'a İlaç URL'si Ekle")
async def rag_import_url(body: UrlImportRequest, user: dict = Depends(require_patient)):
    return await asyncio.to_thread(
        _import_url_sync, body.source, body.url, int(user["user_id"])
    )


@router.get("/api/rag/drug-search", summary="İlaç Ara (prospektus.co)")
async def rag_drug_search(q: str, user: dict = Depends(require_patient)):
    try:
        results = await asyncio.to_thread(web_import.search_drugs, q, 20)
        return JSONResponse(status_code=200, content={"success": True, "data": results})
    except web_import.WebImportError as exc:
        return JSONResponse(status_code=exc.status_code, content={"success": False, "error": str(exc)})


# ---------------------------------------------------------------------------
# Admin RAG yönetimi (10 parçasının ekranı için)
# /admin/api/* admin JWT middleware'i ile korunur; ek rol kontrolü yapılır.
# Admin içerikleri user_id=NULL ile yazılır, böylece tüm hastaların aramasına girer.
# ---------------------------------------------------------------------------

def _admin_from_request(request: Request):
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None, JSONResponse(status_code=401, content={
            "success": False, "error": "Yetkilendirme token'ı gerekli"
        })
    result = auth_service.verify_token(header[7:], role="admin")
    if not result.get("success"):
        return None, JSONResponse(status_code=401, content={
            "success": False, "error": result.get("message", "Geçersiz token")
        })
    return result.get("user") or {}, None


@router.get("/admin/api/rag/documents", summary="Admin RAG Kaynak Listesi")
async def admin_list_rag_documents(request: Request):
    _, error = _admin_from_request(request)
    if error:
        return error
    conn = None
    try:
        conn = _config.connect_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT source_type,
                       COUNT(*) AS chunks,
                       COUNT(*) FILTER (WHERE user_id IS NULL) AS public_chunks,
                       MIN(created_at) AS created_at,
                       MAX(updated_at) AS updated_at
                FROM rag_documents
                WHERE user_id IS NULL
                GROUP BY source_type
                ORDER BY source_type
                """
            )
            rows = cur.fetchall()
        return JSONResponse(status_code=200, content={"success": True, "data": [
            {
                "source": r[0],
                "chunks": int(r[1] or 0),
                "public_chunks": int(r[2] or 0),
                "created_at": r[3],
                "updated_at": r[4],
            }
            for r in rows
        ]})
    except Exception as exc:
        return JSONResponse(status_code=500, content={
            "success": False, "error": str(exc)[:160]
        })
    finally:
        if conn:
            conn.close()


@router.post("/admin/api/rag/ingest", summary="Admin Public RAG İçerik Ekle")
async def admin_rag_ingest(body: IngestRequest, request: Request):
    _, error = _admin_from_request(request)
    if error:
        return error
    # user_id=None -> public kapsam; hasta aramasında bu parçalar da görünür.
    return await asyncio.to_thread(_ingest, body, None)


@router.post("/admin/api/rag/upload", summary="Admin Public RAG PDF/TXT Yükle")
async def admin_rag_upload(
    source: str = Form(...),
    file: UploadFile = File(...),
    request: Request = None,
):
    _, error = _admin_from_request(request)
    if error:
        return error
    data = await file.read()
    return await asyncio.to_thread(
        _upload_and_ingest_sync, source, file.filename, data, file.content_type, None
    )


@router.post("/admin/api/rag/import-url", summary="Admin Public RAG İlaç URL Ekle")
async def admin_rag_import_url(body: UrlImportRequest, request: Request):
    _, error = _admin_from_request(request)
    if error:
        return error
    return await asyncio.to_thread(_import_url_sync, body.source, body.url, None)


@router.get("/admin/api/rag/drug-search", summary="Admin İlaç Ara (prospektus.co)")
async def admin_rag_drug_search(q: str, request: Request):
    _, error = _admin_from_request(request)
    if error:
        return error
    try:
        results = await asyncio.to_thread(web_import.search_drugs, q, 20)
        return JSONResponse(status_code=200, content={"success": True, "data": results})
    except web_import.WebImportError as exc:
        return JSONResponse(status_code=exc.status_code, content={"success": False, "error": str(exc)})


@router.get("/admin/api/rag/document-content", summary="Admin RAG Kaynak İçeriği")
async def admin_rag_document_content(source: str, request: Request):
    _, error = _admin_from_request(request)
    if error:
        return error
    detail = await asyncio.to_thread(_public_source_detail_sync, source)
    if not detail:
        return JSONResponse(status_code=404, content={
            "success": False, "error": "Public RAG kaynağı bulunamadı."
        })
    return JSONResponse(status_code=200, content={"success": True, "data": detail})


@router.put("/admin/api/rag/document-content", summary="Admin RAG İçeriğini Düzenle ve Yeniden Indexle")
async def admin_rag_update_content(body: RagContentUpdate, request: Request):
    _, error = _admin_from_request(request)
    if error:
        return error
    detail = await asyncio.to_thread(_public_source_detail_sync, body.source)
    if not detail:
        return JSONResponse(status_code=404, content={
            "success": False, "error": "Public RAG kaynağı bulunamadı."
        })
    return await asyncio.to_thread(
        _replace_public_source_sync, body.source, body.content, detail.get("metadata")
    )


@router.post("/admin/api/rag/reindex", summary="Admin RAG Kaynağını Yeniden Indexle")
async def admin_rag_reindex(source: str, request: Request):
    _, error = _admin_from_request(request)
    if error:
        return error
    detail = await asyncio.to_thread(_public_source_detail_sync, source)
    if not detail:
        return JSONResponse(status_code=404, content={
            "success": False, "error": "Public RAG kaynağı bulunamadı."
        })
    return await asyncio.to_thread(
        _replace_public_source_sync, source, detail["text"], detail.get("metadata")
    )


@router.delete("/admin/api/rag/documents/{source}", summary="Admin RAG Kaynağını Sil")
async def admin_rag_delete_source(source: str, request: Request):
    _, error = _admin_from_request(request)
    if error:
        return error
    conn = None
    try:
        conn = _config.connect_db()
        deleted = rag.delete_source(conn, source, None)
        conn.commit()
        return JSONResponse(status_code=200, content={
            "success": True, "deleted": deleted
        })
    except Exception as exc:
        if conn:
            conn.rollback()
        return JSONResponse(status_code=500, content={
            "success": False, "error": str(exc)[:160]
        })
    finally:
        if conn:
            conn.close()
