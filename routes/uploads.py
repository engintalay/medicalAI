# routes/uploads.py — 04 parçası: hasta dosya depolama
#
# Upload / listeleme / silme. user_id daima JWT'den alınır; istekten alınmaz.

import json
import logging
import os
import re
import time
import uuid
from pathlib import Path

import psycopg2
from fastapi import APIRouter, Body, Depends, File, UploadFile
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, JSONResponse as _FastJSONResponse

from config.loader import get_config_loader
from routes.auth import require_patient
from services.vision import VisionError, extract_text


class JSONResponse(_FastJSONResponse):
    """datetime/Decimal gibi tipleri otomatik JSON'a çeviren JSONResponse."""

    def render(self, content):
        return super().render(jsonable_encoder(content))


router = APIRouter()
_config = get_config_loader()
logger = logging.getLogger("uvicorn.error.medicalai.uploads")


def _debug(event, **fields):
    logger.info("[upload-debug] %s %s", event, json.dumps(fields, ensure_ascii=False, default=str))

ALLOWED_TYPES = {
    "application/pdf": {".pdf"},
    "image/jpeg": {".jpg", ".jpeg"},
    "image/png": {".png"},
    "image/webp": {".webp"},
    "text/plain": {".txt"},
}

UPLOAD_EXTRACT_PROMPT = (
    "Bu tıbbi ölçüm görselini/bağı belgesini dikkatle oku. Tansiyon cihazıysa: "
    "en üst köşedeki gg/aa tarihi ölçüm tarihidir; SYS etiketi yanındaki büyük üst sayı "
    "sistolik, DIA yanındaki orta sayı diyastolik, PULSE yanındaki alt sayı nabızdır. "
    "Etiketleri sayılarla birebir eşleştir; sayıları yer değiştirme. Ekranda yıl yoksa "
    "yıl uydurma. Varsa ilaç adı, etken madde, kullanma talimatı, doz, uyarılar, yan "
    "etkiler ve etkileşimler başlıklarını koru. Önce şu satırları ver: "
    "'Tarih: gg/aa', 'Sistolik: ### mmHg', 'Diyastolik: ## mmHg', 'Nabız: ## bpm'. "
    "Ardından kalan metni Markdown başlık, liste ve tabloları kullanarak düzenle. "
    "İlaç bilgileri görselde yoksa ilaç başlıkları ekleme ve yer tutucu uydurma. "
    "Tanı veya öneri ekleme."
)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _db():
    return psycopg2.connect(
        host=_config.get("db_host", "localhost"),
        port=int(_config.get("db_port", "5432")),
        dbname=_config.get("db_name", "medical_ai"),
        user=_config.get("db_user", "medical_user"),
        password=_config.get("db_password", ""),
    )


def _upload_root() -> Path:
    """Config'deki dizini kullanır; yazılamıyorsa proje içi uploads/'a düşer."""
    configured = str(_config.get("upload_dir", "uploads") or "uploads")
    base = Path(configured)
    if not base.is_absolute():
        base = _PROJECT_ROOT / base
    try:
        base.mkdir(parents=True, exist_ok=True)
        if not os.access(base, os.W_OK):
            raise OSError("dizin yazılabilir değil")
        return base
    except OSError as exc:
        fallback = _PROJECT_ROOT / "uploads"
        fallback.mkdir(parents=True, exist_ok=True)
        print(f"⚠️ upload_dir ({base}) kullanılamadı ({exc}); {fallback} kullanılıyor.")
        return fallback


def _max_bytes() -> int:
    try:
        return max(1, int(float(_config.get("max_upload_mb", "20")) * 1024 * 1024))
    except (TypeError, ValueError):
        return 20 * 1024 * 1024


def _safe_name(filename: str) -> str:
    """Path traversal ve garip karakterleri temizler."""
    name = Path(filename or "dosya").name
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name).lstrip(".")
    return (name or "dosya")[:120]


def _row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "user_id": row[1],
        "filename": row[2],
        "stored_name": row[3],
        "mime_type": row[4],
        "size": row[5],
        "created_at": row[6],
        "extracted_text": row[7] if len(row) > 7 else None,
        "extracted_at": row[8] if len(row) > 8 else None,
        "extraction_source": row[9] if len(row) > 9 else None,
    }


