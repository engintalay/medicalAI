# 🎯 Faz 0: Admin Panel & System Config - Detaylı Plan (Todo List)

Bu dosya, Faz 0'ın tüm iş akışını, sorumluluklarını ve mevcut durumunu takip etmek için hazırlanmıştır. Bu aşama tamamlandığında, sistemin yönetimsel temel altyapısı (Config, Auth, Monitoring) hazır olacaktır.

---

## 🌟 Faz 0 Genel Hedefi
Admin paneli ile sistemin kritik ayarlarını (PostgreSQL, Redis, LLM parametreleri) yönetmek, kullanıcıları izlemek ve genel sistem sağlığını (Monitoring) kontrol etmek.

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
- [ ] `config/loader.py` oluşturma (PostgreSQL system_config'den okuma)
- [ ] Config değişimi olduğunda Redis cache'i invalidate etme fonksiyonu
- [ ] Hot reload mekanizması (manuel veya otomatik çağrı)
- [ ] Fallback mekanizması (DB/Redis bağlantısı kesilirse default değerler kullanma)

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
| Basamak | Açıklama | Durum |
|---------|----------|-------|
| 1 | Ortam & Bağımlılıklar | 🔴 Başlangıç |
| 2 | system\_config Tablosu + Seed | ⬜ Yapılacak |
| 3 | Config Loader + Cache + Hot Reload | ⬜ Yapılacak |
| 4 | Admin Authentication (Login + JWT) | ⬜ Yapılacak |
| 5 | Admin Panel Routes (API) | ⬜ Yapılacak |
| 6 | HTML Admin Arayüzü (Templates) | ⬜ Yapılacak |
| 7 | PostgreSQL Ayarları Endpoint & UI | ⬜ Yapılacak |
| 8 | Kullanıcı Yönetimi + Script'ler | ⬜ Yapılacak |

---

## 📌 Sonraki Adımlar
Bu planı onayladıktan sonra, **Basamak 1**'den başlayarak uygulamaya geçebiliriz. Hangi basamakla başlamamı istersin? (Önerim: **Basamak 1**)