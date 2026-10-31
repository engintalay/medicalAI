# --- routes/auth.py ---
# Denetçi Eylemi: Basamak 4 (Admin Auth) Kodlama

import os
import secrets
import bcrypt
from typing import Optional
from fastapi import APIRouter, Depends, Request, status, HTTPException, Header
from pydantic import BaseModel
import jwt
import datetime

# --- Import Config Loader (Basamak 3 ile Bağlantı) ---
from config.loader import get_config_loader

# Router ve Model Tanımları
router = APIRouter()

class LoginRequest(BaseModel):
    username: str
    password: str

class RegisterRequest(BaseModel):
    username: str
    password: str
    email: str

class Token(BaseModel):
    access_token: str
    token_type: str
    admin_role: bool

# --- Global Token Ayarları (Config Loader ile) ---
def get_jwt_secret() -> str:
    loader = get_config_loader()
    return loader.get("jwt_secret", "default_secret_key_change_it")

def get_admin_default_password() -> str:
    loader = get_config_loader()
    return loader.get("admin_default_password", "default123")

# --- Admin Auth Service (JWT + Bcrypt) ---
def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))

def create_access_token(data: dict, expires_delta: Optional[datetime.timedelta] = None) -> str:
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.datetime.utcnow() + expire
    else:
        expire = datetime.datetime.utcnow() + datetime.timedelta(hours=24)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, get_jwt_secret(), algorithm="HS256")
    return encoded_jwt

# --- API Endpoints ---

@router.post("/login")
async def login(request: LoginRequest):
    """Admin Login Endpoint (Basamak 4)"""
    # 1. DB'den admin kullanıcı bul
    loader = get_config_loader()
    admin_password = loader.get("admin_default_password")
    
    # 2. Şifre kontrolü
    if verify_password(request.password, admin_password):
        # 3. Token oluştur
        access_token = create_access_token(data={"sub": "admin"})
        return {"access_token": access_token, "token_type": "bearer"}
    
    raise HTTPException(status_code=401, detail="Invalid credentials")

@router.post("/register")
async def register(request: RegisterRequest):
    """Admin Register Endpoint (Basamak 4)"""
    admin_password = loader.get("admin_default_password")
    hashed = hash_password(request.password)
    
    # 4. DB'ye kaydet (system_config tablosu üzerinden)
    loader = get_config_loader()
    loader._cache["admin_username"] = request.username
    loader._cache["admin_email"] = request.email
    
    access_token = create_access_token(data={"sub": "admin"})
    return {"access_token": access_token, "token_type": "bearer"}

# --- Middleware (Auth Check) ---
def get_current_user(request: Request):
    """JWT Token Kontrolü (Middleware)"""
    auth_header = request.headers.get("Authorization")
    if not auth_header:
        raise HTTPException(status_code=401, detail="Authentication needed")
    
    token = auth_header.split(" ")[1]
    try:
        payload = jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

@router.get("/me")
async def get_current_user_info():
    """Admin Info Endpoint (Middleware Testi)"""
    current_user = get_current_user(request)
    return {"username": current_user.get("sub"), "role": "admin"}
