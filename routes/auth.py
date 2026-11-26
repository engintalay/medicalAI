# routes/auth.py — Hasta kimlik doğrulama ve profil API'si
#
# 03 parçası: register / login / me / logout + Redis oturum kara listesi.
# Admin auth ayrıdır: /admin/api/auth/login (routes/admin.py).

from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse as _FastJSONResponse
from pydantic import BaseModel

from config.auth_service import auth_service


class JSONResponse(_FastJSONResponse):
    """datetime/Decimal gibi tipleri otomatik JSON'a çeviren JSONResponse."""

    def render(self, content):
        return super().render(jsonable_encoder(content))


router = APIRouter()


class PatientRegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    birth_year: Optional[int] = None
    city: Optional[str] = None


class PatientLoginRequest(BaseModel):
    email: str
    password: str


class ProfileUpdateRequest(BaseModel):
    full_name: Optional[str] = None
    height_cm: Optional[float] = None
    weight_kg: Optional[float] = None
    birth_year: Optional[int] = None
    city: Optional[str] = None


def _token_from_header(request: Request) -> Optional[str]:
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return None
    return header[7:]


def require_patient(request: Request) -> dict:
    """Hasta JWT'sini doğrular; admin token'ı hasta endpoint'lerinde geçmez."""
    token = _token_from_header(request)
    if not token:
        return JSONResponse(
            status_code=401,
            content={"success": False, "error": "Yetkilendirme token'ı gerekli"},
        )
    if auth_service.is_token_revoked(token):
        return JSONResponse(
            status_code=401,
            content={"success": False, "error": "Token geçersiz kılınmış (çıkış yapılmış)"},
        )
    result = auth_service.verify_token(token, role="patient")
    if not result.get("success"):
        return JSONResponse(
            status_code=401,
            content={"success": False, "error": result.get("message", "Geçersiz token")},
        )
    user = result.get("user") or {}
    if not user.get("is_active", True):
        return JSONResponse(
            status_code=401,
            content={"success": False, "error": "Kullanıcı pasif durumda"},
        )
    return user


def _auth_result(result: dict, success_code: int = 200) -> JSONResponse:
    if not result.get("success"):
        return JSONResponse(
            status_code=401,
            content={"success": False, "error": result.get("message", "Giriş başarısız")},
        )
    user = result.get("user") or {}
    return JSONResponse(
        status_code=success_code,
        content={
            "success": True,
            "message": result.get("message", ""),
            "token": result.get("token"),
            "user": user,
            "data": user,
        },
    )


@router.post("/api/auth/register", summary="Hasta Kaydı")
async def patient_register(payload: PatientRegisterRequest):
    try:
        result = auth_service.register_patient(
            email=payload.email,
            password=payload.password,
            full_name=payload.full_name,
            height_cm=payload.height_cm,
            weight_kg=payload.weight_kg,
            birth_year=payload.birth_year,
            city=payload.city,
        )
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"success": False, "error": f"Kayıt oluşturulamadı: {exc}"},
        )
    if not result.get("success"):
        return JSONResponse(
            status_code=400,
            content={"success": False, "error": result.get("message", "Kayıt başarısız")},
        )
    return _auth_result(result, success_code=201)


@router.post("/api/auth/login", summary="Kullanıcı Girişi (hasta/admin)")
async def patient_login(payload: PatientLoginRequest):
    try:
        # Normal giriş her rolü kabul eder; admin hesabı hasta API'lerinde kullanılamaz.
        result = auth_service.login(payload.email, payload.password, role=None)
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"success": False, "error": f"Giriş yapılamadı: {exc}"},
        )
    return _auth_result(result)


@router.post("/api/auth/logout", summary="Hasta Çıkışı")
async def patient_logout(request: Request):
    token = _token_from_header(request)
    if not token:
        return JSONResponse(
            status_code=401,
            content={"success": False, "error": "Token gerekli"},
        )
    revoked = auth_service.revoke_token(token)
    auth_service.delete_session(token)
    return JSONResponse(
        status_code=200,
        content={"success": True, "message": "Çıkış yapıldı", "revoked": revoked},
    )


@router.get("/api/user/me", summary="Hasta Profili")
@router.get("/api/user/profile", include_in_schema=False)
async def get_my_profile(user: dict = Depends(require_patient)):
    profile = auth_service.get_profile(user["user_id"])
    if not profile:
        return JSONResponse(
            status_code=404,
            content={"success": False, "error": "Kullanıcı bulunamadı"},
        )
    return JSONResponse(status_code=200, content={"success": True, "data": profile})


@router.put("/api/user/me", summary="Hasta Profil Güncelle")
@router.put("/api/user/profile", include_in_schema=False)
async def update_my_profile(
    payload: ProfileUpdateRequest,
    user: dict = Depends(require_patient),
):
    try:
        profile = auth_service.update_profile(user["user_id"], payload.model_dump(exclude_unset=True))
    except Exception as exc:
        return JSONResponse(
            status_code=503,
            content={"success": False, "error": f"Profil güncellenemedi: {exc}"},
        )
    return JSONResponse(status_code=200, content={"success": True, "data": profile})
