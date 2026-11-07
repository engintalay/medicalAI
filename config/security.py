# config/security.py

import jwt
import bcrypt
import os
from typing import Dict, Any, Optional, Callable, Tuple
from functools import wraps
from fastapi import Request
from config.loader import get_config_loader
from config.auth_service import auth_service

class SecurityMiddleware:
    """
    Güvenlik Middleware'ı
    - JWT token doğrulama
    - Password hashleme
    - Admin/Patient rol kontrolü
    """
    
    def __init__(self):
        self._config = get_config_loader()
    
    def verify_jwt(self, token: str, required_role: str = None) -> Tuple[bool, Optional[Dict[str, Any]]]:
        """
        JWT token'ı doğrular.
        
        Args:
            token: JWT token
            required_role: İstenen rol (admin, patient)
        
        Returns:
            (success, user_info)
        """
        result = auth_service.verify_token(token, role=required_role)
        return result['success'], result.get('user')

    def verify_password(self, password: str, password_hash: str) -> bool:
        """
        Parolayı hash ile karşılaştırır.
        
        Args:
            password: Plain text password
            password_hash: Bcrypt hash
        
        Returns:
            Doğrulama sonucu
        """
        return bcrypt.checkpw(password.encode('utf-8'), password_hash.encode('utf-8'))

    def get_secret_key(self) -> str:
        """
        JWT secret key'ini config'den getirir.
        
        Returns:
            Secret key string
        """
        return self._config.get('jwt_secret', 'medical_ai_default_secret_2026')

    def get_jwt_expiry_hours(self) -> int:
        """
        JWT token süresini (saat) getirir.
        
        Returns:
            Süre (saat)
        """
        return 24


# FastAPI middleware
class JWTAuthMiddleware:
    """
    FastAPI için JWT otantiklik middleware'ı
    """
    
    def __init__(self, app):
        self.app = app
    
    async def __call__(self, scope, receive, send):
        request = Request(scope)
        await self.handle_request(request, receive, send)
    
    async def handle_request(self, request: Request, receive, send):
        # Token'ı al (Header'dan)
        auth_header = request.headers.get('Authorization', '')

        if not auth_header.startswith('Bearer '):
            from fastapi.responses import JSONResponse
            await send(
                (401, 'application/json', {},
                 JSONResponse(content={'success': False, 'error': 'Geçersiz Authorization Header'}).body)
            )
            return

        token = auth_header[7:]

        # Admin endpointleri için admin token kontrolü
        if request.url.path.startswith('/admin/api/'):
            secret_key = self._config.get('jwt_secret', 'medical_ai_default_secret_2026')
            try:
                payload = jwt.decode(token, secret_key, algorithms=['HS256'])
                role = payload.get('role', '')
                
                if role != 'admin':
                    from fastapi.responses import JSONResponse
                    await send(
                        (403, 'application/json', {}, 
                         JSONResponse(content={'success': False, 'error': 'Admin token gerekli'}).body)
                    )
                    return
            except jwt.ExpiredSignatureError:
                from fastapi.responses import JSONResponse
                await send(
                    (401, 'application/json', {}, 
                     JSONResponse(content={'success': False, 'error': 'Token süresi dolmuş'}).body)
                )
                return
            except jwt.InvalidTokenError:
                from fastapi.responses import JSONResponse
                await send(
                    (401, 'application/json', {}, 
                     JSONResponse(content={'success': False, 'error': 'Geçersiz token'}).body)
                )
                return
        
        # Token başarılı, devam et
        await receive()
        return


# Decorator-based Auth
def require_jwt(required_role: str = None):
    """
    JWT token gerektiren endpoint decorator'ı.
    
    Args:
        required_role: İstenen rol (admin, patient)
    
    Returns:
        Decorator function
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            request: Request = args[1] if len(args) > 1 else kwargs.get('request')
            if request:
                auth_header = request.headers.get('Authorization', '')
                if auth_header.startswith('Bearer '):
                    token = auth_header[7:]
                    # Token'ı doğrula (basitçe, tam doğrulama auth_service'te)
                    try:
                        secret_key = SecurityMiddleware().get_secret_key()
                        payload = jwt.decode(token, secret_key, algorithms=['HS256'])
                        if required_role:
                            if payload.get('role') != required_role:
                                from fastapi.responses import JSONResponse
                                return JSONResponse(
                                    status_code=403,
                                    content={'success': False, 'error': f'{required_role} rolü gerekli'}
                                )
                    except jwt.ExpiredSignatureError:
                        from fastapi.responses import JSONResponse
                        return JSONResponse(
                            status_code=401,
                            content={'success': False, 'error': 'Token süresi dolmuş'}
                        )
                    except jwt.InvalidTokenError:
                        from fastapi.responses import JSONResponse
                        return JSONResponse(
                            status_code=401,
                            content={'success': False, 'error': 'Geçersiz token'}
                        )
            return await func(*args, **kwargs)
        return wrapper
    return decorator


# FastAPI Response Helper
class JSONResponse:
    """
    Consistent JSON response format.
    """
    
    def __init__(self, status_code: int = 200, content: Any = {}, error: str = None):
        self.status_code = status_code
        self.content = content
        self.error = error
    
    def __call__(self, *args, **kwargs):
        # FastAPI'ye uyumlu response
        body = {
            'success': self.error is None,
            'data': self.content,
            'error': self.error
        }
        from fastapi.responses import JSONResponse
        return JSONResponse(status_code=self.status_code, content=body)

# Singleton instance
security = SecurityMiddleware()
