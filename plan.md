# Medical AI Uygulaması - Plan ve Kararlar

## 1. Proje Amacı ve Hedef Kitle
- **Hedef Kitle**: Hasta kullanıcılar
- **Amacı**: Kullanıcılara tıbbi bilgiler, izlemler ve destek sunmak

## 2. Veri Kaynakları
- **Public Veri**: ilaç prospectüleri, internetten bulunan araştırmalar
- **Kullanıcı Özel Veri**: tahlil sonuçları, şikayetler, resimler (fotoğraflar, PDF'ler)
- **Veri Tipleri**: Text, PDF, görüntüler (resimler)

## 3. Mimari
- **İki LLM Sistemi**:
  1. **Ana Model**: Asıl cevaplar üretir
  2. **Visual Model**: PDF, image gibi dataları alıp ana modelin anlayabileceği text haline getirir
- **Web Front-End**: Başlangıçta web, ileride cep telefonu uygulaması
- **API-First**: Tüm backend işlemleri API üzerinden, hem web hem mobil için

## 4. Kullanıcı Yönetimi
- **Çoklu Kullanıcı Destek**: Birden fazlaHasta yönetimi possible
- **Kullanıcı Profili**: Boy, kilo, demografi bilgileri
- **Admin Paneli**: Tamamen ayrı, farklı olarak yönetilir

## 5. Dashboard (Paneli)
- **Akıllı Tasarım**: Kullanıcıyı bilgilendirir ve hatırlatır
- **İstatistikler**: Boy, kilo trendi, tahlil sonuçları
- **Hatırlatmalar**: İlaç hatırlatması, kontrol tarihleri

## 6. Teknostack (Docker'sız)
- **Backend**: Python + FastAPI
- **Python Ortayı**: `venv` (sanal ortam, bağımlılıklar izole)
- **Database (PostgreSQL)**: **Remote** (uzaktan erişilecek, proje dışarıdan bağlanır)
- **Cache (Redis)**: **Remote** (uzaktan erişilecek)
- **Konfigürasyon**: PostgreSQL + Redis bağlantı bilgileri `system_config` tablosundan yönetilir (`.env` YASAK — proje bu servisleri config olarak tüketir)
- **Dosya Depolaması**: Yerel dosya sistemi (/uploads klasörü)
- **Vector Storage**: PostgreSQL + pgvector (RAG için)
## 7. RAG Sistemi (Retrieval-Augmented Generation)
- **Vector Tablosu**: `rag_documents`
- **Ölçeklendirme**: pgvector ile cosine similarity search
- **Embedding Model**: Sentence-Transformers (kendi seçeceğiniz)
- **İş Akışı**: PDF/Resim Upload → Text Extraction → Chunking → Embedding → PostgreSQL Kaydet
- **Dual Data Support**: Kullanıcı özel veriler + Public research data ayrı search
- **Query Pipeline**: User Query → Embedding → Similarity Search → Context Formation → Main LLM → Response

## 8. Module Bileşenleri
1. **Authentication & User Management**: Kayıt, giriş, rol bazlı erişim
2. **Data Ingestion & Visual LLM API**: PDF/image upload → text extraction
3. **Main LLM Engine API**: `/api/chat` endpoint, context injection
4. **Dashboard & Analytics API**: Metrics, trends, export
5. **Admin Panel API (Separate)**: User management, system monitoring
6. **Notification API**: Push/email hatırlatmalar
7. **File Storage API**: Upload, list, delete
8. **Testing & QA**: Unit tests, integration tests

## 9. Öncelik Sırası (MVP için)
1. Authentication + User Profiles + Basal Dashboard
2. Data Ingestion (PDF upload + visual text extraction)
3. Main LLM Engine + Basit cevap sistemi
4. Admin Panel (ayrı deployment)
5. Reminders + Analytics + Refiner Dashboard

## 10. API Endpoint'ler (Özet)
- `POST /api/auth/register` / `login`
- `GET /api/user/dashboard` - metrics + uploads
- `POST /api/upload` - PDF/resim upload
- `POST /api/visual-process` - PDF→text (Visual LLM)
- `POST /api/chat` - Main LLM interaction (RAG included)
- `GET /api/notifications` - bildirim tercihleri
- `GET /admin/api/users` - Admin (separate auth)

## 11. Dağıtım (Docker'sız)
- **Sistem Servisleri**: Linux systemd service ile
- **Günlük Çalıştırma**: `uvicorn app:app --host 0.0.0.0 --port 8000`
- **PostgreSQL (Remote)**: Uzak sunucuda çalışır; uygulama config üzerinden bağlanır, yerel servis başlatılmaz
- **Redis (Remote)**: Uzak sunucuda çalışır; uygulama config üzerinden bağlanır, yerel servis başlatılmaz
- **Backup**: Rutin PostgreSQL yedekleme scriptleri

## 12. Güvenlik ve Uyumluluk
- **Veri Şifrelemesi**: Hassas veriler için PostgreSQL encryption
- **Kullanıcı Veri Ayrımı**: Her kullanıcı verileri isolated
- **Hata Handling**: Medical safety guardrails, yanlış cevap önleme

## 13. Gelecek Gelişmeler (Roadmap)
- Cep telefonu uygulaması (React Native / Flutter)
- GraphQL API (complex dashboards için)
- MinIO self-hosted storage (eğer gerekecekse)
- Advanced medical NLP modülleri

## 14. Son Geliştirmeler (Uygulama Kararları)

Bu bölüm, kodlama sırasında ortaya çıkan ve orijinal planı tamamlayan kararları kaydeder. Kaynak ayrıntılar
`/home/engintalay/.opencode/plan/medicalai/` altındaki bağımsız parçalardadır.

### 14.1 Config kalıcılığı (LLM ayarlarının silinmesi sorunu)
- `database/init_db.py` seed'i `ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value` kullanıyordu.
  Her migration çalıştırmasında admin panelinden kaydedilen LLM/vision/değerler `.env`'deki boş
  varsayılanlarla eziliyordu.
- **Karar:** Seed `ON CONFLICT (key) DO NOTHING` kullanır. Yalnızca eksik anahtarlar eklenir;
  mevcut hiçbir config değeri migration ile değiştirilmez.
- `.env`, DB erişilemediğinde uygulama tarafında *fallback* olarak kalır; yazıcı kaynak değildir.
- Admin panelinden kaydedilen gizli değerler API'de maskelenir ve UI'da boş gösterilir; boş bırakıldığında
  mevcut değer korunur. Arayüzde "Kayıtlı değer var (güvenlik için gösterilmez)" bilgisi gösterilir.

### 14.2 Dosya depolama (04) — tamamlandı
- `routes/uploads.py`: `POST /api/uploads` (+ `/api/upload` alias), `GET /api/uploads`,
  `DELETE /api/uploads/{id}`; MIME/uzantı doğrulama, boyut sınırı (413), UUID isim, `user_id` JWT'den.
- `max_upload_mb` config'i eklendi; `upload_dir` yazılamıyorsa proje içi `uploads/`'a düşülür.
- Başkasının dosyası listelenemez/silemez (404); silme DB kaydı + fiziksel dosyayı birlikte kaldırır.

### 14.3 Admin — kullanıcı bazlı disk kullanım istatistikleri (yeni)
Amaç: yöneticinin dosya depolamayı kullanıcı bazında izlemesi; sağlık metrikleri admin linkinden
kaldırıldığı için depolama tarafının görünürlüğü bu ekranla sağlanır.

- **Endpoint:** `GET /admin/api/uploads/stats` (JWT + `role=admin`).
- **Sayfa:** `/admin/storage` — sidebar'da "💾 Disk Kullanımı".
- **Gösterilecekler:**
  - Özet kartları: toplam dosya, toplam disk kullanımı, dosya yükleyen kullanıcı sayısı, ort. dosya boyutu.
  - Kullanıcı bazlı tablo: e-posta/ad, dosya sayısı, toplam boyut, son yükleme, MIME türü dağılımı.
  - MIME türü bazlı dağılım (PDF / görsel / metin) ve son yüklemeler.
- **Kaynak:** `user_uploads` + `users` (LEFT JOIN); `size_bytes` toplamları, `upload_date` son yükleme.
- **Gizlilik:** yalnızca istatistik; dosya içeriği ve fiziksel yol admin ekranında gösterilmez.

### 14.4 Vision LLM / görselden metin (05) — tamamlandı
- `POST /api/uploads/{id}/extract` → `{text, pages, source, model_used}`.
- `llm_vision_supported=true` → `source="primary_llm"`; `vision_llm_enabled=true` → `source="vision_llm"`.
- **Metin tabanlı PDF'ler stdlib `zlib` ile yerel okunur** (`source="local_pdf"`, LLM çağrısı yok);
  taranan PDF ve görseller vision LLM'e gönderilir. (Not: sunucuda vision yok değil; yalnızca
  `Meta-Llama-3.1-8B-Instruct` modelinde görsel desteği yok. `Ornith-1.5-9B` görselleri okuyor.)
- TXT dosyaları doğrudan okunur (`source="local_text"`). Yeni Python bağımlılığı eklenmedi.
- Kaydedilmemiş API anahtarı istek gövdesiyle kullanılabilir; hata mesajlarında anahtar maskelenir,
  model adı ve dosya yolu loglanmaz.
- **Admin LLM ekranında canlı test:** `POST /admin/api/llm/test` (metin ping'i) ve
  `POST /admin/api/llm/test-vision` (sentetik kırmızı PNG gönderir). İki endpoint de kaydedilmemiş
  form değerleriyle çalışır; scope `primary` veya `vision`. Ana LLM'in görsel destekleyip desteklemediği
  de `test-vision` ile ayrıca sınanabilir. Reasoning modelleri için `max_tokens=256`.

### 14.5 İzleme
- Dashboard'daki LLM durumu `llm_api_key` varlığına göre `configured` hesaplar; gizli anahtar maskeli
  döndüğü için alan boş görünür ama değer korunur. Sağlık metrikleri admin menüsünden geçici olarak
  kaldırıldı; kod ve `/admin/api/health/*` endpoint'leri korundu (08 parçasına taşınacak).

---

**Plan onaylandıktan sonra kodlama başlayacaktır.**