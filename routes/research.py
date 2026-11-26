# routes/research.py — 13 parçası: public research kayıtları + admin içerik yönetimi
#
# Kural: keyfi URL'den dış ağa istek YOK. İçerik istek gövdesinde gelir.
# Public kayıtlar RAG'da user_id=NULL ile saklanır.

import asyncio
import json

from fastapi import APIRouter, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse as _FastJSONResponse
from pydantic import BaseModel

from config.auth_service import auth_service
from config.loader import get_config_loader
from services import rag

router = APIRouter()
_config = get_config_loader()

SUGGESTED_SOURCES = {"prospektus", "arastirma", "klinic_kilavuz", "diger"}


class JSONResponse(_FastJSONResponse):
    def render(self, content):
        return super().render(jsonable_encoder(content))


class ResearchRequest(BaseModel):
    source: str
    title: str
    content: str
    url: str | None = None


class ResearchUpdate(BaseModel):
    source: str | None = None
    title: str | None = None
    content: str | None = None
    url: str | None = None


def _admin_check(request: Request) -> JSONResponse | None:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={
            "success": False, "error": "Yetkilendirme token'ı gerekli"
        })
    token = header[7:]
    if auth_service.is_token_revoked(token):
        return JSONResponse(status_code=401, content={
            "success": False, "error": "Token geçersiz kılınmış (çıkış yapılmış)"
        })
    result = auth_service.verify_token(token, role="admin")
    if not result.get("success"):
        return JSONResponse(status_code=401, content={
            "success": False, "error": result.get("message", "Admin token gerekli")
        })
    return None


def _find_existing(conn, body: ResearchRequest):
    with conn.cursor() as cur:
        if body.url:
            cur.execute(
                "SELECT data_id FROM research_data WHERE url = %s ORDER BY data_id LIMIT 1",
                (body.url.strip(),),
            )
            row = cur.fetchone()
            if row:
                return row[0]
        cur.execute(
            "SELECT data_id FROM research_data "
            "WHERE source_name = %s AND title = %s ORDER BY data_id LIMIT 1",
            (body.source.strip(), body.title.strip()),
        )
        row = cur.fetchone()
        return row[0] if row else None


def _save(conn, body: ResearchRequest, data_id: int | None) -> int:
    metadata = {"title": body.title.strip(), "url": body.url or ""}
    if data_id is None:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO research_data
                    (source_name, title, content, url, metadata, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s::jsonb, NOW(), NOW())
                RETURNING data_id
                """,
                (body.source.strip(), body.title.strip(), body.content.strip(),
                 body.url or None, json.dumps(metadata)),
            )
            data_id = cur.fetchone()[0]
    else:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE research_data
                SET source_name = %s, title = %s, content = %s, url = %s,
                    metadata = %s::jsonb, updated_at = NOW()
                WHERE data_id = %s
                """,
                (body.source.strip(), body.title.strip(), body.content.strip(),
                 body.url or None, json.dumps(metadata), data_id),
            )
    source = f"research:{data_id}"
    rag.delete_source(conn, source)
    rag.ingest(
        conn, None, source, body.content,
        chunk_size=800, overlap=100,
        metadata={"title": body.title.strip(), "url": body.url or "", "scope": "public"},
    )
    return data_id


@router.post("/api/research", summary="Public Araştırma Kaydı (admin)")
async def create_research_public(body: ResearchRequest, request: Request):
    error = _admin_check(request)
    if error:
        return error
    return await asyncio.to_thread(_create, body)


@router.get("/admin/api/research", summary="Araştırma Listesi")
async def list_research(limit: int = 50, offset: int = 0):
    conn = None
    try:
        conn = _config.connect_db()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM research_data")
            total = int(cur.fetchone()[0])
            cur.execute(
                "SELECT data_id, source_name, title, content, url, created_at, updated_at "
                "FROM research_data ORDER BY data_id DESC LIMIT %s OFFSET %s",
                (max(1, min(int(limit), 200)), max(0, int(offset))),
            )
            rows = cur.fetchall()
        return JSONResponse(status_code=200, content={"total": total, "data": [
            {
                "id": r[0], "source": r[1], "title": r[2],
                "content": r[3], "url": r[4],
                "created_at": r[5], "updated_at": r[6],
            }
            for r in rows
        ]})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)[:160]})
    finally:
        if conn:
            conn.close()


def _create(body: ResearchRequest) -> JSONResponse:
    if not (body.content or "").strip():
        return JSONResponse(status_code=400, content={"success": False, "error": "İçerik boş olamaz."})
    if not (body.title or "").strip():
        return JSONResponse(status_code=400, content={"success": False, "error": "Başlık boş olamaz."})
    conn = None
    try:
        conn = _config.connect_db()
        existing = _find_existing(conn, body)
        data_id = _save(conn, body, existing)
        conn.commit()
        return JSONResponse(status_code=201, content={
            "success": True, "data": {"id": data_id, "ingested": True}
        })
    except ValueError as exc:
        if conn:
            conn.rollback()
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
    except Exception as exc:
        if conn:
            conn.rollback()
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)[:160]})
    finally:
        if conn:
            conn.close()


@router.post("/admin/api/research", summary="Araştırma Ekle")
async def create_research_admin(body: ResearchRequest):
    return await asyncio.to_thread(_create, body)


def _update_research_sync(data_id: int, body: ResearchUpdate) -> JSONResponse:
    conn = None
    try:
        conn = _config.connect_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT source_name, title, content, url FROM research_data WHERE data_id = %s",
                (data_id,),
            )
            row = cur.fetchone()
        if not row:
            return JSONResponse(status_code=404, content={
                "success": False, "error": "Kayıt bulunamadı."
            })
        merged = ResearchRequest(
            source=body.source or row[0],
            title=body.title or row[1],
            content=body.content or row[2],
            url=body.url if body.url is not None else (row[3] or ""),
        )
        _save(conn, merged, data_id)
        conn.commit()
        return JSONResponse(status_code=200, content={
            "success": True, "data": {"id": data_id, "ingested": True}
        })
    except ValueError as exc:
        if conn:
            conn.rollback()
        return JSONResponse(status_code=400, content={"success": False, "error": str(exc)})
    except Exception as exc:
        if conn:
            conn.rollback()
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)[:160]})
    finally:
        if conn:
            conn.close()


@router.put("/admin/api/research/{data_id}", summary="Araştırma Güncelle")
async def update_research(data_id: int, body: ResearchUpdate):
    return await asyncio.to_thread(_update_research_sync, data_id, body)


@router.delete("/admin/api/research/{data_id}", summary="Araştırma Sil")
async def delete_research(data_id: int):
    conn = None
    try:
        conn = _config.connect_db()
        with conn.cursor() as cur:
            cur.execute("SELECT 1 FROM research_data WHERE data_id = %s", (data_id,))
            if not cur.fetchone():
                return JSONResponse(status_code=404, content={
                    "success": False, "error": "Kayıt bulunamadı."
                })
            rag.delete_source(conn, f"research:{data_id}")
            cur.execute("DELETE FROM research_data WHERE data_id = %s", (data_id,))
        conn.commit()
        return JSONResponse(status_code=200, content={
            "success": True, "message": "Kayıt silindi."
        })
    except Exception as exc:
        if conn:
            conn.rollback()
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)[:160]})
    finally:
        if conn:
            conn.close()
