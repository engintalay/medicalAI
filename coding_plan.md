# Medical AI - Kodlama Planı

> Bu dosya, kodlama sırasını ve yapılan işlemleri takip etmek için kullanılır.
> ✅ = Tamamlandı | 🔴 = Başlangıç | 🟡 = Devam Ediyor | ⬜ = Yapılacak

---

> ⚠️ **YENİ BAŞLANGIÇ**: Kodlar silindi, proje sıfırdan kuruluyor. Yukarıdaki
> ✅ işaretleri eski kodları gösteriyor; **tüm fazların yeniden uygulanması gerekli.**
> Bu dosyadaki ilerleme işaretleri sıfırlanarak gerçek durum yansıtılacak.
> Not: PostgreSQL remote, Redis remote (her ikisi de config olarak girilecek), Python ortamı `venv`.
> Not: Faz 0 Redis olmadan (config tabanlı taslak olarak) başlıyor; Redis cache opsiyonel.

---

## **Faz 0: Admin Panel & System Config (YENİ - İlk Faz)**

> **Yeni yaklaşım**: Admin panel ile başlıyoruz. Sistem config tablosu üzerinden
> PostgreSQL, Redis, LLM bağlantıları yönetilebilir olacak. **Veritabanı kurulumu da
> admin panelinden yapılabilir.**

### 0.1. Bağımlılıkları kurulum
- [ ] Python 3.x kurulumu (venv)
- [ ] pip package kurulum (fastapi, uvicorn, psycopg2-binary, redis, python-dotenv, sentence-transformers)
- [ ] Bağımlılık test doğrulama

### 0.2. system_config tablosu oluşturma
- [ ] Config tablosu (key/value yapısı)
- [ ] Default config değerleri (seed)
- [ ] Config key'leri: db_host, db_port, db_name, db_user, db_password, redis_host, redis_port, vb. (PostgreSQL remote, Redis yerel)

