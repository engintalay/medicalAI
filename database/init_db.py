#!/usr/bin/env python3
"""
database/init_db.py - Veritabanı şemasını güvenli/tekrar çalıştırılabilir şekilde kurar.

- .env dosyasındaki gerçek bağlantı bilgilerini kullanır.
- pgvector varsa VECTOR(1536), yoksa JSONB fallback ile RAG tablolarını oluşturur.
- system_config seed değerlerini .env'den yazar (DB şifresi vb. yanlış seed edilmesin).
- Admin kullanıcısını gerçek bcrypt hash ile oluşturur/günceller.

Kullanım:  python database/init_db.py
"""

import os
import sys
from pathlib import Path

import bcrypt
import psycopg2
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=ROOT / ".env")

DB = dict(
    host=os.getenv("DB_HOST", "localhost"),
    port=int(os.getenv("DB_PORT", "5432")),
    dbname=os.getenv("DB_NAME", "medical_ai"),
    user=os.getenv("DB_USER", "medical_user"),
    password=os.getenv("DB_PASSWORD", ""),
)


def main() -> int:
    print(f"→ Bağlanılıyor: {DB['user']}@{DB['host']}:{DB['port']}/{DB['dbname']}")
    conn = psycopg2.connect(connect_timeout=10, **DB)
    conn.autocommit = False
    cur = conn.cursor()

    # --- pgvector kontrolü / kurulumu ---
    cur.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'vector';")
    vector_available = cur.fetchone() is not None
    pgvector = False
    if vector_available:
        try:
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector;")
            pgvector = True
        except Exception as e:
            conn.rollback()
            print(f"⚠️  pgvector kurulamadı ({e}). Vektörsüz devam ediliyor.")
    else:
        print("⚠️  pgvector sunucuda mevcut değil. RAG tabloları JSONB ile oluşturulacak.")

    vector_type = "VECTOR(1536)" if pgvector else "JSONB"

    # --- Tablolar ---
    cur.execute("""
        CREATE TABLE IF NOT EXISTS system_config (
            key VARCHAR(50) PRIMARY KEY,
            value TEXT NOT NULL,
            description TEXT,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id SERIAL PRIMARY KEY,
            email VARCHAR(100) UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name VARCHAR(150) NOT NULL,
            role VARCHAR(20) NOT NULL DEFAULT 'patient',
            is_active BOOLEAN DEFAULT TRUE,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP WITH TIME ZONE
        );
    """)

    # --- Profil alanları (mevcut DB'ler için idempotent migration) ---
    for column, column_type in (
        ("height_cm", "NUMERIC(5,2)"),
        ("weight_kg", "NUMERIC(5,2)"),
        ("birth_year", "INTEGER"),
        ("city", "VARCHAR(100)"),
    ):
        cur.execute(f"ALTER TABLE users ADD COLUMN IF NOT EXISTS {column} {column_type};")

    cur.execute("""
        CREATE TABLE IF NOT EXISTS health_metrics (
            metric_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            metric_name VARCHAR(50) NOT NULL,
            value DECIMAL(5, 2) NOT NULL,
            unit VARCHAR(20),
            recorded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_uploads (
            upload_id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
            file_path VARCHAR(255) NOT NULL,
            original_name VARCHAR(255) NOT NULL,
            mime_type VARCHAR(100),
            size_bytes BIGINT,
            upload_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS rag_documents (
            doc_id SERIAL PRIMARY KEY,
            user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL,
            source_type VARCHAR(50) NOT NULL,
            file_name VARCHAR(255),
            page_number INTEGER,
            content TEXT NOT NULL,
            content_vector {vector_type},
            metadata JSONB,
            created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
    """)

    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS research_data (
            data_id SERIAL PRIMARY KEY,
            source_name VARCHAR(255) NOT NULL,
            content TEXT NOT NULL,
            content_vector {vector_type},
            metadata JSONB,
            is_primary BOOLEAN DEFAULT TRUE
        );
    """)

    # --- Index'ler ---
    cur.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_rag_user_id ON rag_documents (user_id);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_metrics_user_id ON health_metrics (user_id);")
    if pgvector:
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_rag_content_vector "
            "ON rag_documents USING ivfflat (content_vector) WITH (lists = 100);"
        )

    # --- system_config seed (.env'deki gerçek değerlerle) ---
    seeds = [
        ("db_host", DB["host"], "PostgreSQL host"),
        ("db_port", str(DB["port"]), "PostgreSQL port"),
        ("db_name", DB["dbname"], "Veritabanı adı"),
        ("db_user", DB["user"], "DB kullanıcı adı"),
        ("db_password", DB["password"], "DB şifresi"),
        ("redis_host", os.getenv("REDIS_HOST", "localhost"), "Redis host"),
        ("redis_port", os.getenv("REDIS_PORT", "6379"), "Redis port"),
        ("redis_password", os.getenv("REDIS_PASSWORD", ""), "Redis şifresi"),
        ("llm_api_key", os.getenv("LLM_API_KEY", ""), "Ana LLM API anahtarı"),
        ("llm_model", os.getenv("LLM_MODEL", "gpt-4o-mini"), "Ana LLM model adı (sağlık)"),
        ("llm_provider", os.getenv("LLM_PROVIDER", "openai"), "Ana LLM sağlayıcısı"),
        ("llm_base_url", os.getenv("LLM_BASE_URL", ""), "Ana LLM API adresi (opsiyonel)"),
        ("llm_vision_supported", os.getenv("LLM_VISION_SUPPORTED", "false"), "Ana LLM görsel (vision) destekliyor mu?"),
        ("vision_llm_enabled", os.getenv("VISION_LLM_ENABLED", "false"), "İkinci vision LLM kullanılsın mı?"),
        ("vision_llm_provider", os.getenv("VISION_LLM_PROVIDER", "openai"), "Vision LLM sağlayıcısı"),
        ("vision_llm_model", os.getenv("VISION_LLM_MODEL", ""), "Vision LLM model adı"),
        ("vision_llm_api_key", os.getenv("VISION_LLM_API_KEY", ""), "Vision LLM API anahtarı"),
        ("vision_llm_base_url", os.getenv("VISION_LLM_BASE_URL", ""), "Vision LLM API adresi (opsiyonel)"),
        ("embedding_model", os.getenv("EMBEDDING_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"), "Yerel Sentence-Transformers embedding modeli"),
        ("rag_top_k", os.getenv("RAG_TOP_K", "5"), "RAG sonuç sayısı"),
        ("rag_chunk_size", os.getenv("RAG_CHUNK_SIZE", "500"), "RAG chunk boyutu"),
        ("rag_overlap", os.getenv("RAG_OVERLAP", "100"), "RAG chunk overlap"),
        ("upload_dir", os.getenv("UPLOAD_DIR", "/uploads"), "Dosya yükleme dizini"),
        ("admin_default_password", os.getenv("ADMIN_DEFAULT_PASSWORD", "changeme123"), "Varsayılan admin şifresi"),
        ("jwt_secret", os.getenv("JWT_SECRET", "medical_ai_default_secret_2026"), "JWT imza anahtarı"),
    ]
    for key, value, desc in seeds:
        cur.execute(
            """
            INSERT INTO system_config (key, value, description)
            VALUES (%s, %s, %s)
            ON CONFLICT (key) DO UPDATE
              SET value = EXCLUDED.value,
                  description = EXCLUDED.description,
                  updated_at = NOW();
            """,
            (key, value, desc),
        )

    # --- Admin kullanıcısı ---
    admin_email = os.getenv("ADMIN_EMAIL", "admin@medicalai.com")
    admin_password = os.getenv("ADMIN_DEFAULT_PASSWORD", "changeme123")
    admin_hash = bcrypt.hashpw(admin_password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
    cur.execute(
        """
        INSERT INTO users (email, password_hash, full_name, role, is_active)
        VALUES (%s, %s, %s, 'admin', TRUE)
        ON CONFLICT (email) DO UPDATE
          SET password_hash = EXCLUDED.password_hash,
              role = 'admin',
              is_active = TRUE;
        """,
        (admin_email, admin_hash, "Sistem Yöneticisi"),
    )

    conn.commit()

    # --- Özet ---
    cur.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' ORDER BY table_name;"
    )
    tables = [r[0] for r in cur.fetchall()]
    cur.execute("SELECT COUNT(*) FROM system_config;")
    cfg_count = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM users;")
    user_count = cur.fetchone()[0]

    cur.close()
    conn.close()

    print("\n✅ Veritabanı hazır.")
    print(f"   Tablolar : {', '.join(tables)}")
    print(f"   Config   : {cfg_count} kayıt")
    print(f"   Kullanıcı: {user_count} kayıt (admin: {admin_email})")
    print(f"   pgvector : {'aktif' if pgvector else 'YOK (RAG vektörleri JSONB)'}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"\n❌ Hata: {exc}")
        sys.exit(1)
