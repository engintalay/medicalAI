# routes/user.py — 08 parçası: hasta dashboard verisi + CSV/PDF export
#
# Tüm sorgular JWT'deki user_id ile filtrelenir; veri yoksa boş liste döner.

import csv
import html
import io
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse as _FastJSONResponse, Response
from pydantic import BaseModel

from config.loader import get_config_loader
from routes.auth import require_patient

router = APIRouter()
_config = get_config_loader()


class JSONResponse(_FastJSONResponse):
    def render(self, content):
        return super().render(jsonable_encoder(content))


class MetricRequest(BaseModel):
    name: str
    value: float
    unit: str | None = None
    recorded_at: datetime | None = None


def _json_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _profile(conn, user_id: int) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT full_name, height_cm, weight_kg, birth_year, city "
            "FROM users WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone() or (None,) * 5
    return {
        "full_name": row[0] or "",
        "height_cm": _json_value(row[1]),
        "weight_kg": _json_value(row[2]),
        "birth_year": row[3],
        "city": row[4] or "",
    }


def _weight_trend(conn, user_id: int) -> list:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT recorded_at, value FROM health_metrics "
            "WHERE user_id = %s AND metric_name ILIKE 'weight%%' "
            "ORDER BY recorded_at ASC LIMIT 30",
            (user_id,),
        )
        rows = cur.fetchall()
    return [
        {"date": _json_value(r[0]), "value": _json_value(r[1])}
        for r in rows
    ]


def _metric_history(conn, user_id: int) -> list:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT metric_id, metric_name, value, unit, recorded_at, created_at FROM health_metrics "
            "WHERE user_id = %s ORDER BY recorded_at DESC LIMIT 200",
            (user_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "id": r[0],
            "name": r[1],
            "value": _json_value(r[2]),
            "unit": r[3] or "",
            "date": _json_value(r[4]),
            "created_at": _json_value(r[5]),
        }
        for r in rows
    ]


def _uploads(conn, user_id: int) -> list:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT original_name, upload_date, size_bytes, extracted_text, extracted_at, extraction_source "
            "FROM user_uploads WHERE user_id = %s ORDER BY upload_date DESC LIMIT 200",
            (user_id,),
        )
        rows = cur.fetchall()
    return [
        {
            "name": r[0], "date": _json_value(r[1]), "size": r[2] or 0,
            "extracted_text": r[3] or "", "extracted_at": _json_value(r[4]),
            "extraction_source": r[5] or "",
        }
        for r in rows
    ]


def _reminders(conn, user_id: int) -> list:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT type, title, due_date FROM reminders "
                "WHERE user_id = %s AND is_active = TRUE ORDER BY due_date ASC",
                (user_id,),
            )
            rows = cur.fetchall()
        return [
            {"type": r[0], "title": r[1], "due_date": _json_value(r[2])}
            for r in rows
        ]
    except Exception:
        # 09 parçası tablosu henüz yoksa dashboard yine de çalışır.
        return []


def _collect(conn, user_id: int) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM user_uploads WHERE user_id = %s", (user_id,))
        upload_count = int(cur.fetchone()[0] or 0)
    return {
        "profile": _profile(conn, user_id),
        "weight_trend": _weight_trend(conn, user_id),
        "upload_count": upload_count,
        "reminders": _reminders(conn, user_id),
        "metrics": _metric_history(conn, user_id),
        "uploads": _uploads(conn, user_id),
    }


@router.get("/api/user/dashboard", summary="Hasta Dashboard Özeti")
async def patient_dashboard(user: dict = Depends(require_patient)):
    conn = None
    try:
        conn = _config.connect_db()
        data = _collect(conn, int(user["user_id"]))
        return JSONResponse(status_code=200, content={"success": True, "data": data})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)[:160]})
    finally:
        if conn:
            conn.close()


def _metric_definition(conn, metric_key: str, active_only: bool = True):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT definition_id, metric_key, label, unit, category, min_value, max_value, "
            "is_active, created_at, updated_at FROM health_metric_definitions "
            "WHERE metric_key = %s AND (%s OR is_active = TRUE)",
            (metric_key, not active_only),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "id": row[0], "metric_key": row[1], "label": row[2], "unit": row[3] or "",
        "category": row[4], "min_value": _json_value(row[5]), "max_value": _json_value(row[6]),
        "is_active": row[7], "created_at": _json_value(row[8]), "updated_at": _json_value(row[9]),
    }


