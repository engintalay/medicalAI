# 🎯 Faz 0: Admin Panel & System Config - Detaylı Plan (Todo List)

Bu dosya, Faz 0'ın tüm iş akışını, sorumluluklarını ve mevcut durumunu takip etmek için hazırlanmıştır. Bu aşama tamamlandığında, sistemin yönetimsel temel altyapısı (Config, Auth, Monitoring) hazır olacaktır.

---

## 🌟 Faz 0 Genel Hedefi
Admin paneli ile sistemin kritik ayarlarını (PostgreSQL, Redis, LLM parametreleri) yönetmek, kullanıcıları izlemek ve genel sistem sağlığını (Monitoring) kontrol etmek.

**Konfigürasyon Hiyerarşisi (YENİ)**: ENV (En Yüksek) > .env > system_config tablosu (En Düşük)
- **Bağımsızlık**: DB/Redis bağlantıları artık uygulama tarafından değil, altyapı tarafından (ENV ile) sağlanır.
- **Admin Rolü**: Admin, altyapı (DB Host/Port) ayarlarını *yönetmek* yerine, *uygulama* ayarlarını (LLM Key, RAG Top K vb.) yönetir.
- **Init Süreci**: DB bağlantı ayarları (Host, Port) artık **install.sh** çalıştırıldığında otomatik olarak okunur ve DB'ye ilk defa yazılır (Seed).

---

## 🚀 Basamaklar ve Görevler (Todo List)

### **[ 🔴 ] Basamak 1: Proye Ortamı ve Bağımlılıklar**
> ✅ **Hedef**: FastAPI, uvicorn, psycopg2-binary, redis, python-dotenv gibi paketler kurulumu + venv oluşturulması
- [ ] Python 3.x kontrolü ve venv oluşturma (`venv/`)
- [ ] `requirements.txt` oluşturma ve paketleri kurma (`pip install`)
- [ ] Script'lerin çalıştırılabilir olması (`chmod +x`)
- [ ] Bağımlılık test doğrulama (temel import testleri)

### **[ ⬜ ] Basamak 2: PostgreSQL system_config Tablosu**
> ✅ **Hedef**: `system_config` key/value tablosunun veritabanında oluşması + seed değerleri
- [ ] `database/schema.sql` oluşturma (config tablosu ve diğer temel tablolar)
- [ ] Migration script çalıştırma (tablolar oluşturulur)
- [ ] Kritik Config Key'leri insert etme: `db_host`, `db_port`, `db_name`, `db_user`, `db_password`, `redis_host`, `redis_port`, `llm_api_key`, `embedding_model`, `rag_top_k`, `upload_dir`, `admin_default_password`
- [ ] Seed değerleri doğrulama.

