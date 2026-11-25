# routes/rag.py — 06 parçası: RAG ingestion API
#
# Alias'lar 01-shared-contracts.md'den: /api/rag/ingest ve /api/rag/add-document.
# user_id her zaman JWT'den alınır; istek gövdesinden kabul edilmez.

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse as _FastJSONResponse
from pydantic import BaseModel

from config.auth_service import auth_service
from config.loader import get_config_loader
from routes.auth import require_patient
from services import rag

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


@router.post("/api/rag/ingest", summary="RAG İçerik Ekle")
@router.post("/api/rag/add-document", include_in_schema=False)
async def rag_ingest(body: IngestRequest, user: dict = Depends(require_patient)):
    """Metni parçalar, yerel modelle embedding üretir ve rag_documents'a yazar."""
    return _ingest(body, int(user["user_id"]))


@router.post("/api/rag/ingest-url", summary="RAG URL/Research İçerik Ekle")
async def rag_ingest_url(body: IngestUrlRequest, user: dict = Depends(require_patient)):
    """`ingest` ile aynı akış; research tarafı için sabit chunk ayarları kullanır."""
    return _ingest(
        IngestRequest(source=body.source, text=body.text, chunk_size=800, overlap=100),
        int(user["user_id"]),
    )


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
    return _ingest(body, None)


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