@router.get("/api/user/metric-definitions", summary="Aktif Metrik Tanımları")
async def list_metric_definitions(user: dict = Depends(require_patient)):
    conn = None
    try:
        conn = _config.connect_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT definition_id, metric_key, label, unit, category, min_value, max_value, "
                "is_active, created_at, updated_at FROM health_metric_definitions "
                "WHERE is_active = TRUE ORDER BY category, label"
            )
            rows = cur.fetchall()
        data = []
        for row in rows:
            data.append({
                "id": row[0], "metric_key": row[1], "label": row[2], "unit": row[3] or "",
                "category": row[4], "min_value": _json_value(row[5]), "max_value": _json_value(row[6]),
                "is_active": row[7], "created_at": _json_value(row[8]), "updated_at": _json_value(row[9]),
            })
        return JSONResponse(status_code=200, content={"success": True, "data": data})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)[:160]})
    finally:
        if conn:
            conn.close()


@router.get("/api/user/metrics", summary="Grafik için Filtreli Metrikler")
async def list_metrics(
    name: list[str] | None = Query(None),
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = 1000,
    user: dict = Depends(require_patient),
):
    """Ölçüm tarihi ve metrik adına göre grafik verisini döndürür."""
    if start is not None and start.tzinfo is None:
        start = start.replace(tzinfo=timezone.utc)
    if end is not None and end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    if start is not None and end is not None and start > end:
        return JSONResponse(status_code=400, content={
            "success": False, "error": "Başlangıç tarihi bitiş tarihinden sonra olamaz."
        })
    names = [item.strip() for item in (name or []) if item and item.strip()]
    conditions = ["user_id = %s"]
    params = [int(user["user_id"])]
    if start is not None:
        conditions.append("recorded_at >= %s")
        params.append(start)
    if end is not None:
        conditions.append("recorded_at <= %s")
        params.append(end)
    if names:
        conditions.append("metric_name = ANY(%s)")
        params.append(names)
    params.append(max(1, min(int(limit), 1000)))
    conn = None
    try:
        conn = _config.connect_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT metric_id, metric_name, value, unit, recorded_at "
                "FROM health_metrics WHERE " + " AND ".join(conditions) +
                " ORDER BY recorded_at ASC LIMIT %s",
                tuple(params),
            )
            rows = cur.fetchall()
        return JSONResponse(status_code=200, content={"success": True, "data": [
            {
                "id": r[0], "name": r[1], "value": _json_value(r[2]),
                "unit": r[3] or "", "date": _json_value(r[4]),
            }
            for r in rows
        ]})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)[:160]})
    finally:
        if conn:
            conn.close()


@router.post("/api/user/metrics", summary="Sağlık Metriği Ekle")
async def add_metric(body: MetricRequest, user: dict = Depends(require_patient)):
    if not (body.name or "").strip():
        return JSONResponse(status_code=400, content={"success": False, "error": "Metrik adı boş olamaz."})
    recorded_at = body.recorded_at or datetime.now(timezone.utc)
    if recorded_at.tzinfo is None:
        recorded_at = recorded_at.replace(tzinfo=timezone.utc)
    if recorded_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        return JSONResponse(status_code=400, content={
            "success": False, "error": "Ölçüm tarihi gelecek olamaz."
        })
    conn = None
    try:
        conn = _config.connect_db()
        definition = _metric_definition(conn, body.name.strip())
        unit = body.unit
        if definition:
            unit = unit or definition["unit"] or None
            if definition["min_value"] is not None and body.value < definition["min_value"]:
                return JSONResponse(status_code=400, content={
                    "success": False,
                    "error": f"{definition['label']} için minimum değer {definition['min_value']}."
                })
            if definition["max_value"] is not None and body.value > definition["max_value"]:
                return JSONResponse(status_code=400, content={
                    "success": False,
                    "error": f"{definition['label']} için maksimum değer {definition['max_value']}."
                })
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO health_metrics (user_id, metric_name, value, unit, recorded_at) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING metric_id",
                (int(user["user_id"]), body.name.strip(), body.value, unit, recorded_at),
            )
            metric_id = cur.fetchone()[0]
        conn.commit()
        return JSONResponse(status_code=201, content={"success": True, "data": {"id": metric_id}})
    except Exception as exc:
        if conn:
            conn.rollback()
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)[:160]})
    finally:
        if conn:
            conn.close()


