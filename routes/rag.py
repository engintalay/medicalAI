# routes/rag.py — 06 parçası: RAG ingestion API
#
# Alias'lar 01-shared-contracts.md'den: /api/rag/ingest ve /api/rag/add-document.
# user_id her zaman JWT'den alınır; istek gövdesinden kabul edilmez.

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse as _FastJSONResponse
from pydantic import BaseModel

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
