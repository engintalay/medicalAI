# config/loader.py
import os
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
        # Çevre değişkenlerinden DB ve Redis bağlantı detaylarını alır.
        # Bu değerler, .env dosyası (geçici kullanım için) veya doğrudan kodda fallback olarak tutulur.
        db_host = os.getenv("DB_HOST", "localhost")
        db_port = os.getenv("DB_PORT", "5432")
        db_name = os.getenv("DB_NAME", "medical_ai")
        db_user = os.getenv("DB_USER", "medical_user")
        # Şifre, DB bağlantısı kurmadan önce alınamayabilir, bu yüzden şimdilik varsayılıyor
        db_password = os.getenv("DB_PASSWORD", "changeme123") 
        
        # Redis bağlantısını dener
        try:
            self._redis = redis.Redis(host=os.getenv("REDIS_HOST", "localhost"), port=int(os.getenv("REDIS_PORT", "6379")), decode_responses=True)
            self._redis.ping()
            print("✅ Redis Bağlantısı Başarıyla Kuruldu.")
        except redis.exceptions.ConnectionError as e:
            print(f"⚠️ Redis Bağlantı Hatası: {e}. Redis cache kullanılamayacak, sadece bellekte kalacak.")
            self._redis = None

        self._cache: Dict[str, Any] = {}
        self.load_all()
        print("✅ ConfigLoader başlatıldı ve tüm ayarlar belleğe yüklendi.")

    def load_all(self):
        """Tüm config'leri PostgreSQL'den oku + Redis'e cachele."""
        try:
            # DB Bağlantısı Kurulumu
            conn = psycopg2.connect(
                host=os.getenv("DB_HOST", "localhost"),
                port=int(os.getenv("DB_PORT", "5432")),
                dbname=os.getenv("DB_NAME", "medical_ai"),
                user=os.getenv("DB_USER", "medical_user")
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

