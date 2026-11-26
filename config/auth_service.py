# config/auth_service.py

import jwt
import bcrypt
import os
import time
import redis
from datetime import timedelta, datetime
from typing import Dict, Any, Optional
from config.loader import get_config_loader
import psycopg2

class AuthService:
    """
    Admin Authentication Service
    - JWT token oluşturma/doğrulama
    - Password hashleme (bcrypt)
    - Admin kullanıcı yönetimi
    """
    
    def __init__(self):
        self._config = get_config_loader()
        self._redis = None
        self._init_redis()
    
    def _init_redis(self):
        """Redis bağlantısını oluştur (şifre destekli)"""
        try:
            redis_host = self._config.get('redis_host', 'localhost')
            redis_port = self._config.get('redis_port', '6379')
            redis_password = os.getenv('REDIS_PASSWORD') or None
            redis_username = os.getenv('REDIS_USERNAME') or None
            self._redis = redis.Redis(
                host=redis_host,
                port=int(redis_port),
                password=redis_password,
                username=redis_username,
                decode_responses=True,
            )
            self._redis.ping()
            print("✅ Redis Bağlantısı Başarıyla Kuruldu.")
        except Exception as e:
            print(f"⚠️ Redis Bağlantı Hatası: {e}. Redis cache kullanılamayacak.")
            self._redis = None

    def generate_jwt(self, email: str, role: str, exp_hours: int = 24) -> str:
        """
        JWT token oluşturur.
        
        Args:
            email: Kullanıcı email'i
            role: Kullanıcı rolü (admin, patient vb.)
            exp_hours: Token süresi (saat)
        
        Returns:
            JWT token string
        """
        # Secret key config'den al
        secret_key = self._config.get('jwt_secret', 'medical_ai_default_secret_2026')
        
        # Token yükleme
        payload = {
            'sub': email,
            'role': role,
            'iat': datetime.utcnow(),
            'exp': datetime.utcnow() + timedelta(hours=exp_hours)
        }
        
        # JWT oluştur
        token = jwt.encode(payload, secret_key, algorithm='HS256')
        return token

    def create_admin_user(self, email: str, password: str, full_name: str = 'Sistem Yöneticisi') -> Dict[str, Any]:
        """
        İlk admin kullanıcıyı oluşturur.
        
        Args:
            email: Admin email
            password: Admin şifresi
            full_name: Admin adı
        
        Returns:
            Kullanıcı bilgileri
        """
        conn = psycopg2.connect(
            host=self._config.get('db_host', 'localhost'),
            port=int(self._config.get('db_port', '5432')),
            dbname=self._config.get('db_name', 'medical_ai'),
            user=self._config.get('db_user', 'medical_user'),
            password=self._config.get('db_password', '')
        )
        cur = conn.cursor()
        
        # Şifreyi hash'le
        password_hash = self._bcrypt_hash(password)
        
        # Admin user'ı ekle
        cur.execute("""
            INSERT INTO users (email, password_hash, full_name, role, is_active)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (email) DO UPDATE SET
                password_hash = EXCLUDED.password_hash,
                full_name = EXCLUDED.full_name
        """, (email, password_hash, full_name, 'admin', True))
        
        cur.execute("SELECT user_id, email, full_name, role, is_active, created_at, last_login FROM users WHERE email = %s", (email,))
        user = cur.fetchone()
        
        cur.close()
        conn.close()
        
        return {
            'user_id': user[0],
            'email': user[1],
            'full_name': user[2],
            'role': user[3],
            'is_active': user[4],
            'created_at': user[5],
            'last_login': user[6]
        }

    def login(self, email: str, password: str, role: str = 'admin') -> Dict[str, Any]:
        """
        Admin girişi.
        
        Args:
            email: Email
            password: Parola
            role: Rol (admin, patient)
        
        Returns:
            JWT token ve kullanıcı bilgileri
        """
        # DB'de user'ı bul
        conn = psycopg2.connect(
            host=self._config.get('db_host', 'localhost'),
            port=int(self._config.get('db_port', '5432')),
            dbname=self._config.get('db_name', 'medical_ai'),
            user=self._config.get('db_user', 'medical_user'),
            password=self._config.get('db_password', '')
        )
        cur = conn.cursor()
        
        cur.execute("""
            SELECT user_id, email, full_name, role, is_active, created_at, last_login, password_hash
            FROM users 
            WHERE email = %s
        """, (email,))
        
        user = cur.fetchone()
        cur.close()
        conn.close()
        
        # Kullanıcı yoksa veya bcrypt doğrulaması başarısızsa reddet
        if not user or not bcrypt.checkpw(password.encode('utf-8'), user[7].encode('utf-8')):
            return {
                'success': False,
                'message': 'Kullanıcı bulunamadı veya parola hatalı',
                'token': None,
                'user': None
            }

        # Pasif kullanıclar giriş yapamaz
        if not user[4]:
            return {
                'success': False,
                'message': 'Kullanıcı pasif durumda',
                'token': None,
                'user': None
            }

        # Rol kontrolü (admin girişinde patient hesabı kullanılamasın)
        if role and user[3] != role:
            return {
                'success': False,
                'message': f'Bu hesap {role} rolüne sahip değil',
                'token': None,
                'user': None
            }
        
        # JWT token oluştur
        token = self.generate_jwt(user[1], user[3])

        # Redis oturum kaydı (best-effort; Redis yoksa giriş yine çalışır)
        self.store_session(user[0], token, user[3])

        # Son giriş tarihini güncelle
        self._update_last_login(user[0])
        
        return {
            'success': True,
            'message': 'Giriş başarılı',
            'token': token,
            'user': {
                'user_id': user[0],
                'email': user[1],
                'full_name': user[2],
                'role': user[3],
                'is_active': user[4],
                'created_at': user[5],
                'last_login': user[6]
            }
        }

    def _bcrypt_hash(self, password: str) -> str:
        """
        Parolayı bcrypt ile hash'ler.
        
        Args:
            password: Plain text password
        
        Returns:
            Bcrypt hash string
        """
        salt = bcrypt.gensalt()
        hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
        return hashed.decode('utf-8')

    def _update_last_login(self, user_id: int):
        """
        Son giriş tarihini günceller.
        
        Args:
            user_id: Kullanıcı ID
        """
        conn = psycopg2.connect(
            host=self._config.get('db_host', 'localhost'),
            port=int(self._config.get('db_port', '5432')),
            dbname=self._config.get('db_name', 'medical_ai'),
            user=self._config.get('db_user', 'medical_user'),
            password=self._config.get('db_password', '')
        )
        cur = conn.cursor()
        
        cur.execute("""
            UPDATE users 
            SET last_login = NOW()
            WHERE user_id = %s
        """, (user_id,))
        
        conn.commit()
        cur.close()
        conn.close()

    def store_session(self, user_id: int, token: str, role: str) -> bool:
        """Redis'te oturum kaydı tutar (token süresi kadar TTL)."""
        if not self._redis:
            return False
        try:
            secret_key = self._config.get('jwt_secret', 'medical_ai_default_secret_2026')
            payload = jwt.decode(
                token, secret_key, algorithms=['HS256'],
                options={'verify_exp': False}
            )
            ttl = max(1, int(float(payload.get('exp') or 0) - time.time()))
            self._redis.setex(f"session:{token}", ttl, f"{user_id}:{role}")
            return True
        except Exception:
            return False

    def delete_session(self, token: str) -> bool:
        """Oturum kaydını siler (logout)."""
        if not self._redis:
            return False
        try:
            self._redis.delete(f"session:{token}")
            return True
        except Exception:
            return False

    def register_patient(
        self,
        email: str,
        password: str,
        full_name: str,
        height_cm: Optional[float] = None,
        weight_kg: Optional[float] = None,
        birth_year: Optional[int] = None,
        city: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Hasta kaydı oluşturur ve JWT döndürür."""
        email = (email or '').strip().lower()
        full_name = (full_name or '').strip()

        if not email or '@' not in email:
            return {'success': False, 'message': 'Geçerli bir email adresi girin', 'token': None, 'user': None}
        if len(password or '') < 8:
            return {'success': False, 'message': 'Şifre en az 8 karakter olmalı', 'token': None, 'user': None}
        if not full_name:
            return {'success': False, 'message': 'Ad soyad zorunlu', 'token': None, 'user': None}
        if birth_year is not None and not (1900 <= int(birth_year) <= datetime.utcnow().year):
            return {'success': False, 'message': 'Geçersiz doğum yılı', 'token': None, 'user': None}
        if self.get_user_by_email(email):
            return {'success': False, 'message': 'Bu email ile kayıtlı kullanıcı var', 'token': None, 'user': None}

        conn = psycopg2.connect(
            host=self._config.get('db_host', 'localhost'),
            port=int(self._config.get('db_port', '5432')),
            dbname=self._config.get('db_name', 'medical_ai'),
            user=self._config.get('db_user', 'medical_user'),
            password=self._config.get('db_password', '')
        )
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO users
                    (email, password_hash, full_name, role, is_active,
                     height_cm, weight_kg, birth_year, city)
                VALUES (%s, %s, %s, 'patient', TRUE, %s, %s, %s, %s)
                ON CONFLICT (email) DO NOTHING
                RETURNING user_id, email, full_name, role, is_active,
                          created_at, last_login, height_cm, weight_kg, birth_year, city
            """, (
                email, self._bcrypt_hash(password), full_name,
                height_cm, weight_kg, birth_year, city,
            ))
            row = cur.fetchone()
            conn.commit()
            if not row:
                return {'success': False, 'message': 'Bu email ile kayıtlı kullanıcı var', 'token': None, 'user': None}
        except Exception as exc:
            conn.rollback()
            raise exc
        finally:
            cur.close()
            conn.close()

        user = self._shape_user(row)
        token = self.generate_jwt(user['email'], user['role'])
        self.store_session(user['user_id'], token, user['role'])
        return {
            'success': True,
            'message': 'Kayıt oluşturuldu',
            'token': token,
            'user': user,
        }

    def admin_create_user(
        self,
        email: str,
        password: str,
        full_name: str,
        role: str = 'patient',
        height_cm: Optional[float] = None,
        weight_kg: Optional[float] = None,
        birth_year: Optional[int] = None,
        city: Optional[str] = None,
        is_active: bool = True,
    ) -> Dict[str, Any]:
        """Admin tarafından kullanıcı oluşturur (şifre her zaman bcrypt hash'lenir)."""
        email = (email or '').strip().lower()
        full_name = (full_name or '').strip()
        role = (role or 'patient').strip().lower()
        fail = lambda message: {'success': False, 'message': message, 'user': None}

        if role not in ('admin', 'patient'):
            return fail('Rol admin veya patient olmalı')
        if not email or '@' not in email:
            return fail('Geçerli bir email adresi girin')
        if len(password or '') < 8:
            return fail('Şifre en az 8 karakter olmalı')
        if not full_name:
            return fail('Ad soyad zorunlu')
        try:
            if birth_year is not None and not (1900 <= int(birth_year) <= datetime.utcnow().year):
                return fail('Geçersiz doğum yılı')
        except (TypeError, ValueError):
            return fail('Geçersiz doğum yılı')
        if self.get_user_by_email(email):
            return fail('Bu email ile kayıtlı kullanıcı var')

        conn = psycopg2.connect(
            host=self._config.get('db_host', 'localhost'),
            port=int(self._config.get('db_port', '5432')),
            dbname=self._config.get('db_name', 'medical_ai'),
            user=self._config.get('db_user', 'medical_user'),
            password=self._config.get('db_password', '')
        )
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO users
                    (email, password_hash, full_name, role, is_active,
                     height_cm, weight_kg, birth_year, city)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (email) DO NOTHING
                RETURNING user_id, email, full_name, role, is_active,
                          created_at, last_login, height_cm, weight_kg, birth_year, city
            """, (
                email, self._bcrypt_hash(password), full_name, role, bool(is_active),
                height_cm, weight_kg, birth_year, city,
            ))
            row = cur.fetchone()
            conn.commit()
            if not row:
                return fail('Bu email ile kayıtlı kullanıcı var')
        except Exception as exc:
            conn.rollback()
            raise exc
        finally:
            cur.close()
            conn.close()

        user = self._shape_user(row)
        return {'success': True, 'message': 'Kullanıcı oluşturuldu', 'user': user, 'data': user}

    def admin_set_active(self, user_id: int, is_active: bool, actor_user_id: Optional[int] = None):
        """Kullanıcıyı aktif/pasif yapar; son aktif admin ve kendi hesabı korunur."""
        fail = lambda message: {'success': False, 'message': message, 'user': None}
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return fail('Geçersiz kullanıcı')

        conn = psycopg2.connect(
            host=self._config.get('db_host', 'localhost'),
            port=int(self._config.get('db_port', '5432')),
            dbname=self._config.get('db_name', 'medical_ai'),
            user=self._config.get('db_user', 'medical_user'),
            password=self._config.get('db_password', '')
        )
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT user_id, email, full_name, role, is_active, created_at, last_login, "
                "height_cm, weight_kg, birth_year, city FROM users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return fail('Kullanıcı bulunamadı')
            if not is_active and actor_user_id is not None and user_id == int(actor_user_id):
                return fail('Kendi hesabınızı pasife alamazsınız')
            if not is_active and row[3] == 'admin':
                cur.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND is_active = TRUE"
                )
                if int(cur.fetchone()[0] or 0) <= 1:
                    return fail('Son aktif admin pasife alınamaz')

            cur.execute(
                "UPDATE users SET is_active = %s WHERE user_id = %s "
                "RETURNING user_id, email, full_name, role, is_active, created_at, last_login, "
                "height_cm, weight_kg, birth_year, city",
                (bool(is_active), user_id),
            )
            updated = cur.fetchone()
            conn.commit()
            user = self._shape_user(updated)
            return {'success': True, 'message': 'Kullanıcı durumu güncellendi', 'user': user, 'data': user}
        except Exception as exc:
            conn.rollback()
            raise exc
        finally:
            cur.close()
            conn.close()

    def admin_update_user(
        self,
        user_id: int,
        email: Optional[str] = None,
        full_name: Optional[str] = None,
        role: Optional[str] = None,
        password: Optional[str] = None,
        is_active: Optional[bool] = None,
        actor_user_id: Optional[int] = None,
    ):
        """Admin kullanıcı düzenleme; kendi rolü ve son aktif admin korunur."""
        fail = lambda message: {'success': False, 'message': message, 'user': None}
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            return fail('Geçersiz kullanıcı')

        conn = psycopg2.connect(
            host=self._config.get('db_host', 'localhost'),
            port=int(self._config.get('db_port', '5432')),
            dbname=self._config.get('db_name', 'medical_ai'),
            user=self._config.get('db_user', 'medical_user'),
            password=self._config.get('db_password', '')
        )
        cur = conn.cursor()
        try:
            cur.execute(
                "SELECT user_id, email, full_name, role, is_active, created_at, last_login, "
                "height_cm, weight_kg, birth_year, city FROM users WHERE user_id = %s",
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return fail('Kullanıcı bulunamadı')
            current = self._shape_user(row)

            new_email = (email if email is not None else current['email']).strip().lower()
            new_name = (full_name if full_name is not None else current['full_name']).strip()
            new_role = (role if role is not None else current['role']).strip().lower()
            new_active = current['is_active'] if is_active is None else bool(is_active)
            if not new_email or '@' not in new_email:
                return fail('Geçerli bir email adresi girin')
            if not new_name:
                return fail('Ad soyad zorunlu')
            if new_role not in ('admin', 'patient'):
                return fail('Rol admin veya patient olmalı')
            if password and len(password) < 8:
                return fail('Şifre en az 8 karakter olmalı')
            if actor_user_id is not None and user_id == int(actor_user_id):
                if new_role != 'admin':
                    return fail('Kendi admin rolünüzü kaldıramazsınız')
                if not new_active:
                    return fail('Kendi hesabınızı pasife alamazsınız')
            if current['role'] == 'admin' and current['is_active'] and (new_role != 'admin' or not new_active):
                cur.execute("SELECT COUNT(*) FROM users WHERE role='admin' AND is_active=TRUE")
                if int(cur.fetchone()[0] or 0) <= 1:
                    return fail('Son aktif adminun rolü veya aktifliği değiştirilemez')

            cur.execute("SELECT 1 FROM users WHERE lower(email)=%s AND user_id<>%s", (new_email, user_id))
            if cur.fetchone():
                return fail('Bu email ile kayıtlı kullanıcı var')

            sets = ["email=%s", "full_name=%s", "role=%s", "is_active=%s"]
            values = [new_email, new_name, new_role, new_active]
            if password:
                sets.append("password_hash=%s")
                values.append(self._bcrypt_hash(password))
            values.append(user_id)
            cur.execute(
                "UPDATE users SET " + ", ".join(sets) + " WHERE user_id=%s "
                "RETURNING user_id, email, full_name, role, is_active, created_at, last_login, "
                "height_cm, weight_kg, birth_year, city",
                tuple(values),
            )
            updated = cur.fetchone()
            conn.commit()
            user = self._shape_user(updated)
            return {'success': True, 'message': 'Kullanıcı güncellendi', 'user': user, 'data': user}
        except Exception as exc:
            conn.rollback()
            raise exc
        finally:
            cur.close()
            conn.close()

    def _shape_user(self, row) -> Dict[str, Any]:
        """users satırını API yanıtına çevirir (şifre hash'i dahil edilmez)."""
        if len(row) >= 11:
            profile = {
                'height_cm': float(row[7]) if row[7] is not None else None,
                'weight_kg': float(row[8]) if row[8] is not None else None,
                'birth_year': row[9],
                'city': row[10],
            }
        else:
            profile = {}
        base = {
            'user_id': row[0],
            'id': row[0],
            'email': row[1],
            'full_name': row[2],
            'role': row[3],
            'is_active': row[4],
            'created_at': row[5],
            'last_login': row[6],
        }
        base.update(profile)
        return base

    def get_profile(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Hasta profilini (boy/kilo/demografi) döndürür."""
        conn = psycopg2.connect(
            host=self._config.get('db_host', 'localhost'),
            port=int(self._config.get('db_port', '5432')),
            dbname=self._config.get('db_name', 'medical_ai'),
            user=self._config.get('db_user', 'medical_user'),
            password=self._config.get('db_password', '')
        )
        cur = conn.cursor()
        try:
            cur.execute("""
                SELECT user_id, email, full_name, role, is_active,
                       created_at, last_login, height_cm, weight_kg, birth_year, city
                FROM users WHERE user_id = %s
            """, (user_id,))
            row = cur.fetchone()
        finally:
            cur.close()
            conn.close()
        return self._shape_user(row) if row else None

    def update_profile(self, user_id: int, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Profil alanlarını güvenli biçimde günceller (beyaz liste)."""
        allowed = {
            'full_name': 'full_name',
            'height_cm': 'height_cm',
            'weight_kg': 'weight_kg',
            'birth_year': 'birth_year',
            'city': 'city',
        }
        sets, values = [], []
        for key, column in allowed.items():
            if key in updates and updates[key] is not None:
                sets.append(f"{column} = %s")
                values.append(updates[key])
        if not sets:
            return self.get_profile(user_id)

        values.append(user_id)
        conn = psycopg2.connect(
            host=self._config.get('db_host', 'localhost'),
            port=int(self._config.get('db_port', '5432')),
            dbname=self._config.get('db_name', 'medical_ai'),
            user=self._config.get('db_user', 'medical_user'),
            password=self._config.get('db_password', '')
        )
        cur = conn.cursor()
        try:
            cur.execute(
                "UPDATE users SET " + ", ".join(sets) + " WHERE user_id = %s",
                values,
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()
            raise exc
        finally:
            cur.close()
            conn.close()
        return self.get_profile(user_id)

    def revoke_token(self, token: str) -> bool:
        """JWT'yi Redis kara listesine ekler (logout sonrası geçersiz kılar)."""
        if not self._redis:
            return False
        try:
            secret_key = self._config.get('jwt_secret', 'medical_ai_default_secret_2026')
            payload = jwt.decode(
                token, secret_key, algorithms=['HS256'],
                options={'verify_exp': False}
            )
            expires_at = float(payload.get('exp') or 0)
            ttl = max(1, int(expires_at - time.time()))
            self._redis.setex(f"token_blacklist:{token}", ttl, "1")
            self._redis.delete(f"session:{token}")
            return True
        except Exception:
            return False

    def is_token_revoked(self, token: str) -> bool:
        """Token logout ile iptal edilmiş mi?"""
        if not self._redis:
            return False
        try:
            return bool(self._redis.exists(f"token_blacklist:{token}"))
        except Exception:
            return False

    def verify_token(self, token: str, role: str = 'admin') -> Dict[str, Any]:
        """
        JWT token doğrulama.
        
        Args:
            token: JWT token
            role: Beklenen rol (admin, patient)
        
        Returns:
            Doğrulama sonucu ve kullanıcı bilgileri
        """
        secret_key = self._config.get('jwt_secret', 'medical_ai_default_secret_2026')
        
        try:
            payload = jwt.decode(token, secret_key, algorithms=['HS256'])
            user_email = payload['sub']
            user_role = payload['role']
            
            # Rol kontrolü
            if role and user_role != role:
                return {
                    'success': False,
                    'message': f'Rol eşleşmesi hatası: beklenen={role}, token={user_role}',
                    'user': None
                }
            
            # Kullanıcı bilgilerini çek
            conn = psycopg2.connect(
                host=self._config.get('db_host', 'localhost'),
                port=int(self._config.get('db_port', '5432')),
                dbname=self._config.get('db_name', 'medical_ai'),
                user=self._config.get('db_user', 'medical_user'),
                password=self._config.get('db_password', '')
            )
            cur = conn.cursor()
            
            cur.execute("""
                SELECT user_id, email, full_name, role, is_active, created_at, last_login
                FROM users 
                WHERE email = %s
            """, (user_email,))
            
            user = cur.fetchone()
            cur.close()
            conn.close()
            
            if not user:
                return {
                    'success': False,
                    'message': 'Kullanıcı bulunamadı',
                    'user': None
                }
            
            return {
                'success': True,
                'message': 'Token doğrulandı',
                'user': {
                    'user_id': user[0],
                    'email': user[1],
                    'full_name': user[2],
                    'role': user[3],
                    'is_active': user[4],
                    'created_at': user[5],
                    'last_login': user[6]
                }
            }
            
        except jwt.ExpiredSignatureError:
            return {
                'success': False,
                'message': 'Token süresi dolmuş',
                'user': None
            }
        except jwt.InvalidTokenError as e:
            return {
                'success': False,
                'message': f'Geçersiz token: {str(e)}',
                'user': None
            }

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        """
        Kullanıcı ID'ye göre kullanıcı bilgilerini getirir.
        
        Args:
            user_id: Kullanıcı ID
        
        Returns:
            Kullanıcı bilgileri
        """
        conn = psycopg2.connect(
            host=self._config.get('db_host', 'localhost'),
            port=int(self._config.get('db_port', '5432')),
            dbname=self._config.get('db_name', 'medical_ai'),
            user=self._config.get('db_user', 'medical_user'),
            password=self._config.get('db_password', '')
        )
        cur = conn.cursor()
        
        cur.execute("""
            SELECT user_id, email, full_name, role, is_active, created_at, last_login
            FROM users 
            WHERE user_id = %s
        """, (user_id,))
        
        user = cur.fetchone()
        cur.close()
        conn.close()
        
        if not user:
            return None
        
        return {
            'user_id': user[0],
            'email': user[1],
            'full_name': user[2],
            'role': user[3],
            'is_active': user[4],
            'created_at': user[5],
            'last_login': user[6]
        }

    def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """
        Email'e göre kullanıcı bilgilerini getirir.
        
        Args:
            email: Kullanıcı email
        
        Returns:
            Kullanıcı bilgileri
        """
        conn = psycopg2.connect(
            host=self._config.get('db_host', 'localhost'),
            port=int(self._config.get('db_port', '5432')),
            dbname=self._config.get('db_name', 'medical_ai'),
            user=self._config.get('db_user', 'medical_user'),
            password=self._config.get('db_password', '')
        )
        cur = conn.cursor()
        
        cur.execute("""
            SELECT user_id, email, full_name, role, is_active, created_at, last_login
            FROM users 
            WHERE email = %s
        """, (email,))
        
        user = cur.fetchone()
        cur.close()
        conn.close()
        
        if not user:
            return None
        
        return {
            'user_id': user[0],
            'email': user[1],
            'full_name': user[2],
            'role': user[3],
            'is_active': user[4],
            'created_at': user[5],
            'last_login': user[6]
        }

# Singleton instance
auth_service = AuthService()


# Test amaçlı kullanım
if __name__ == "__main__":
    print("=== AuthService Testi Başlatılıyor ===\n")
    
    # Test 1: Admin kullanıcı oluştur
    print("Test 1: Admin kullanıcı oluşturuluyor...")
    admin = auth_service.create_admin_user(
        email='admin@medicalai.com',
        password='changeme123',
        full_name='Sistem Yöneticisi'
    )
    print(f"✅ Admin oluşturuldu: {admin['email']}")
    
    # Test 2: Login yap
    print("\nTest 2: Giriş yapılıyor...")
    result = auth_service.login('admin@medicalai.com', 'changeme123', role='admin')
    if result['success']:
        print(f"✅ Giriş başarılı! Token: {result['token'][:50]}...")
    else:
        print(f"❌ Giriş hatası: {result['message']}")
    
    # Test 3: Token doğrulama
    print("\nTest 3: Token doğrulanıyor...")
    token_result = auth_service.verify_token(result['token'], role='admin')
    if token_result['success']:
        print(f"✅ Token doğrulandı! Kullanıcı: {token_result['user']['email']}")
    else:
        print(f"❌ Token hatası: {token_result['message']}")
    
    # Test 4: Bcrypt hashleme
    print("\nTest 4: Bcrypt hashleme testi...")
    hash_result = auth_service._bcrypt_hash('testpassword123')
    print(f"✅ Hash: {hash_result[:50]}...")
    
    # Test 5: DB'den kullanıcı çek
    print("\nTest 5: DB'den kullanıcı bilgileri çekiliyor...")
    user = auth_service.get_user_by_email('admin@medicalai.com')
    if user:
        print(f"✅ Kullanıcı bulundu: {user['email']}")
    else:
        print(f"❌ Kullanıcı bulunamadı")
    
    print("\n=== Tüm Testler Tamamlandı ===")