@router.put("/api/user/metrics/{metric_id}", summary="Sağlık Metriği Güncelle")
async def update_metric(
    metric_id: int,
    body: MetricRequest,
    user: dict = Depends(require_patient),
):
    if not (body.name or "").strip():
        return JSONResponse(status_code=400, content={"success": False, "error": "Metrik adı boş olamaz."})
    recorded_at = body.recorded_at
    if recorded_at is not None:
        if recorded_at.tzinfo is None:
            recorded_at = recorded_at.replace(tzinfo=timezone.utc)
        if recorded_at > datetime.now(timezone.utc) + timedelta(minutes=5):
            return JSONResponse(status_code=400, content={
                "success": False, "error": "Ölçüm tarihi gelecek olamaz."
            })
    conn = None
    try:
        conn = _config.connect_db()
        definition = _metric_definition(conn, body.name.strip())
        unit = body.unit
        if definition:
            unit = unit or definition["unit"] or None
            if definition["min_value"] is not None and body.value < definition["min_value"]:
                return JSONResponse(status_code=400, content={
                    "success": False,
                    "error": f"{definition['label']} için minimum değer {definition['min_value']}."
                })
            if definition["max_value"] is not None and body.value > definition["max_value"]:
                return JSONResponse(status_code=400, content={
                    "success": False,
                    "error": f"{definition['label']} için maksimum değer {definition['max_value']}."
                })
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE health_metrics SET metric_name = %s, value = %s, unit = %s, "
                "recorded_at = COALESCE(%s, recorded_at) "
                "WHERE metric_id = %s AND user_id = %s "
                "RETURNING metric_id, metric_name, value, unit, recorded_at",
                (body.name.strip(), body.value, unit, recorded_at,
                 metric_id, int(user["user_id"])),
            )
            row = cur.fetchone()
        if not row:
            conn.rollback()
            return JSONResponse(status_code=404, content={
                "success": False, "error": "Metrik bulunamadı."
            })
        conn.commit()
        return JSONResponse(status_code=200, content={"success": True, "data": {
            "id": row[0], "name": row[1], "value": _json_value(row[2]),
            "unit": row[3] or "", "date": _json_value(row[4]),
        }})
    except Exception as exc:
        if conn:
            conn.rollback()
        return JSONResponse(status_code=500, content={
            "success": False, "error": str(exc)[:160]
        })
    finally:
        if conn:
            conn.close()


