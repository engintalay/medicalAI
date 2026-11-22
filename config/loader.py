# config/loader.py
import os
from dotenv import load_dotenv
from pathlib import Path

# .env dosyasını yükle (proje kök dizininde)
env_path = Path(__file__).parent.parent / '.env'
load_dotenv(dotenv_path=env_path)

import psycopg2
import redis
from typing import Dict, Any, Optional

# --- Global Singleton Instance ---
# Uygulama genelinde tek bir ConfigLoader örneği kullanılmasını sağlar.
config_loader = None

def get_config_loader() -> 'ConfigLoader':
    """ConfigLoader örneğine erişimi sağlar. Oluşturulmadıysa yeni bir tane yaratır."""
    global config_loader
    if config_loader is None:
        config_loader = ConfigLoader()
    return config_loader

class ConfigLoader:
    def __init__(self):
        """
        ConfigLoader'ı başlatır. Redis bağlantısını dener ve ilk yüklemeyi yapar.
        """
        # Çevre değişkenlerinden DB ve Redis bağlantı detaylarını alır (.env'den yüklenir).
        self._db_host = os.getenv("DB_HOST", "localhost")
        self._db_port = int(os.getenv("DB_PORT", "5432"))
        self._db_name = os.getenv("DB_NAME", "medical_ai")
        self._db_user = os.getenv("DB_USER", "medical_user")
        self._db_password = os.getenv("DB_PASSWORD", "")

        # Redis bağlantısını dener (şifre destekli)
        try:
            redis_password = os.getenv("REDIS_PASSWORD") or None
            redis_username = os.getenv("REDIS_USERNAME") or None
            self._redis = redis.Redis(
                host=os.getenv("REDIS_HOST", "localhost"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                password=redis_password,
                username=redis_username,
                decode_responses=True,
            )
            self._redis.ping()
            print("✅ Redis Bağlantısı Başarıyla Kuruldu.")
        except Exception as e:
            print(f"⚠️ Redis Bağlantı Hatası: {e}. Redis cache kullanılamayacak, sadece bellekte kalacak.")
            self._redis = None

        self._cache: Dict[str, Any] = {}
        # .env değerlerini fallback olarak cache'e koy (DB erişilemezse de config çalışsın)
        self._seed_from_env()
        self.load_all()
        print("✅ ConfigLoader başlatıldı ve tüm ayarlar belleğe yüklendi.")

    def _seed_from_env(self):
        """DB/Redis erişilemezse kullanılacak fallback değerleri .env'den yükler."""
        env_config = {
            "db_host": self._db_host,
            "db_port": str(self._db_port),
            "db_name": self._db_name,
            "db_user": self._db_user,
            "db_password": self._db_password,
            "redis_host": os.getenv("REDIS_HOST", "localhost"),
            "redis_port": os.getenv("REDIS_PORT", "6379"),
            "jwt_secret": os.getenv("JWT_SECRET", "medical_ai_default_secret_2026"),
            "llm_api_key": os.getenv("LLM_API_KEY", ""),
            "llm_model": os.getenv("LLM_MODEL", ""),
            "llm_provider": os.getenv("LLM_PROVIDER", "openai"),
            "llm_base_url": os.getenv("LLM_BASE_URL", ""),
            "llm_vision_supported": os.getenv("LLM_VISION_SUPPORTED", "false"),
            "vision_llm_enabled": os.getenv("VISION_LLM_ENABLED", "false"),
            "vision_llm_provider": os.getenv("VISION_LLM_PROVIDER", "openai"),
            "vision_llm_model": os.getenv("VISION_LLM_MODEL", ""),
            "vision_llm_api_key": os.getenv("VISION_LLM_API_KEY", ""),
            "vision_llm_base_url": os.getenv("VISION_LLM_BASE_URL", ""),
            "embedding_model": os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2"),
            "rag_top_k": os.getenv("RAG_TOP_K", "5"),
            "rag_chunk_size": os.getenv("RAG_CHUNK_SIZE", "500"),
            "rag_overlap": os.getenv("RAG_OVERLAP", "100"),
            "upload_dir": os.getenv("UPLOAD_DIR", "/uploads"),
            "admin_default_password": os.getenv("ADMIN_DEFAULT_PASSWORD", "changeme123"),
        }
        for key, value in env_config.items():
            self._cache[key] = value

    def load_all(self):
        """Tüm config'leri PostgreSQL'den oku + Redis'e cachele."""
        try:
            # DB Bağlantısı Kurulumu (şifre dahil)
            conn = psycopg2.connect(
                host=self._db_host,
                port=self._db_port,
                dbname=self._db_name,
                user=self._db_user,
                password=self._db_password,
            )
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM system_config ORDER BY key")
            rows = cur.fetchall()
            
            # Cache'leme
            for key, value in rows:
                self._cache[key] = value
                # Redis'e de cachele (Eğer Redis varsa)
                if self._redis:
                    self._redis.set(f"config:{key}", value)
            
            cur.close()
            conn.close()
            
        except psycopg2.OperationalError as e:
            print(f"❌ PostgreSQL Bağlantı Hatası: {e}. Varsayılan değerler kullanılacak.")
        except Exception as e:
            print(f"❌ Beklenmedik Hata (DB/Config): {e}. Varsayılan değerler kullanılacak.")


    def get(self, key: str, default: Any = None) -> Any:
        """Belirli bir config değerini getter fonksiyonu."""
        return self._cache.get(key, default)

    def set(self, key: str, value: Any):
        """
        Bir config değerini bellek ve Redis cache'ine anında yazar.

        DB bağlantı anahtarları değiştiğinde ConfigLoader'ın kendi bağlantı
        bilgilerini de günceller; böylece yeni ayarlar restart beklemeden
        sonraki sorgularda kullanılır.
        """
        self._cache[key] = value

        if self._redis:
            try:
                self._redis.set(f"config:{key}", value)
            except Exception:
                pass

        # DB bağlantı ayarları ConfigLoader tarafından ayrıca tutuluyor.
        if key == "db_host":
            self._db_host = value
        elif key == "db_port":
            try:
                self._db_port = int(value)
            except (TypeError, ValueError):
                pass
        elif key == "db_name":
            self._db_name = value
        elif key == "db_user":
            self._db_user = value
        elif key == "db_password":
            self._db_password = value

        print(f"🔄 Config '{key}' güncellendi.")

    def invalidate(self, key: Optional[str] = None):
        """
        Belirli key veya tüm cache'i Redis ve bellekteki önbelleği temizler.
        Bu, hot reload tetikler.
        """
        if key:
            # 1. Belleği temizle
            self._cache.pop(key, None)
            # 2. Redis'i temizle
            if self._redis:
                self._redis.delete(f"config:{key}")
            print(f"🔄 Config '{key}' başarıyla geçersiz kılındı (Invalidated).")
        else:
            # Tamamen temizle
            self._cache.clear()
            if self._redis:
                # Tüm ana config anahtarını temizle
                self._redis.delete("config:ALL") 
                print("🔄 Tüm Config'ler başarıyla geçersiz kılındı (Full Invalidation).")

# --- Kullanım Örneği (Test amaçlı) ---
if __name__ == "__main__":
    # Bu block, dosyayı doğrudan çalıştırdığımızda test eder.
    loader = get_config_loader()
    
    print("\n--- TEST BAŞLATILIYOR ---")
    print(f"DB Host (Getter): {loader.get('db_host')}")
    print(f"RAG Top K (Getter): {loader.get('rag_top_k')}")
    
    # Hot Reload Testi (Manuel simülasyon)
    print("\n--- HOT RELOAD TESTİ ---")
    # Diyelim ki DB'de 'rag_top_k' değeri 5'ten 10'a güncellendi.
    print("Simüle edilen güncelleme: rag_top_k = 10")
    loader.invalidate('rag_top_k')
    
    # Kontrol et
    print(f"Yeni RAG Top K değeri (Getter): {loader.get('rag_top_k')}")
    
    # Redis'te de var mı kontrol et
    if loader._redis:
        redis_value = loader._redis.get('config:rag_top_k')
        print(f"Redis'teki güncel değer: {redis_value}")

