# routines/health.py - HealthMetrics Business Logic (psycopg2)

import psycopg2
from psycopg2.extras import RealDictCursor
from typing import Optional, List, Tuple
from datetime import datetime


def get_db_connection(config: dict) -> psycopg2.connection:
    """psycopg2 bağlantısı açar (config loader'dan okunan DB ayarlarıyla)."""
    return psycopg2.connect(
        host=config.get('db_host', 'localhost'),
        port=int(config.get('db_port', '5432')),
        dbname=config.get('db_name', 'medical_ai'),
        user=config.get('db_user', 'medical_user'),
        password=config.get('db_password', ''),
    )


def create_health_metric(
    conn: psycopg2.connection,
    user_id: int,
    metric_name: str,
    value: float,
    unit: str,
    recorded_at: Optional[datetime] = None
) -> int:
    """Yeni bir health metric ekler.

    Args:
        conn: Veritabanı bağlantısı
        user_id: Kullanıcı ID'si
        metric_name: Metrik adı (örn: 'weight', 'height')
        value: Metrik değeri
        unit: Birim (örn: 'kg', 'cm')
        recorded_at: Kayıt zamanı (varsayılan: şimdi)

    Returns:
        Oluşturulan metric_id
    """
    if recorded_at is None:
        recorded_at = datetime.now()

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            INSERT INTO health_metrics (user_id, metric_name, value, unit, recorded_at)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING metric_id
        """, (user_id, metric_name, value, unit, recorded_at))
        metric_id = cur.fetchone()['metric_id']
    conn.commit()
    return metric_id


def get_health_metrics(
    conn: psycopg2.connection,
    user_id: int,
    metric_name: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> Tuple[List[dict], int]:
    """Kullanıcının health metric'lerini listeler.

    Args:
        conn: Veritabanı bağlantısı
        user_id: Kullanıcı ID'si
        metric_name: Metrik adına göre filtre (isteğe bağlı)
        limit: Maksimum sonuç sayısı
        offset: Sayfalama offset'i

    Returns:
        (metric listesi, toplam sayı)
    """
    # Toplam sayı için parametrik COUNT sorgusu
    count_conditions = ["user_id = %s"]
    if metric_name:
        count_conditions.append("metric_name = %s")
    count_query = "SELECT COUNT(*) AS count FROM health_metrics WHERE " + " AND ".join(count_conditions)
    count_params = [user_id]
    if metric_name:
        count_params.append(metric_name)

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(count_query, count_params)
        total = cur.fetchone()['count']

    # Veriler için parametrik LIMIT/OFFSET (SQL injection riski yok)
    metrics_query = "SELECT metric_id, user_id, metric_name, value, unit, recorded_at " \
                    "FROM health_metrics " \
                    "WHERE user_id = %s"
    if metric_name:
        metrics_query += " AND metric_name = %s"
    metrics_query += " ORDER BY recorded_at DESC LIMIT %s OFFSET %s"
    metrics_params = [user_id]
    if metric_name:
        metrics_params.append(metric_name)
    metrics_params.extend([limit, offset])

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(metrics_query, metrics_params)
        rows = cur.fetchall()

    return [dict(row) for row in rows], total


def get_health_metric_by_id(
    conn: psycopg2.connection,
    metric_id: int,
    user_id: int
) -> Optional[dict]:
    """ID'sine göre tek bir metric getirir (kullanıcı sahiplik kontrolü).

    Returns:
        Metric verisi ya da None
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            SELECT metric_id, user_id, metric_name, value, unit, recorded_at
            FROM health_metrics
            WHERE metric_id = %s AND user_id = %s
        """, (metric_id, user_id))
        row = cur.fetchone()
        return dict(row) if row else None


def update_health_metric(
    conn: psycopg2.connection,
    metric_id: int,
    user_id: int,
    metric_name: Optional[str] = None,
    value: Optional[float] = None,
    unit: Optional[str] = None,
    recorded_at: Optional[datetime] = None
) -> bool:
    """Health metric günceller (kullanıcı sahiplik kontrolü).

    Returns:
        Güncelleme yapıldıysa True, değilse False
    """
    updates = []
    values = []

    if metric_name is not None:
        updates.append("metric_name = %s")
        values.append(metric_name)

    if value is not None:
        updates.append("value = %s")
        values.append(value)

    if unit is not None:
        updates.append("unit = %s")
        values.append(unit)

    if recorded_at is not None:
        updates.append("recorded_at = %s")
        values.append(recorded_at)

    # Değiştirilecek hiçbir alan yoksa güncelleme yapılmaz
    if not updates:
        return False

    values.append(metric_id)
    values.append(user_id)

    # WHERE kolonları parametrik (SQL injection riski yok)
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(
            f"UPDATE health_metrics SET {', '.join(updates)} "
            f"WHERE metric_id = %s AND user_id = %s",
            tuple(values)
        )
        updated = cur.rowcount == 1
    conn.commit()
    return updated


def delete_health_metric(
    conn: psycopg2.connection,
    metric_id: int,
    user_id: int
) -> bool:
    """Health metric siler (kullanıcı sahiplik kontrolü).

    Returns:
        Silindiysa True, değilse False
    """
    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute("""
            DELETE FROM health_metrics
            WHERE metric_id = %s AND user_id = %s
        """, (metric_id, user_id))
        deleted = cur.rowcount == 1
    conn.commit()
    return deleted


def get_health_stats(
    conn: psycopg2.connection,
    user_id: int,
    metric_name: Optional[str] = None,
    days: int = 30
) -> dict:
    """Belirli bir süre içindeki health metric istatistiklerini hesaplar.

    Returns:
        count, avg_value, min_value, max_value içeren sözlük
    """
    conditions = ["user_id = %s", "recorded_at >= NOW() - (%s || ' days')::interval"]
    values = [user_id, str(days)]

    if metric_name:
        conditions.append("metric_name = %s")
        values.append(metric_name)

    query = (
        "SELECT COUNT(*) AS count, AVG(value) AS avg_value, "
        "MIN(value) AS min_value, MAX(value) AS max_value "
        "FROM health_metrics WHERE " + " AND ".join(conditions)
    )

    with conn.cursor(cursor_factory=RealDictCursor) as cur:
        cur.execute(query, tuple(values))
        row = cur.fetchone()

    return {
        "count": row['count'] or 0,
        "avg_value": float(row['avg_value']) if row['avg_value'] is not None else None,
        "min_value": float(row['min_value']) if row['min_value'] is not None else None,
        "max_value": float(row['max_value']) if row['max_value'] is not None else None,
    }