@router.post("/api/uploads", summary="Dosya Yükle")
@router.post("/api/upload", include_in_schema=False)
async def upload_file(
    file: UploadFile = File(...),
    user: dict = Depends(require_patient),
):
    user_id = int(user["user_id"])
    mime = (file.content_type or "").split(";")[0].strip().lower()
    started = time.monotonic()
    _debug("upload_start", user_id=user_id, filename=_safe_name(file.filename), mime=mime)
    if mime not in ALLOWED_TYPES:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Desteklenmeyen dosya tipi. PDF, JPEG, PNG, WebP veya TXT yükleyebilirsiniz."},
        )

    original = _safe_name(file.filename)
    suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED_TYPES[mime]:
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": "Dosya uzantısı içerik tipiyle uyuşmuyor."},
        )

    limit = _max_bytes()
    data = await file.read(limit + 1)
    if len(data) > limit:
        return JSONResponse(
            status_code=413,
            content={"success": False, "error": f"Dosya boyutu {_config.get('max_upload_mb', '20')} MB sınırını aşıyor."},
        )

    stored_name = f"{uuid.uuid4().hex}_{original}"
    user_dir = _upload_root() / str(user_id)
    user_dir.mkdir(parents=True, exist_ok=True)
    path = user_dir / stored_name

    conn = None
    cur = None
    try:
        path.write_bytes(data)
        conn = _db()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO user_uploads
                (user_id, file_path, original_name, stored_name, mime_type, size_bytes)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING upload_id, user_id, original_name, stored_name, mime_type, size_bytes,
                      upload_date, extracted_text, extracted_at, extraction_source
            """,
            (user_id, str(path), original, stored_name, mime, len(data)),
        )
        row = cur.fetchone()
        conn.commit()
    except Exception as exc:
        if conn:
            conn.rollback()
        path.unlink(missing_ok=True)
        return JSONResponse(
            status_code=503,
            content={"success": False, "error": f"Dosya kaydedilemedi: {exc}"},
        )
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    _debug("upload_done", user_id=user_id, upload_id=row[0], bytes=len(data),
           elapsed=round(time.monotonic() - started, 3))
    return JSONResponse(status_code=200, content={"success": True, "data": _row_to_dict(row)})


def _save_extraction(upload_id: int, user_id: int, result: dict):
    conn = None
    cur = None
    try:
        conn = _db()
        cur = conn.cursor()
        cur.execute(
            "UPDATE user_uploads SET extracted_text = %s, extracted_at = NOW(), "
            "extraction_source = %s WHERE upload_id = %s AND user_id = %s",
            (str(result.get("text") or ""), str(result.get("source") or ""), upload_id, user_id),
        )
        conn.commit()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()


@router.post("/api/uploads/{upload_id}/extract", summary="Dosyadan Metin Çıkar")
async def extract_upload_text(
    upload_id: int,
    payload: dict = Body(default=None),
    user: dict = Depends(require_patient),
):
    """Yüklenen PDF/görseli vision LLM ile metne çevirir (05 parçası).

    Body (opsiyonel): {"api_key": "kaydedilmemiş anahtar", "prompt": "..."}
    API anahtarı verilmezse DB'deki ilgili anahtar kullanılır.
    """
    payload = payload or {}
    started = time.monotonic()
    _debug("extract_start", upload_id=upload_id, user_id=int(user["user_id"]))
    api_key = payload.get("api_key")
    prompt = payload.get("prompt")
    if api_key is not None:
        api_key = str(api_key)
    if prompt is not None:
        prompt = str(prompt)[:4000]

    try:
        result = await extract_text(
            upload_id,
            int(user["user_id"]),
            api_key=api_key,
            prompt=prompt or UPLOAD_EXTRACT_PROMPT,
        )
    except VisionError as exc:
        _debug("extract_error", upload_id=upload_id, error=str(exc)[:300],
               elapsed=round(time.monotonic() - started, 3))
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "error": str(exc)},
        )
    _save_extraction(upload_id, int(user["user_id"]), result)
    _debug("extract_done", upload_id=upload_id, source=result.get("source"),
           chars=len(str(result.get("text") or "")), elapsed=round(time.monotonic() - started, 3))
    return JSONResponse(status_code=200, content={"success": True, "data": result})


@router.get("/api/uploads/{upload_id}/file", summary="Dosya Önizleme (güvenli)")
async def get_upload_file(upload_id: int, user: dict = Depends(require_patient)):
    conn = None
    cur = None
    try:
        conn = _db()
        cur = conn.cursor()
        cur.execute(
            "SELECT file_path, original_name, mime_type FROM user_uploads "
            "WHERE upload_id = %s AND user_id = %s",
            (upload_id, int(user["user_id"])),
        )
        row = cur.fetchone()
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()
    if not row:
        return JSONResponse(status_code=404, content={"success": False, "error": "Dosya bulunamadı."})
    path = Path(row[0])
    if not path.is_file():
        return JSONResponse(status_code=404, content={"success": False, "error": "Dosya bulunamadı."})
    return FileResponse(
        path,
        media_type=row[2] or "application/octet-stream",
        filename=row[1] or "dosya",
        content_disposition_type="inline",
    )


@router.get("/api/uploads", summary="Dosyaları Listele")
async def list_uploads(user: dict = Depends(require_patient)):
    user_id = int(user["user_id"])
    conn = None
    cur = None
    try:
        conn = _db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT upload_id, user_id, original_name, stored_name, mime_type, size_bytes,
                   upload_date, extracted_text, extracted_at, extraction_source
            FROM user_uploads
            WHERE user_id = %s
            ORDER BY upload_date DESC
            """,
            (user_id,),
        )
        rows = cur.fetchall()
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"success": False, "error": f"Dosyalar listelenemedi: {exc}"},
        )
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    return JSONResponse(
        status_code=200,
        content={"success": True, "data": [_row_to_dict(r) for r in rows], "total": len(rows)},
    )


@router.delete("/api/uploads/{upload_id}", summary="Dosya Sil")
async def delete_upload(upload_id: int, user: dict = Depends(require_patient)):
    user_id = int(user["user_id"])
    conn = None
    cur = None
    try:
        conn = _db()
        cur = conn.cursor()
        cur.execute(
            "SELECT file_path FROM user_uploads WHERE upload_id = %s AND user_id = %s",
            (upload_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            return JSONResponse(
                status_code=404,
                content={"success": False, "error": f"upload_id {upload_id} bulunamadı"},
            )
        cur.execute(
            "DELETE FROM user_uploads WHERE upload_id = %s AND user_id = %s",
            (upload_id, user_id),
        )
        conn.commit()
    except Exception as exc:
        if conn:
            conn.rollback()
        return JSONResponse(
            status_code=503,
            content={"success": False, "error": f"Dosya silinemedi: {exc}"},
        )
    finally:
        if cur:
            cur.close()
        if conn:
            conn.close()

    try:
        Path(row[0]).unlink(missing_ok=True)
    except OSError as exc:
        print(f"⚠️ fiziksel dosya silinemedi: {exc}")

    return JSONResponse(status_code=200, content={"success": True, "message": "Dosya silindi"})
