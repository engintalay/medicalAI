# Medical AI - Kodlama Kuralları

> Bu dosya, proje geliştirme süreçlerinde uyulması gereken kuralları tanımlar.
> Herhangi bir kod yazmaya başlamadan önce bu kuralları okuyun.

---

## **1. Genel Kodlama Kuralları**

### 1.1. Kodlama Dili ve Framework
- **Python Ortamı**: `venv` (sanal ortam, bağımlılıklar izole)
- **Backend**: Python 3.10+ FastAPI
- **Veritabanı**: PostgreSQL (remote/uzak erişim, psycopg2-binary)
- **Cache**: Redis (remote/uzak erişim)
- **Konfigürasyon**: Tüm servis bağlantıları `system_config` tablosundan yönetilir. `.env` dosyası kullanılmaz.

### 1.2. Kod Stili (PEP 8)
- Python 3.10+ PEP 8 standartlarına uygun kod yazın
- Satır uzunluğu: maksimum 100 karakter
- 4-space indent (asla tab kullanmayın)
- Değişken ve fonksiyon isimleri açıklayıcı olmalı
- Açıklayıcı yorumlar ekleyin (özellikle RAG pipeline)

```python
# DOĞRU
def generate_embedding(text_chunk, model):
    """Metin parçasını embedding vektörüne dönüştürür."""
    return model.encode(text_chunk)

# YANLIŞ
def genEmb(txt):
    return model.encode(txt)
```

---

## **2. Dosya ve Klasör Düzeni**

### 2.1. Proje Yapısı
```
medical_ai/
├── app.py                 # Main FastAPI entry point
├── requirements.txt       # Bağımlılıklar
├── .env                   # Environment variables (git'e DEĞİL)
├── .gitignore
├── README.md
├── database/
│   └── schema.sql         # PostgreSQL schema
├── models/
│   ├── user.py            # User model
│   ├── rag_document.py    # RAG document model
│   └── health.py          # Health metrics model
├── routes/
│   ├── auth.py            # Authentication routes
│   ├── rag.py             # RAG routes
│   ├── chat.py            # Main LLM routes
│   ├── dashboard.py       # Dashboard routes
│   ├── admin.py           # Admin routes
│   └── upload.py          # File upload routes
├── services/
│   ├── embedding.py       # Embedding pipeline
│   ├── visual_llm.py      # Visual model service
│   ├── main_llm.py        # Main LLM service
│   ├── chunking.py        # Chunking logic
│   └── notification.py    # Notification service
├── database/
│   └── connection.py      # Database connection
├── config/
│   ├── config.py          # Configuration
│   └── security.py        # Security settings
└── utils/
    └── helpers.py         # Utility functions
```

### 2.2. Dosya Adlandırma
- Modüller: `snake_case` (örnek: `rag_document.py`)
- Dosyalar: Açıklayıcı İngilizce/Türkçe karışık isimler
- Fonksiyonlar: `snake_case`

---

## **3. Veritabanı Kuralları**

### 3.1. Schema Yönetimi
- Tüm tablo değişiklikleri migration script'lerinde
- Schema changes önce test edilir
- Migration script'leri version kontrollü (migration_001_*.sql)

### 3.2. Config-Based Connection (YENİ - Faz 0)
- **Yeni yaklaşım**: Veritabanı bağlantısı `system_config` tablosundan yönetilir
- Uygulama başlarken config'i okur (Redis cache ile)
- Admin panel üzerinden config güncellenir (hot reload ile)
- **ASLA** `.env` file'ı kullanmayın - tüm bağlantılar config üzerinden
- Admin panel ilk yapılacak faz (Faz 0)

### 3.3. system_config Tablosu Key'leri
- `db_host`, `db_port`, `db_name`, `db_user`, `db_password` - PostgreSQL
- `redis_host`, `redis_port` - Redis
- `llm_api_key`, `llm_endpoint` - Main LLM
- `embedding_model`, `vector_size` - Embedding
- `rag_top_k` - RAG sonuc sayısı
- `upload_dir` - Dosya yükleme dizini
- `admin_default_password` - Varsayılan admin şifresi

### 3.2. Veri Tipi Standartları
- Integer ID'ler: `SERIAL PRIMARY KEY`
- Tarih: `TIMESTAMP`
- Ondalıklı: `DECIMAL(5,2)`
- Boşluklu metin: `VARCHAR` (uygun uzunluk)
- Uzun metin: `TEXT`
- JSON: `JSONB` (esnek metadata için)

### 3.3. Veri Güvenliği
- **ASLA** plaintext password'ları saklamayın
- Password'lar bcrypt ile hash'lenir
- User verileri `user_id` ile referans edilir, doğrudan `user_id` kullanılmaz
- SQL injection'a karşı parametrik sorgular kullanın

```python
# DOĞRU - Parametrik sorgu
cur.execute("SELECT * FROM users WHERE email = %s", (email,))

# YANLIŞ - SQL injection riski
cur.execute(f"SELECT * FROM users WHERE email = {email}")
```

---

## **4. RAG Pipeline Kuralları**

### 4.1. Embedding Standartları
- Embedding boyutu sabit (model seçimine göre: 384, 768, 1536)
- Embedding boyutu `rag_documents.content_vector` kolonunda tanımlı
- Embedding generation asenkron (long-running işlemler için)

