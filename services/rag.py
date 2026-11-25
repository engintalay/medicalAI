# services/rag.py — 06 parçası: chunking + yerel Sentence-Transformers embedding
#
# Kural: API /embeddings çağrısı YOK. Model süreç başına bir kez yüklenir,
# CPU kullanılır ve vektörler JSONB olarak saklanır (pgvector yok).

import json
import threading
from typing import Any, List, Optional

from config.loader import get_config_loader

_config = get_config_loader()

DEFAULT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

_model = None
_model_name = None
_model_lock = threading.Lock()
_model_load_count = 0


def model_name() -> str:
    """Config'deki embedding model adı (varsayılan: çok dilli, 384 boyut)."""
    return str(_config.get("embedding_model", DEFAULT_MODEL) or DEFAULT_MODEL)


def get_model():
    """SentenceTransformer'ı süreç başına bir kez yükler ve cache'ler."""
    global _model, _model_name, _model_load_count
    name = model_name()
    if _model is None or _model_name != name:
        with _model_lock:
            if _model is None or _model_name != name:
                from sentence_transformers import SentenceTransformer

                _model = SentenceTransformer(name, device="cpu")
                _model_name = name
                _model_load_count += 1
    return _model


def load_count() -> int:
    """Testler için model yükleme sayacı (1 kalmalı)."""
    return _model_load_count


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> List[str]:
    """Metni sabit boyutlu, örtüşmeli parçalara böler."""
    text = (text or "").strip()
    if not text:
        return []
    size = max(50, int(chunk_size))
    ov = max(0, min(int(overlap), size - 1))
    step = size - ov
    chunks: List[str] = []
    start = 0
    length = len(text)
    while start < length:
        part = text[start:start + size].strip()
        if part:
            chunks.append(part)
        if start + size >= length:
            break
        start += step
    return chunks


def embed_texts(texts: List[str]) -> List[List[float]]:
    """Normalize edilmiş embedding vektörleri üretir (cosine = dot product)."""
    if not texts:
        return []
    model = get_model()
    vectors = model.encode(
        list(texts),
        normalize_embeddings=True,
        show_progress_bar=False,
        convert_to_numpy=True,
        batch_size=32,
    )
    return [[float(x) for x in vec] for vec in vectors]


def dimensions() -> int:
    return int(get_model().get_sentence_embedding_dimension())


def vector_payload(values: List[float]) -> str:
    """JSONB content_vector alanına yazılacak değer."""
    return json.dumps({"model": _model_name or model_name(), "values": values})


def vector_values(raw: Any) -> List[float]:
    """JSONB (veya JSON string) vektörden float listesi çıkarır."""
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (ValueError, TypeError):
            return []
    if isinstance(raw, dict):
        raw = raw.get("values") or []
    if not isinstance(raw, (list, tuple)):
        return []
    out = []
    for item in raw:
        try:
            out.append(float(item))
        except (TypeError, ValueError):
            continue
    return out


def _score(a: List[float], b: List[float]) -> float:
    """Normalize vektörler için cosine skoru (dot product)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    return sum(x * y for x, y in zip(a, b))


def ingest(
    conn,
    user_id: Optional[int],
    source: str,
    text: str,
    chunk_size: int = 800,
    overlap: int = 100,
    metadata: Optional[dict] = None,
) -> dict:
    """Aynı source için eski parçaları siler, yeni parçaları yazar.

    Commit caller'a aittir; embedding hatasında hiçbir DB yazısı yapılmaz.
    """
    source = (source or "").strip()
    if not source:
        raise ValueError("source boş olamaz")
    chunks = chunk_text(text, chunk_size, overlap)
    if not chunks:
        raise ValueError("Metin boş")

    # DB yazılarından ÖNCE embedding: hata olursa transaction temiz kalır.
    vectors = embed_texts(chunks)
    payloads = [vector_payload(vec) for vec in vectors]
    used_model = _model_name or model_name()
    meta_base = dict(metadata or {})

    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM rag_documents WHERE source_type = %s "
            "AND user_id IS NOT DISTINCT FROM %s",
            (source, user_id),
        )
        for idx, (content, payload) in enumerate(zip(chunks, payloads)):
            meta = dict(meta_base)
            meta.update({"chunk_index": idx, "model": used_model})
            cur.execute(
                """
                INSERT INTO rag_documents
                    (user_id, source_type, content, content_vector, metadata)
                VALUES (%s, %s, %s, %s::jsonb, %s::jsonb)
                """,
                (user_id, source, content, payload, json.dumps(meta)),
            )
    return {
        "chunks": len(chunks),
        "model": used_model,
        "dimensions": len(vectors[0]) if vectors else 0,
    }


def search(
    conn,
    user_id: int,
    query: str,
    top_k: int = 5,
    threshold: float = 0.25,
) -> List[dict]:
    """Kullanıcının özel + public parçalarında arama yapar.

    Public kayıtlar user_id=NULL ile saklanır ve herkese açıktır (13 parçası).
    """
    query = (query or "").strip()
    if not query:
        return []
    qvec = embed_texts([query])[0]

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT doc_id, source_type, content, content_vector, metadata
            FROM rag_documents
            WHERE user_id = %s OR user_id IS NULL
            """,
            (int(user_id),),
        )
        rows = cur.fetchall()

    results = []
    for doc_id, source, content, raw_vec, meta in rows:
        score = _score(qvec, vector_values(raw_vec))
        if score < threshold:
            continue
        results.append({
            "id": doc_id,
            "source": source,
            "content": content,
            "score": round(score, 4),
            "metadata": meta if isinstance(meta, dict) else {},
        })
    results.sort(key=lambda item: item["score"], reverse=True)
    try:
        top_k = max(1, min(int(top_k), 50))
    except (TypeError, ValueError):
        top_k = 5
    return results[:top_k]


def delete_source(conn, source: str, user_id: Optional[int] = None) -> int:
    """Belirli bir source'a ait parçaları siler; silinen satır sayısını döner."""
    with conn.cursor() as cur:
        if user_id is None:
            cur.execute("DELETE FROM rag_documents WHERE source_type = %s", (source,))
        else:
            cur.execute(
                "DELETE FROM rag_documents WHERE source_type = %s AND user_id = %s",
                (source, int(user_id)),
            )
        return int(cur.rowcount or 0)