@router.delete("/api/user/metrics/{metric_id}", summary="Sağlık Metriği Sil")
async def delete_metric(metric_id: int, user: dict = Depends(require_patient)):
    """Yalnızca JWT'deki hastaya ait metriği siler."""
    conn = None
    try:
        conn = _config.connect_db()
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM health_metrics WHERE metric_id = %s AND user_id = %s "
                "RETURNING metric_id",
                (metric_id, int(user["user_id"])),
            )
            deleted = cur.fetchone()
        if not deleted:
            conn.rollback()
            return JSONResponse(status_code=404, content={
                "success": False, "error": "Metrik bulunamadı."
            })
        conn.commit()
        return JSONResponse(status_code=200, content={
            "success": True, "message": "Metrik silindi.", "data": {"id": deleted[0]}
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


def _pdf_font() -> str:
    """Türkçe karakterleri destekleyen bir font kaydeder; yoksa Helvetica."""
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        candidates = [
            "/usr/share/fonts/adwaita-sans-fonts/AdwaitaSans-Regular.ttf",
            "/usr/share/fonts/google-carlito-fonts/Carlito-Regular.ttf",
            "/usr/share/fonts/dejavu/DejaVuSans.ttf",
        ]
        for path in candidates:
            if Path(path).exists():
                pdfmetrics.registerFont(TTFont("MedicalAiTurkish", path))
                return "MedicalAiTurkish"
    except Exception:
        pass
    return "Helvetica"


def _build_pdf(data: dict) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer

    font = _pdf_font()
    styles = getSampleStyleSheet()
    normal = styles["Normal"]
    normal.fontName = font
    title = styles["Title"]
    title.fontName = font

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, title="Medical AI Raporu")
    story = [Paragraph("Medical AI - Kişisel Sağlık Raporu", title), Spacer(1, 12)]

    profile = data["profile"]
    story.append(Paragraph("<b>Profil</b>", normal))
    story.append(Paragraph(
        f"Ad: {profile['full_name']} · Boy: {profile['height_cm'] or '-'} cm · "
        f"Kilo: {profile['weight_kg'] or '-'} kg · Doğum yılı: {profile['birth_year'] or '-'} · "
        f"Şehir: {profile['city'] or '-'}",
        normal,
    ))
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>Sağlık Metrikleri</b>", normal))
    if data["metrics"]:
        for item in data["metrics"][:60]:
            story.append(Paragraph(
                f"{item['date']} — {item['name']}: {item['value']} {item['unit']}", normal
            ))
    else:
        story.append(Paragraph("Kayıt yok.", normal))
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>Dosyalar</b>", normal))
    if data["uploads"]:
        for item in data["uploads"][:60]:
            story.append(Paragraph(f"{item['date']} — {item['name']} ({item['size']} bayt)", normal))
            extracted = str(item.get("extracted_text") or "").strip()
            if extracted:
                safe = html.escape(extracted[:6000]).replace("\n", "<br/>")
                story.append(Paragraph(
                    f"<b>Analiz metni ({item.get('extracted_at') or 'tarih yok'}):</b><br/>{safe}",
                    normal,
                ))
    else:
        story.append(Paragraph("Kayıt yok.", normal))
    story.append(Spacer(1, 10))

    story.append(Paragraph("<b>Hatırlatmalar</b>", normal))
    if data["reminders"]:
        for item in data["reminders"]:
            story.append(Paragraph(f"{item['due_date']} — {item['title']} ({item['type']})", normal))
    else:
        story.append(Paragraph("Kayıt yok.", normal))
    story.append(Spacer(1, 10))
    story.append(Paragraph("Bu bilgi tanı yerine geçmez; doktorunuza danışın.", normal))
    doc.build(story)
    return buffer.getvalue()


def _build_csv(data: dict) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["Bölüm", "Alan", "Değer"])
    profile = data["profile"]
    for key, label in (
        ("full_name", "Ad Soyad"), ("height_cm", "Boy (cm)"),
        ("weight_kg", "Kilo (kg)"), ("birth_year", "Doğum Yılı"), ("city", "Şehir"),
    ):
        writer.writerow(["Profil", label, profile.get(key) or ""])
    for item in data["metrics"]:
        writer.writerow(["Sağlık Metrikleri", f"{item['name']} ({item['unit']}) {item['date']}", item["value"]])
    for item in data["uploads"]:
        writer.writerow(["Dosyalar", item["date"], item["name"]])
        if str(item.get("extracted_text") or "").strip():
            writer.writerow(["Dosya Analizi", item.get("extracted_at") or "", item["extracted_text"]])
            writer.writerow(["Dosya Analizi Kaynağı", item.get("extraction_source") or "", item["name"]])
    for item in data["reminders"]:
        writer.writerow(["Hatırlatmalar", item["due_date"], f"{item['type']}: {item['title']}"])
    return ("\ufeff" + buffer.getvalue()).encode("utf-8")


@router.get("/api/user/export", summary="Veri Export (CSV/PDF)")
async def export_data(
    format: str = Query("csv"),
    user: dict = Depends(require_patient),
):
    fmt = (format or "").strip().lower()
    if fmt not in ("csv", "pdf"):
        return JSONResponse(status_code=400, content={"success": False, "error": "Desteklenmeyen format."})
    user_id = int(user["user_id"])
    conn = None
    try:
        conn = _config.connect_db()
        data = _collect(conn, user_id)
        if fmt == "csv":
            return Response(
                content=_build_csv(data),
                media_type="text/csv; charset=utf-8",
                headers={"Content-Disposition": f'attachment; filename="medicalai-rapor-{user_id}.csv"'},
            )
        return Response(
            content=_build_pdf(data),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="medicalai-rapor-{user_id}.pdf"'},
        )
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)[:160]})
    finally:
        if conn:
            conn.close()