### 0.3. Config loader & cache (YENİ - eklendi)
- [ ] Config dosyası okuyucu (PostgreSQL system_config'den)
- [ ] Redis cache (config değişince invalidation)
- [ ] Hot reload (config değişince otomatik yeniden yükle)

### 0.4. Admin Authentication (YENİ - eklendi)
- [ ] Admin login (separate credentials)
- [ ] Admin JWT token
- [ ] Admin middleware (sadece admin)
- [ ] Default admin user oluşturma

### 0.5. Admin Panel Routes (GENISLETİLDİ)
- [ ] `GET /admin/api/config` - config listele
- [ ] `PUT /admin/api/config/{key}` - config güncelle
- [ ] `POST /admin/api/sql/execute` - SQL komut çalıştırması (GENİŞLETME)
- [ ] `GET /admin/api/sql/templates` - SQL şablonları
- [ ] `GET /admin/api/users` - kullanıcı listesi
- [ ] `GET /admin/api/monitoring` - sistem durumu

### 0.6. Test
- [ ] Config CRUD test
- [ ] Admin auth test
- [ ] Hot reload test
- [ ] SQL execution test (güvenli mod)

---

## **Faz 1: Altyapı ve Veritabanı (Foundation)**

### 1.1. Bağımlılıkları kurulum
- [ ] Python 3.x kurulumu
- [ ] pip package kurulum (fastapi, uvicorn, psycopg2-binary, redis, python-dotenv)
- [ ] Bağımlılık test doğrulama

### 1.2. PostgreSQL bağlantı kurulumu (Config'den okunacak)
- [ ] Config-based connection (admin ayarları kullanılır)
- [ ] Connection test
- [ ] Redis bağlantı test

### 1.3. PostgreSQL schema oluşturma
- [ ] users tablosu oluşturma
- [ ] health_metrics tablosu oluşturma
- [ ] rag_documents tablosu + pgvector extension
- [ ] user_uploads tablosu
- [ ] research_data tablosu
- [ ] Index oluşturma (vector similarity için)

### 1.4. Redis kurulum ve test
- [ ] Redis client config
- [ ] Connection test

### 1.5. Veritabanı migration scripti
- [ ] Migration script oluşturma
- [ ] Schema test çalıştırma

---

## **Faz 2: Authentication & User Management**

### 2.1. Auth service
- [ ] Register function (email + password hash)
- [ ] Login function
- [ ] JWT token generation
- [ ] Password hashing (bcrypt)

### 2.2. User model & API
- [ ] User model definition
- [ ] Role-based access (patient/admin)
- [ ] Middleware for auth

### 2.3. User profile endpoints
- [ ] `POST /api/auth/register`
- [ ] `POST /api/auth/login`
- [ ] `GET /api/user/profile`
- [ ] `PUT /api/user/profile`

### 2.4. Redis session management
- [ ] Session token storage
- [ ] Session expiry handling

### 2.5. Test
- [ ] Register/Login test
- [ ] Profile access test

---

## **Faz 3: RAG Sistemi (Embedding + Vector Storage)**

### 3.1. Embedding model kurulumu
- [ ] Sentence-Transformers model seçimi
- [ ] Model yükleme ve test
- [ ] Embedding generation function

### 3.2. Chunking logic
- [ ] PDF sayfa bazlı chunking
- [ ] Metadata extraction
- [ ] Overlap logic

### 3.3. RAG documents pipeline
- [ ] `POST /api/rag/add-document`
- [ ] PDF→text→embed→store workflow
- [ ] Error handling

### 3.4. Similarity search function
- [ ] Cosine similarity query
- [ ] User-specific vs global search
- [ ] Top-K results retrieval

### 3.5. Test
- [ ] Embedding store test
- [ ] Similarity search test

---

## **Faz 4: Data Ingestion & Visual LLM**

### 4.1. File upload endpoint
- [ ] `POST /api/upload`
- [ ] PDF/resim kaydetme
- [ ] Dosya yolları PostgreSQL'e yazma
- [ ] Validation (dosya tipi, boyut)

### 4.2. Visual LLM service
- [ ] PDF extraction
- [ ] Image → text conversion (OCR)
- [ ] Text normalization

### 4.3. RAG document integration
- [ ] Visual LLM output → rag_documents
- [ ] Metadata injection

### 4.4. Public data ingestion
- [ ] Web scraping / API for research
- [ ] `POST /api/research`
- [ ] Content storage

### 4.5. Test
- [ ] Upload test
- [ ] Visual LLM extraction test

---

## **Faz 5: Main LLM Engine**

### 5.1. Chat endpoint
- [ ] `POST /api/chat`
- [ ] System prompt (medical safety)
- [ ] Context injection

### 5.2. RAG context assembly
- [ ] Similarity search → context
- [ ] Combine user data + public data
- [ ] Context formatting

### 5.3. Multi-turn conversation
- [ ] Session management
- [ ] Context persistence
- [ ] Conversation history

### 5.4. Safety guardrails
- [ ] Medical disclaimer
- [ ] Incorrect answer prevention
- [ ] Input validation

### 5.5. Test
- [ ] Chat flow test
- [ ] Safety test scenarios

---

## **Faz 6: Dashboard & Analytics API**

### 6.1. Metrics endpoints
- [ ] `GET /api/user/metrics`
- [ ] Health trends calculation
- [ ] Time-series data

### 6.2. Dashboard data
- [ ] Charts data (JSON format)
- [ ] Health insights

### 6.3. Notification endpoints
- [ ] `GET /api/notifications`
- [ ] Reminder preferences
- [ ] Notification scheduling

### 6.4. Export functionality
- [ ] CSV export
- [ ] PDF export

### 6.5. Test
- [ ] Metrics endpoint test
- [ ] Export test

---

## **Faz 7: Admin Panel (Ayrı)**

### 7.1. Admin auth
- [ ] Separate admin tokens
- [ ] `GET /admin/api/*` routes
- [ ] Admin middleware

### 7.2. User management
- [ ] List/filter users
- [ ] Export user data
- [ ] User actions

### 7.3. System monitoring
- [ ] LLM performance metrics
- [ ] Usage statistics
- [ ] Error rates

### 7.4. Content management
- [ ] Public data management
- [ ] Data update/delete

### 7.5. Test
- [ ] Admin access test
- [ ] User management test

---

## **Faz 8: Testing & Documentation**

### 8.1. Unit tests
- [ ] Auth module tests
- [ ] RAG pipeline tests
- [ ] LLM integration tests

### 8.2. Integration tests
- [ ] Full user flow test
- [ ] API endpoint tests
- [ ] Error scenario tests

### 8.3. API documentation
- [ ] OpenAPI/Swagger setup
- [ ] Postman collection
- [ ] Endpoint documentation

### 8.4. Medical safety testing
- [ ] Incorrect answer scenarios
- [ ] Medical disclaimer coverage
- [ ] User feedback testing

### 8.5. Final deployment prep
- [ ] Deployment script
- [ ] Backup script
- [ ] Final documentation

---

## **İşlenen İşlemler Takibi (Progress Log)**

> Her tamamlanan işlemin tarihi ve notu burada kaydedilir.

| Tarih | Faz | İşlem | Durum | Not |
|-------|-----|-------|-------|-----|
| 2026-10-26 | - | Plan oluşturuldu | ✅ | Plan, mimari, RAG, kodlama sırası belirlendi |
| 2026-10-26 | - | Kodlar silindi | 🔴 | Proje sıfırdan kurulacak, tüm fazlar yeniden yapılacak |
| 2026-10-26 | - | git başlatıldı | ✅ | İlk commit alındı (plan/kurallar planı) |
| 2026-10-26 | - | Plan güncellendi | ✅ | PostgreSQL remote, Redis yerel, Python ortamı venv |
| 2026-10-26 | - | Plan oluşturuldu | ✅ | Plan, mimari, RAG, kodlama sırası belirlendi |
| - | 0 | Bağımlılıklar kurulum | ✅ | fastapi, uvicorn, psycopg2-binary, redis, python-dotenv installed |
| - | 0 | system_config tablosu oluşturma | ✅ | database/schema.sql oluşturuldu |
| - | 0 | Config loader & cache | ✅ | config/loader.py çalışıyor (fallback with defaults) |
| - | 0 | Admin Authentication | ✅ | Admin endpoint'leri çalışıyor |
| - | 0 | Admin Panel Routes | ✅ | GET/POST/admin/api/config endpoints implemented |
| - | 0 | SQL Execution Endpoints | ✅ | /admin/api/sql/execute ve /admin/api/sql/templates eklendi |
| - | 0 | HTML Admin Arayüzü | ✅ | templates/admin.html oluşturulup serving ediliyor |
| - | 0 | PostgreSQL Ayarları | ✅ | /admin/api/db-config endpoint + HTML gösterimi |
| - | 0 | Kullanıcı Yönetimi | ✅ | /admin/api/users endpoint + kullanıcı listesi tablosu |
| - | 0 | Script Dosyaları | ✅ | run.sh, restart.sh, stop.sh, install.sh eklendi |
| - | - | Faz 0 tamamlandı | ✅ | Admin Panel & System Config tamamen çalışıyor - DB yönetimi + HTML UI included |

---

## **Toplam Durum**

| Faz | İlerleme | Durum |
|-----|----------|-------|
| Faz 0: Admin Panel & Config | 0% | Başlanacak (kodlar silindi, sıfırdan) |
| Faz 1: Altyapı | 0% | Başlanmadı |
| Faz 2: Authentication | 0% | Başlanmadı |
| Faz 3: RAG Sistemi | 0% | Başlanmadı |
| Faz 4: Data Ingestion | 0% | Başlanmadı |
| Faz 5: Main LLM Engine | 0% | Başlanmadı |
| Faz 6: Dashboard & Analytics | 0% | Başlanmadı |
| Faz 7: Testing & Docs | 0% | Başlanmadı |
| Faz 8: Admin Panel (User Content) | 0% | Başlanmadı |

**Toplam İlerleme: %0 (tamamen sıfırdan başlıyor)**

---

## **Script Dosyaları (YENİ)**

Proje yönetimi ve deployment için hazırlanan bash script'leri:

| Script | Açıklama | Kullanım |
|--------|----------|----------|
| `install.sh` | Bağımlılıkları kurar ve venv oluşturur | `./install.sh` |
| `run.sh` | Uygulamayı başlatır (arkada mod) | `./run.sh` |
| `restart.sh` | Uygulamayı yeniden başlatır | `./restart.sh` |
| `stop.sh` | Uygulamayı durdurur | `./stop.sh` |

**Script Özellikleri:**
- `install.sh`: Virtual environment oluşturur, gerekli Python paketlerini (fastapi, uvicorn, psycopg2-binary, redis, python-dotenv) yükler, script'leri çalıştırılabilir yapar
- `run.sh`: Uygulamayı `http://localhost:8000` üzerinde başlatır, admin panel adresi `http://localhost:8000/admin`
- `restart.sh`: Önceki process'i güvenilir şekilde durdurup yeniden başlatır, PID dosyası ile takip eder
- `stop.sh`: Çalışan uvicorn process'ini durdurur, PID dosyası yoksa process'i arar
- Tüm script'ler `medicalAI` dizininde çalıştırılacak şekilde yapılandırıldı

---

**Not**: Kodlama planı hazır. Planı onayladıktan sonra kodlama başlayacaktır. Her tamamlanan faz bu dosyada işaretlenecek.
