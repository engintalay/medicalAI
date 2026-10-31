# config/auth_service.py

import jwt
import bcrypt
import os
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
        """Redis bağlantısını oluştur"""
        try:
            redis_host = self._config.get('redis_host', 'localhost')
            redis_port = self._config.get('redis_port', '6379')
            self._redis = redis.Redis(host=redis_host, port=int(redis_port), decode_responses=True)
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
            user=self._config.get('db_user', 'medical_user')
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
        # Şifreyi hash'le
        password_hash = self._bcrypt_hash(password)
        
        # DB'de user'ı bul
        conn = psycopg2.connect(
            host=self._config.get('db_host', 'localhost'),
            port=int(self._config.get('db_port', '5432')),
            dbname=self._config.get('db_name', 'medical_ai'),
            user=self._config.get('db_user', 'medical_user')
        )
        cur = conn.cursor()
        
        cur.execute("""
            SELECT user_id, email, full_name, role, is_active, created_at, last_login, password_hash
            FROM users 
            WHERE email = %s AND password_hash = %s
        """, (email, password_hash))
        
        user = cur.fetchone()
        cur.close()
        conn.close()
        
        if not user:
            return {
                'success': False,
                'message': 'Kullanıcı bulunamadı veya parola hatalı',
                'token': None,
                'user': None
            }
        
        # JWT token oluştur
        token = self.generate_jwt(user[1], user[3])
        
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
            user=self._config.get('db_user', 'medical_user')
        )
        cur = conn.cursor()
        
        cur.execute("""
            UPDATE users 
            SET last_login = NOW(), created_at = created_at
            WHERE user_id = %s
        """, (user_id,))
        
        conn.commit()
        cur.close()
        conn.close()

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
                user=self._config.get('db_user', 'medical_user')
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
            user=self._config.get('db_user', 'medical_user')
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
            user=self._config.get('db_user', 'medical_user')
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
