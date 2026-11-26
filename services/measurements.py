"""Yüklenen belge metninden yaygın sağlık ölçümlerini çıkarır.

Kural tabanlıdır: LLM görseli okuyup metni çıkarır; bu modül metindeki
sayıları doğrular ve health_metrics şemasına uygun normalize eder.
"""

import re


def _to_float(value: str) -> float:
    return float(str(value).strip().replace(",", "."))


def _valid(value: float, low: float, high: float) -> bool:
    return low <= value <= high


def extract_measurements(text: str) -> list:
    """Metinden güvenli aralıktaki ölçümleri döndürür.

    Dönen kayıtlar: {"name": str, "value": float, "unit": str}
    Yalnızca ilk eşleşen değer alınır; aynı metrik tekrar eklenmez.
    """
    raw = (text or "").replace("\u00a0", " ")
    items = []
    seen = set()

    def add(name, value, unit, low, high):
        try:
            number = _to_float(value)
        except (TypeError, ValueError):
            return
        if name in seen or not _valid(number, low, high):
            return
        seen.add(name)
        items.append({"name": name, "value": round(number, 2), "unit": unit})

    # 128/82, 128 / 82 mmHg
    bp = re.search(r"(?<!\d)(\d{2,3})\s*[/\\]\s*(\d{2,3})(?!\d)", raw, re.I)
    if bp:
        systolic, diastolic = _to_float(bp.group(1)), _to_float(bp.group(2))
        if _valid(systolic, 70, 250) and _valid(diastolic, 40, 150) and systolic > diastolic:
            add("sistolik", systolic, "mmHg", 70, 250)
            add("diyastolik", diastolic, "mmHg", 40, 150)

    # Sistolik 128, diyastolik 82
    if "sistolik" not in seen:
        systolic = re.search(
            r"(?:sistolik|sistol|büyük|buyuk|üst tansiyon|ust tansiyon)[^\d]{0,18}(\d{2,3})",
            raw, re.I,
        )
        diastolic = re.search(
            r"(?:diyastolik|diyastol|küçük|kucuk|alt tansiyon)[^\d]{0,18}(\d{2,3})",
            raw, re.I,
        )
        if systolic and diastolic:
            sys_value, dia_value = _to_float(systolic.group(1)), _to_float(diastolic.group(1))
            if (_valid(sys_value, 70, 250) and _valid(dia_value, 40, 150)
                    and sys_value > dia_value):
                add("sistolik", sys_value, "mmHg", 70, 250)
                add("diyastolik", dia_value, "mmHg", 40, 150)

    pulse = re.search(
        r"(?:nab[ıi]z|pulse|kalp at[ıi]m[ıi]?|bpm)[^\d]{0,18}(\d{2,3})", raw, re.I
    ) or re.search(r"(?<!\d)(\d{2,3})\s*(?:bpm|at[ıi]m\s*/\s*dk)(?!\w)", raw, re.I)
    if pulse:
        add("nabız", pulse.group(1), "bpm", 30, 220)

    weight = re.search(
        r"(?:kilo|a[ğg][ıi]rl[ıi]k|weight)[^\d]{0,18}(\d{2,3}(?:[.,]\d{1,2})?)\s*(?:kg)?",
        raw, re.I,
    )
    if weight:
        add("weight", weight.group(1), "kg", 20, 350)

    glucose = re.search(
        r"(?:kan [şs]ekeri|glukoz|glucose)[^\d]{0,22}(\d{2,3}(?:[.,]\d{1,2})?)\s*(?:mg\s*/\s*d[lL])?",
        raw, re.I,
    )
    if glucose:
        add("glucose", glucose.group(1), "mg/dL", 20, 600)

    temperature = re.search(
        r"(?:s[ıi]cakl[ıi][kğg][ıi]?|ate[şs]|temperature)[^\d]{0,18}(\d{2}(?:[.,]\d{1,2})?)\s*°?\s*[cC]?",
        raw, re.I,
    )
    if temperature:
        add("temperature", temperature.group(1), "°C", 30, 45)

    spo2 = re.search(
        r"(?:spo\s*2|oksijen saturasyonu|oksijen doygunlu[ğg]u|o2 saturasyon)[^\d]{0,22}(\d{2,3})\s*%?",
        raw, re.I,
    )
    if spo2:
        add("spo2", spo2.group(1), "%", 50, 100)

    return items
