-- database/schema.sql

-- ---------------------------------------------------------
-- 1. system_config Tablosu: Tüm uygulama ayarlarının merkezi
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS system_config (
    key VARCHAR(50) PRIMARY KEY,
    value TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------
-- 2. Users Tablosu: Uygulama kullanıcıları (Patient/Admin)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    user_id SERIAL PRIMARY KEY,
    email VARCHAR(100) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL, -- bcrypt ile hash'lenmiş şifre
    full_name VARCHAR(150) NOT NULL,
    role VARCHAR(20) NOT NULL DEFAULT 'patient', -- patient, admin
    is_active BOOLEAN DEFAULT TRUE,
    height_cm NUMERIC(5, 2),
    weight_kg NUMERIC(5, 2),
    birth_year INTEGER,
    city VARCHAR(100),
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_login TIMESTAMP WITH TIME ZONE
);

-- ---------------------------------------------------------
-- 3. HealthMetrics Tablosu: Sağlık verileri (Boy, Kilo vb.)
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS health_metrics (
    metric_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    metric_name VARCHAR(50) NOT NULL, -- örn: 'weight', 'height'
    value DECIMAL(5, 2) NOT NULL,
    unit VARCHAR(20), -- örn: 'kg', 'cm'
    recorded_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------
-- 4. RAG Documents Tablosu: Veri parçacıkları ve vektörler
-- ---------------------------------------------------------
-- PostgreSQL 14+ için pgvector extension'ı gereklidir.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS rag_documents (
    doc_id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(user_id) ON DELETE SET NULL, -- NULL ise Public Data
    source_type VARCHAR(50) NOT NULL, -- 'pdf', 'image', 'web', 'user_upload'
    file_name VARCHAR(255),
    page_number INTEGER,
    content TEXT NOT NULL, -- Orijinal metin içeriği
    content_vector VECTOR(1536) NOT NULL, -- Varsayılan olarak 1536 boyutlu kabul ediyoruz (En büyük)
    metadata JSONB, -- Ekstra metadata (kaynak URL, vb.)
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------
-- 5. User Uploads Tablosu: Dosyaların metadata'sı
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS user_uploads (
    upload_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    file_path VARCHAR(255) NOT NULL, -- Dosyanın fiziksel yolu
    original_name VARCHAR(255) NOT NULL,
    mime_type VARCHAR(100),
    size_bytes BIGINT,
    upload_date TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- ---------------------------------------------------------
-- 6. ResearchData Tablosu: Harici/Public araştırma verileri
-- ---------------------------------------------------------
CREATE TABLE IF NOT EXISTS research_data (
    data_id SERIAL PRIMARY KEY,
    source_name VARCHAR(255) NOT NULL,
    content TEXT NOT NULL,
    content_vector VECTOR(1536) NOT NULL, -- Public data için de aynı boyutu kullanıyoruz
    metadata JSONB,
    is_primary BOOLEAN DEFAULT TRUE -- Bu veri ana veri mi?
);


-- ---------------------------------------------------------
-- INDEXLER
-- ---------------------------------------------------------
-- Users için hızlı lookup
CREATE INDEX idx_users_email ON users (email);
-- RAG Documents için en kritik indeks (Vektör araması)
CREATE INDEX idx_rag_content_vector ON rag_documents USING ivfflat (content_vector) WITH (lists = 100); -- 100 listesi, boyutlandırmaya göre ayarlanabilir
-- RAG Documents için User filtrelemesi
CREATE INDEX idx_rag_user_id ON rag_documents (user_id);
-- HealthMetrics için kullanıcıya göre hızlı sorgulama
CREATE INDEX idx_metrics_user_id ON health_metrics (user_id);

-- ---------------------------------------------------------
-- DEFAULT VALUES (Seed Data)
-- ---------------------------------------------------------

-- Default Admin Kullanıcı Oluşturma (Basamak 0 gerekliliği)
INSERT INTO users (email, password_hash, full_name, role, is_active) 
VALUES ('admin@medicalai.com', '$2b$12$YOUR_GENERATED_ADMIN_HASH_HERE', 'Sistem Yöneticisi', 'admin', TRUE);
-- NOT: YOUR_GENERATED_ADMIN_HASH_HERE yerine Bcrypt ile hashlenmiş şifrenin gelmesi gerekiyor.
-- Örnek olarak: '$2b$12$yA.O2zXyP/k....'

-- Default Config Değerleri (Basamak 2 gerekliliği)
-- NOT: Bu değerler Basamak 3'te Loader tarafından okunacak, ancak burada da tutulması tutarlılık için iyi.

-- PostgreSQL Remote, Redis yerel kabul edildiği için başlangıç değerleri:
INSERT INTO system_config (key, value, description) VALUES
('db_host', 'localhost', 'PostgreSQL host (Remote DB adresi)'),
('db_port', '5432', 'PostgreSQL port'),
('db_name', 'medical_ai', 'Veritabanı adı'),
('db_user', 'medical_user', 'DB kullanıcı adı'),
('db_password', 'changeme123', 'DB şifresi (Admin default şifresi)'),
('redis_host', 'localhost', 'Redis host'),
('redis_port', '6379', 'Redis port'),
('llm_api_key', '', 'Ana LLM API anahtarı (API key buraya gelecek)'),
('llm_max_tokens', '256', 'Ana LLM maksimum cevap token sayısı'),
('llm_timeout', '180', 'Ana LLM istek zaman aşımı (saniye)'),
('vision_max_tokens', '1024', 'Vision LLM maksimum cevap token sayısı'),
('vision_timeout', '180', 'Vision LLM istek zaman aşımı (saniye)'),
('embedding_model', 'all-MiniLM-L6-v2', 'Embedding model adı (CPU uyumlu varsayılan)'),
('rag_top_k', '5', 'RAG sonuc sayısı'),
('upload_dir', '/uploads', 'Dosya yükleme dizini'),
('admin_default_password', 'changeme123', 'Varsayılan admin şifresi');

-- Not: Basamak 3'te Loader bu verileri okuyacak, ancak bu yapı hem config hem de veri tutar.
-- Tekrar kontrol: Kullanıcı (Admin) ve Config'in veritabanında aynı anda olması tutarlılık sağlar.
-- Eğer Faz 3'te kullanıcı kaydı yapılırsa, bu INSERT'i (Admin için) kaldırıp,
-- Basamak 4'te kodla ekleme yapabiliriz, ancak şimdilik tutarlılık için ekledim.