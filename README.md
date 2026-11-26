# Medical AI

FastAPI tabanlı; admin yönetimi, hasta paneli, RAG destekli sağlık sohbeti,
görsel/PDF metin çıkarma ve sağlık metriği yönetimi sunan uygulama.

## Özellikler

- **Admin paneli:** kullanıcı oluşturma/aktiflik, sistem config, LLM ayarları,
  sağlık metrikleri, public RAG bilgi tabanı ve araştırma/içerik yönetimi.
- **Hasta paneli:** dashboard, ölçüm tarihli metrikler, arama/filtre/çoklu silme,
  dosya yükleme ve önizleme, hatırlatmalar, profil ve kişisel RAG.
- **Sohbet:** dosya ekleme/sürükle-bırak, vision ile okuma, otomatik ölçüm kaydı,
  sohbet arama, arşivleme ve silme.
- **RAG içe aktarma:** metin, PDF/TXT, `prospektus.co` ilaç URL’si ve ilaç arama/seçim.
- **Güvenlik:** ayrı admin/hasta JWT rolleri, bcrypt, kullanıcı sahiplik kontrolleri,
  gizli anahtar maskeleme ve tıbbi guardrail.

## Çalıştırma

```bash
./install.sh
python database/init_db.py
./run.sh
```

- Admin: <http://localhost:8000/admin>
- Hasta: <http://localhost:8000/patient>
- API dokümantasyonu: <http://localhost:8000/docs>
- Sağlık kontrolü: <http://localhost:8000/health>

```bash
./restart.sh
./stop.sh
python -m pytest tests -q
```

## Yapılandırma

Bootstrap sırasında `ENV` / `.env` kullanılır; çalışma zamanında
`system_config` tablosundaki değerler admin panelinden yönetilir.

Önemli anahtarlar:

- `llm_provider`, `llm_base_url`, `llm_model`, `llm_api_key`
- `llm_max_tokens`, `llm_timeout`, `llm_thinking` (Admin → LLM Ayarları → Advanced)
- `vision_llm_*`, `vision_max_tokens`, `vision_timeout`
- `embedding_model`, `rag_top_k`, `rag_chunk_size`, `rag_overlap`
- `db_*`, `redis_*`, `max_upload_mb`, `upload_dir`

## Model ve içerik referansları

- **Google MedGemma Release koleksiyonu:**  
  <https://huggingface.co/collections/google/medgemma-release>
- **İlaç prospektüsleri:**  
  <https://prospektus.co/>

## Dokümanlar

- Güncel uygulama/operasyon raporu: [`FAZ0_SON_DURUM_RAPORU.md`](FAZ0_SON_DURUM_RAPORU.md)
- API test koleksiyonu: [`POSTMAN_COLLECTION.json`](POSTMAN_COLLECTION.json)
