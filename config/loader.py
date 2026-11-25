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

        Bootstrap için DB/Redis adresleri .env'den okunur; gerçek kaynak
        `system_config` tablosudur. load_all() sonrası Redis bağlantısı
        config değerleriyle yeniden kurulur (hot reload destekli).
        """
        # Çevre değişkenlerinden DB ve Redis bağlantı detaylarını alır (.env'den yüklenir).
        self._db_host = os.getenv("DB_HOST", "localhost")
        self._db_port = int(os.getenv("DB_PORT", "5432"))
        self._db_name = os.getenv("DB_NAME", "medical_ai")
        self._db_user = os.getenv("DB_USER", "medical_user")
        self._db_password = os.getenv("DB_PASSWORD", "")

        self._cache: Dict[str, Any] = {}
        self._redis = None
        self._redis_params = None
        # .env değerlerini fallback olarak cache'e koy (DB erişilemezse de config çalışsın)
        self._seed_from_env()
        self._connect_redis_from_config(announce=True)
        self.load_all()
        # system_config değerleri .env fallback'ini ezdiyse Redis'i yeniden bağla.
        self._connect_redis_from_config(announce=False)
        print("✅ ConfigLoader başlatıldı ve tüm ayarlar belleğe yüklendi.")

    def _redis_config(self) -> dict:
        """Redis ayarlarını config cache'inden (fallback: .env) okur."""
        def port_value(value, default):
            try:
                return int(value or default)
            except (TypeError, ValueError):
                return int(default)

        return {
            "host": str(self.get("redis_host") or os.getenv("REDIS_HOST", "localhost")),
            "port": port_value(self.get("redis_port"), 6379),
            "password": self.get("redis_password") or os.getenv("REDIS_PASSWORD") or None,
            "username": self.get("redis_username") or os.getenv("REDIS_USERNAME") or None,
        }

    def _connect_redis_from_config(self, announce: bool = True) -> bool:
        """Config'deki Redis uç noktasına bağlanır; değişmediyse yeniden bağlanmaz."""
        params = self._redis_config()
        if self._redis is not None and params == self._redis_params:
            return True
        old = self._redis
        try:
            client = redis.Redis(
                host=params["host"],
                port=params["port"],
                password=params["password"],
                username=params["username"],
                socket_connect_timeout=5,
                decode_responses=True,
            )
            client.ping()
        except Exception as exc:
            # Hata mesajına şifre/token yazılmaz; yalnızca uç nokta adı görünür.
            print(f"⚠️ Redis Bağlantı Hatası ({params['host']}:{params['port']}): {exc}. Bellek cache kullanılacak.")
            if old is not None:
                try:
                    old.close()
                except Exception:
                    pass
            self._redis = None
            self._redis_params = None
            return False
        if old is not None:
            try:
                old.close()
            except Exception:
                pass
        self._redis = client
        self._redis_params = params
        if announce:
            print(f"✅ Redis Bağlantısı Başarıyla Kuruldu ({params['host']}:{params['port']}).")
        return True

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
            "redis_password": os.getenv("REDIS_PASSWORD", ""),
            "redis_username": os.getenv("REDIS_USERNAME", ""),
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
            "embedding_model": os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"),
            "rag_top_k": os.getenv("RAG_TOP_K", "5"),
            "rag_chunk_size": os.getenv("RAG_CHUNK_SIZE", "500"),
            "rag_overlap": os.getenv("RAG_OVERLAP", "100"),
            "upload_dir": os.getenv("UPLOAD_DIR", "uploads"),
            "max_upload_mb": os.getenv("MAX_UPLOAD_MB", "20"),
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

    def connect_db(self):
        """Config'den okunanPostgreSQL bağlantısını açar (servisler için ortak nokta)."""
        return psycopg2.connect(
            host=self.get("db_host", "localhost"),
            port=int(self.get("db_port", "5432") or 5432),
            dbname=self.get("db_name", "medical_ai"),
            user=self.get("db_user", "medical_user"),
            password=self.get("db_password", "") or "",
            connect_timeout=10,
        )

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

        # Redis uç noktası/şifresi değiştiyse bağlantıyı config'den yenile.
        if key.startswith("redis_"):
            self._connect_redis_from_config(announce=False)

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
            # 3. Redis bağlantı ayarıysa system_config'den tekrar oku
            if key.startswith("redis_"):
                try:
                    conn = self.connect_db()
                    with conn.cursor() as cur:
                        cur.execute("SELECT value FROM system_config WHERE key = %s", (key,))
                        row = cur.fetchone()
                    conn.close()
                    if row:
                        self._cache[key] = row[0]
                except Exception:
                    pass
                self._connect_redis_from_config(announce=False)
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