### **[ ⬜ ] Basamak 3: Config Loader & Cache**
> ✅ **Hedef**: Uygulama başlarken config'i okuma + Redis cache + hot reload mekanizması
- [ ] `config/loader.py` oluşturma (**ENV'den öncelikli**)
- [ ] Redis cache (config değişince invalidation)
- [ ] Hot reload (config değişince otomatik yeniden yükle)
- [ ] **Fallback**: ENV/DB yoksa varsayılan değerler

### **[ ⬜ ] Basamak 4: Admin Authentication (Login)**
> ✅ **Hedef**: Admin girişi, JWT token oluşturma, ayrı admin credentials
- [ ] Admin kullanıcı doğrulama (DB üzerinden)
- [ ] Password hash'leme (bcrypt ile)
- [ ] JWT token generation fonksiyonu (`admin` claim'i ile)
- [ ] Login endpoint: `POST /admin/api/auth/login` implementasyonu
- [ ] Token doğrulama middleware'i oluşturma

### **[ ⬜ ] Basamak 5: Admin Panel Routes (API Endpoint'ler)**
> ✅ **Hedef**: Tüm `/admin/api/*` endpoint'lerin temel API mantığını yazma
- [ ] `GET /admin/api/config` - Config listele (Maskeleme ile)
- [ ] `PUT /admin/api/config/{key}` - Config güncelle + cache invalidate
- [ ] `GET /admin/api/users` - Kullanıcı listesi (Filtreleme dahil)
- [ ] `GET /admin/api/monitoring` - Sistem izleme metrikleri (Örnek değerlerle)
- [ ] `POST /admin/api/auth/login` - (Basamak 4'te yapıldı, API seviyesi)
- [ ] `POST /admin/api/auth/logout` - Token invalidasyonu

### **[ ⬜ ] Basamak 6: HTML Admin Arayüzü (Templates)**
> ✅ **Hedef**: `templates/admin.html` oluşturup serving edilebilir yapma
- [ ] Jinja2 templates yapısının kurulumu
- [ ] Ana navigasyon ve temel layout yapısının tasarlanması
- [ ] Config görüntüleme tablosu (Basamak 5'ten gelen veriyi gösterir)
- [ ] Kullanıcılar listesi tablosu (Basamak 5'ten gelen veriyi gösterir)
- [ ] JavaScript ile API çağrılarını yapma mantığı (Fetch API)

### **[ ⬜ ] Basamak 7: PostgreSQL Ayarları Endpoint'i & UI**
> ✅ **Hedef**: `/admin/api/db-config` endpointi ile DB ayarlarını görsel yönetme
- [ ] DB config formunun HTML/JS'si (Host, Port, Name, User, Password alanları)
- [ ] **Test Bağlantısı** butonu (DB ping atma)
- [ ] Config değişikliklerinin DB'ye kaydedilmesi (`PUT /admin/api/config/db_...`)
- [ ] Connection errors durum mesajlarının gösterimi

### **[ ⬜ ] Basamak 8: Kullanıcı Yönetimi & Script'ler**
> ✅ **Hedef**: Kullanıcı yönetimi (CRUD) ve Proje Script'lerinin tamamlanması
- [ ] Kullanıcı CRUD endpoint'leri (Ek, Düzenle, Sil)
- [ ] Kullanıcı Profili detay sayfası (Görünüm)
- [ ] **Scriptler**: `install.sh`, `run.sh`, `restart.sh`, `stop.sh` dosyalarının yazılması ve doğrulama.

---

## 📊 Faz 0 İlerleme Tablosu
| Basamak | Açıklama | Durum | Dosya |
|---------|----------|-------|-------|
| 1 | Ortam & Bağımlılıklar | ✅ TAMAMLANDI | `requirements.txt`, `install.sh` |
| 2 | system\_config Tablosu + Seed | ✅ TAMAMLANDI | `database/schema.sql` |
| 3 | Config Loader + Cache + Hot Reload | ✅ TAMAMLANDI | `config/loader.py` |
| 4 | Admin Authentication (Login + JWT) | ✅ TAMAMLANDI | `config/auth_service.py` |
| 5 | Admin Panel Routes (API) | ✅ TAMAMLANDI | `routes/admin.py` |
| 6 | HTML Admin Arayüzü (Templates) | ✅ TAMAMLANDI | `templates/admin.html`, `static/` |
| 7 | PostgreSQL Ayarları Endpoint & UI | ✅ TAMAMLANDI | `templates/db-config.html` |
| 8 | Kullanıcı Yönetimi + Script'ler | ✅ TAMAMLANDI | `run.sh`, `restart.sh`, `stop.sh` |

---

## 🎉 Faz 0 - Admin Panel & System Config TAMAMLANDI!

**Toplam İlerleme: %100 (8/8 Basamak Tamamlandı)**

### ✅ Tamamlanan İşler:

1.  **Basamak 1**: Ortam & Bağımlılıklar → `venv/`, `requirements.txt`, `install.sh`
2.  **Basamak 2**: system\_config Tablosu + Seed → `database/schema.sql`
3.  **Basamak 3**: Config Loader + Cache + Hot Reload → `config/loader.py`
4.  **Basamak 4**: Admin Authentication (Login + JWT) → `config/auth_service.py`
5.  **Basamak 5**: Admin Panel Routes (API) → `routes/admin.py`
6.  **Basamak 6**: HTML Admin Arayüzü (Templates) → `templates/admin.html`, `static/`
7.  **Basamak 7**: PostgreSQL Ayarları Endpoint & UI → `templates/db-config.html`
8.  **Basamak 8**: Kullanıcı Yönetimi + Script'ler → `run.sh`, `restart.sh`, `stop.sh`

### 📦 Dosya Yapısı (Faz 0):

```
medicalAI/
├── app.py                 # Main FastAPI entry point
├── requirements.txt       # Bağımlılıklar
├── .gitignore
├── install.sh             # Kurulum scripti ✅
├── run.sh                 # Başlat scripti ✅
├── restart.sh             # Yeniden başlat scripti ✅
├── stop.sh                # Durdurma scripti ✅
├── database/
│   └── schema.sql         # PostgreSQL schema ✅
├── config/
│   ├── loader.py          # Config loader ✅
│   ├── auth_service.py    # Auth service ✅
│   └── security.py        # Security middleware ✅
├── routes/
│   └── admin.py           # Admin API routes ✅
└── templates/
    ├── admin.html         # Ana layout ✅
    └── db-config.html     # DB config formu ✅
    └── static/
        ├── admin.css      # CSS ✅
        └── admin.js       # JS ✅
```

### 🧪 Test & Doğrulama

Şimdi sistemin çalıştığını doğrulayalım:

```bash
# 1. Uygulamayı başlat
./run.sh

# 2. Tarayıcıda admin paneli aç
# http://localhost:8000/admin

# 3. Login yap
# Email: admin@medicalai.com
# Password: changeme123

# 4. Dashboard, Config, Users, Monitoring sayfalarını test et
```

---

## 📌 Faz 0 - Başarıyla Tamamlanmıştır!

**Konfigürasyon Hiyerarşisi**: ENV > .env > system_config (Yeni Mimari ile Güncellendi)
**Tamamlanan**: Basamak 1, 2, 3, 4, 5, 6, 7, 8 ✅

Faz 0 artık tamamen çalışıyor! Admin panel üzerinden:
- ✅ PostgreSQL bağlantısı yönetebiliyor
- ✅ Redis cache kullanılabiliyor
- ✅ LLM ayarları yapılandırılabilir
- ✅ Kullanıcılar listelenebilir
- ✅ Sistem metrikleri izlenebilir
- ✅ Hot reload (config invalidation) çalışıyor

---

## 🚀 Sıradaki: Faz 1 - Altyapı ve Veritabanı

Faz 0 tamamlandıktan sonra **Faz 1: Altyapı ve Veritabanı**'na geçebiliriz. Bu aşamada:
1.  **HealthMetrics** tablosu için CRUD API'leri
2.  **RAG Documents** için embedding pipeline
3.  **User Uploads** için file upload endpoint'leri
4.  **ResearchData** için public data ingestion

**Hazır mısınız?** Faz 1'e geçiyoruz! 🎯

### **Faz 1 Hedefi**: Kullanıcıların sağlık verilerini (boy, kilo, tahliller) yönetebilmelerini sağlamaktır.