### 4.2. Chunking Kuralları
- PDF chunk: 500-1000 karakter
- Overlap: 100-200 karakter
- Her chunk'a metadata eklenecek: dosya_adi, sayfa, source_type, user_id

### 4.3. Context Assembly
- User query → embedding → similarity search
- Top-K: 5 sonuç (varsayılan)
- Context user data + public data birleştirilir
- Context format: net ve yapılandırılmış

---

## **5. API Kuralları**

### 5.1. Endpoint Standartları
- RESTful design
- Resource-based: `/api/users`, `/api/chat`, `/api/rag`
- Versioning: `/api/v1/`
- Consistent response format:
```json
{
  "success": true,
  "data": {...},
  "error": null
}
```

### 5.2. Error Handling
- HTTP status codes kullanın (200, 400, 401, 403, 404, 500)
- Error message'ler açıklayıcı
- Error logging

### 5.3. Authentication
- JWT tokens
- Auth middleware
- Refresh token mekanizması
- Admin endpoints için ayrı token

---

## **6. Güvenlik ve Sağlık Kuralları (CRITICAL)**

### 6.1. Medical Safety (EN ÖNEMLİ)
- **Tıbbi tavsiye verilmemeli** - sadece bilgilendirme
- Her cevap medikal disclaimer içermeli
- Yanlış/tehlikeli bilgi tespit edildiyse, güvenli cevap üret
- Kullanıcı verileri hassas, şifreli saklanmalı

### 6.2. Veri Gizliliği
- User verileri `user_id` ile isolated
- Public data ile user data ayrımı
- Veri silme hakkı (GDPR/HIPAA uyumlu)
- Veri export yeteneği

### 6.3. Input Validation
- Tüm input'lar validate edilir
- Dosya tipi/boyut kontrolü
- Text input uzunluğu limiti
- Injection attack'ları önle

---

## **7. Kod Kalitesi Kuralları**

### 7.1. Fonksiyon Kuralları
- Fonksiyonlar küçük ve tek sorumluluk
- Maksimum 50 satır fonksiyon
- Açıklayıcı yorumlar
- Docstring her public fonksiyon için

### 7.2. Test Kuralları
- Her modül için unit test
- Integration test: LLM pipeline
- Test coverage: minimum %70
- Test dosyaları: `*_test.py` veya `tests/` klasörü

### 7.3. Logging
- Tüm kritik işlemler loglanır
- User data loglanmAMAZ (gizlilik)
- Error logları ayrı dosyada

### 7.4. Documentation
- Her dosya başında başlık yorum
- Complex logic için detaylı yorum
- API endpoint'leri dokümante
- RAG pipeline adımları açık

---

## **8. Deployment Kuralları**

### 8.1. System Services
- Sistem service ile çalıştır
- `systemd` veya `pm2` kullanın
- Auto-restart: `Restart=always`

### 8.2. Backup
- PostgreSQL düzenli yedek
- Yedek: ayrı dosyada (encrypted)
- Backup schedule: günlük

### 8.3. Configuration
- `.env` dosyası git'e EKLİNMEZ
- `.gitignore` içine ekleyin
- Environment variables kullanın

---

## **9. Kodlama İyileştirme**

### 9.1. Refactoring
- Kod düzenli refactoring
- Teknik borcu takip
- Dead code temizle

### 9.2. Code Review
- Her modül tamamlandıktan sonra review
- Kod kalitesi kontrol
- Security check

### 9.3. Performance
- Index'ler optimize
- Redis cache kullan
- Async processing için background jobs

---

## **10. Kodlama Süreci (Workflow)**

1. **Plan**: Kodlama planında görevi belirle
2. **Implement**: Kodu yaz (bu kurallara göre)
3. **Test**: Testleri çalıştır
4. **Commit**: Değişiklikleri commit et (ZORUNLU - her kod değişikliği için)
5. **Document**: Gerekli dokümantasyonu güncelle
6. **Mark Progress**: coding_plan.md'de ilerlemeyi işaretle

### 11. Git Commit Kuralı (CRITICAL)

- **Her kod değişikliği için git commit YAPILMALI**
- Commit mesajı açıklayıcı olmalı: `git commit -m "Anlamlı açıklama"`
- Commit işleminin yapılmadığını asla ihmal etme
- Örnek: `git commit -m "Add user registration endpoint"`

---

## **Kısa Referans**

| Kural | Standart |
|-------|----------|
| Dili | Python 3.10+ FastAPI |
| Veritabanı | PostgreSQL + pgmodule |
| Cache | Redis |
| Kod Stili | PEP 8 (max 100 char) |
| Test Coverage | %70 minimum |
| Veri Güvenliği | Password hashing, parametrik sorgular |
| Medical Safety | Hiç tıbbi tavsiye, disclaimer |
| **Git Commit** | **Her kod değişikliği için ZORUNLU** |

---

## **Kısa Referans**

| Kural | Standart |
|-------|----------|
| Dili | Python 3.10+ FastAPI |
| Veritabanı | PostgreSQL + pgmodule |
| Cache | Redis |
| Kod Stili | PEP 8 (max 100 char) |
| Test Coverage | %70 minimum |
| Veri Güvenliği | Password hashing, parametrik sorgular |
| Medical Safety | Hiç tıbbi tavsiye, disclaimer |
| Git | plan.md, coding_plan.md, coding_rules.md |

---

**Bu kurallar, kodlama başlangıcından itibaren geçerlidir.** Herhangi bir şüphe durumunda bu dosyaya başvurun.
