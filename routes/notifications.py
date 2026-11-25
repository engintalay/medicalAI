# routes/notifications.py — 09 parçası: hatırlatmalar ve bildirim tercihleri
#
# Gerçek bildirim gönderimi YOK; yalnızca kayıt/okuma/silme (scaffold).
# user_id her zaman JWT'den gelir.

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse as _FastJSONResponse
from pydantic import BaseModel

from config.loader import get_config_loader
from routes.auth import require_patient

router = APIRouter()
_config = get_config_loader()

ALLOWED_TYPES = {"medication", "checkup", "lab", "other"}


class JSONResponse(_FastJSONResponse):
    def render(self, content):
        return super().render(jsonable_encoder(content))


class ReminderRequest(BaseModel):
    type: str
    title: str
    due_date: datetime


class PreferencesRequest(BaseModel):
    email_enabled: bool = True
    push_enabled: bool = False
    quiet_hours: str | None = None


@router.post("/api/reminders", summary="Hatırlatma Ekle")
@router.post("/api/notifications", include_in_schema=False)
async def create_reminder(body: ReminderRequest, user: dict = Depends(require_patient)):
    if body.type not in ALLOWED_TYPES:
        return JSONResponse(status_code=400, content={
            "success": False,
            "error": "Geçersiz hatırlatma tipi. medication, checkup, lab veya other kullanın.",
        })
    if not (body.title or "").strip():
        return JSONResponse(status_code=400, content={"success": False, "error": "Başlık boş olamaz."})
    due = body.due_date
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    if due < datetime.now(timezone.utc):
        return JSONResponse(status_code=400, content={
            "success": False, "error": "Geçmiş tarihli hatırlatma oluşturulamaz."
        })

    conn = None
    try:
        conn = _config.connect_db()
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO reminders (user_id, type, title, due_date) "
                "VALUES (%s, %s, %s, %s) RETURNING reminder_id",
                (int(user["user_id"]), body.type, body.title.strip(), due),
            )
            reminder_id = cur.fetchone()[0]
        conn.commit()
        return JSONResponse(status_code=201, content={"success": True, "data": {"id": reminder_id}})
    except Exception as exc:
        if conn:
            conn.rollback()
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)[:160]})
    finally:
        if conn:
            conn.close()


@router.get("/api/reminders", summary="Hatırlatma Listesi")
@router.get("/api/notifications", include_in_schema=False)
async def list_reminders(user: dict = Depends(require_patient)):
    conn = None
    try:
        conn = _config.connect_db()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT reminder_id, type, title, due_date, is_active, created_at "
                "FROM reminders WHERE user_id = %s AND is_active = TRUE "
                "ORDER BY due_date ASC",
                (int(user["user_id"]),),
            )
            rows = cur.fetchall()
        return JSONResponse(status_code=200, content={"success": True, "data": [
            {
                "id": r[0], "type": r[1], "title": r[2],
                "due_date": r[3], "is_active": r[4], "created_at": r[5],
            }
            for r in rows
        ]})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)[:160]})
    finally:
        if conn:
            conn.close()


@router.delete("/api/reminders/{reminder_id}", summary="Hatırlatma Sil (yumuşak)")
@router.delete("/api/notifications/{reminder_id}", include_in_schema=False)
async def delete_reminder(reminder_id: int, user: dict = Depends(require_patient)):
    conn = None
    try:
        conn = _config.connect_db()
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE reminders SET is_active = FALSE "
                "WHERE reminder_id = %s AND user_id = %s AND is_active = TRUE",
                (reminder_id, int(user["user_id"])),
            )
            if cur.rowcount == 0:
                return JSONResponse(status_code=404, content={
                    "success": False, "error": "Hatırlatma bulunamadı."
                })
        conn.commit()
        return JSONResponse(status_code=200, content={
            "success": True, "message": "Hatırlatma silindi."
        })
    except Exception as exc:
        if conn:
            conn.rollback()
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)[:160]})
    finally:
        if conn:
            conn.close()


def _get_preferences(conn, user_id: int) -> dict:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT email_enabled, push_enabled, quiet_hours FROM notification_preferences "
            "WHERE user_id = %s",
            (user_id,),
        )
        row = cur.fetchone()
    if not row:
        return {"email_enabled": True, "push_enabled": False, "quiet_hours": None}
    return {"email_enabled": row[0], "push_enabled": row[1], "quiet_hours": row[2]}


@router.get("/api/user/notification-preferences", summary="Bildirim Tercihleri")
async def get_preferences(user: dict = Depends(require_patient)):
    conn = None
    try:
        conn = _config.connect_db()
        return JSONResponse(status_code=200, content={
            "success": True, "data": _get_preferences(conn, int(user["user_id"]))
        })
    except Exception as exc:
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)[:160]})
    finally:
        if conn:
            conn.close()


@router.put("/api/user/notification-preferences", summary="Bildirim Tercihlerini Kaydet")
async def update_preferences(body: PreferencesRequest, user: dict = Depends(require_patient)):
    user_id = int(user["user_id"])
    conn = None
    try:
        conn = _config.connect_db()
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO notification_preferences
                    (user_id, email_enabled, push_enabled, quiet_hours, updated_at)
                VALUES (%s, %s, %s, %s, NOW())
                ON CONFLICT (user_id) DO UPDATE SET
                    email_enabled = EXCLUDED.email_enabled,
                    push_enabled = EXCLUDED.push_enabled,
                    quiet_hours = EXCLUDED.quiet_hours,
                    updated_at = NOW()
                """,
                (user_id, body.email_enabled, body.push_enabled, body.quiet_hours),
            )
        conn.commit()
        return JSONResponse(status_code=200, content={"success": True, "data": {
            "email_enabled": body.email_enabled,
            "push_enabled": body.push_enabled,
            "quiet_hours": body.quiet_hours,
        }})
    except Exception as exc:
        if conn:
            conn.rollback()
        return JSONResponse(status_code=500, content={"success": False, "error": str(exc)[:160]})
    finally:
        if conn:
            conn.close()
