"""prospektus.co ilaç bilgisi arama ve URL içerik çekme adaptörü.

Yalnızca prospektus.co / www.prospektus.co kabul edilir; yönlendirmeler de
doğrulanır. HTML etiketleri temizlenip RAG için okunabilir metin üretilir.
"""

import re
from html import unescape
from urllib.parse import quote, urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from bs4 import BeautifulSoup

ALLOWED_HOSTS = {"prospektus.co", "www.prospektus.co"}
BASE_URL = "https://prospektus.co"
MAX_BYTES = 2 * 1024 * 1024
USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 MedicalAI/1.0"


class WebImportError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.status_code = status_code


def _validate_url(url: str):
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise WebImportError("Geçerli bir http(s) URL girin.")
    if parsed.username or parsed.password:
        raise WebImportError("URL içinde kullanıcı adı/şifre kabul edilmez.")
    host = parsed.hostname.lower().rstrip(".")
    if host not in ALLOWED_HOSTS:
        raise WebImportError("Şu an yalnızca prospektus.co adresleri destekleniyor.")


class _SafeRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urljoin(req.full_url, newurl)
        _validate_url(target)
        return super().redirect_request(req, fp, code, msg, headers, target)


def _get(url: str) -> tuple[bytes, str]:
    _validate_url(url)
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
    opener = build_opener(_SafeRedirectHandler())
    try:
        with opener.open(request, timeout=30) as response:
            content_type = (response.headers.get("Content-Type") or "").split(";")[0].lower()
            if content_type != "text/html":
                raise WebImportError("URL metin/html içeriği döndürmedi.", 422)
            data = response.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise WebImportError("URL içeriği 2 MB sınırını aşıyor.", 413)
            return data, response.url
    except WebImportError:
        raise
    except Exception as exc:
        raise WebImportError("Sayfa çekilemedi: " + str(exc)[:160], 502)


def _clean_lines(text: str) -> str:
    lines = []
    seen = set()
    for raw in text.splitlines():
        line = re.sub(r"\s+", " ", unescape(raw)).strip()
        if not line or line in seen:
            continue
        seen.add(line)
        lines.append(line)
    return "\n".join(lines)


def fetch_url_text(url: str) -> dict:
    """İlaç sayfasını çekip başlık + temiz metin + kaynak URL döndürür."""
    data, final_url = _get(url)
    soup = BeautifulSoup(data.decode("utf-8", errors="replace"), "html.parser")
    for tag in soup(["script", "style", "noscript", "svg", "form", "nav", "footer"]):
        tag.decompose()
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = _clean_lines(main.get_text("\n", strip=True))
    if len(text) < 80:
        raise WebImportError("Sayfadan yeterli ilaç bilgisi çıkarılamadı.", 422)
    text = text[:200000]
    return {"title": title, "text": text, "url": final_url, "characters": len(text)}


def search_drugs(query: str, limit: int = 20) -> list:
    """prospektus.co arama sayfasından ilaç başlık/URL listesi döndürür."""
    query = (query or "").strip()
    if len(query) < 2:
        raise WebImportError("İlaç adı en az 2 karakter olmalı.")
    if len(query) > 100:
        raise WebImportError("Arama ifadesi en fazla 100 karakter olabilir.")
    url = BASE_URL + "/arama?q=" + quote(query)
    data, _final_url = _get(url)
    soup = BeautifulSoup(data.decode("utf-8", errors="replace"), "html.parser")
    results = []
    seen = set()
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if "/ilaclar/" not in href:
            continue
        absolute = urljoin(BASE_URL, href)
        parsed = urlparse(absolute)
        if parsed.hostname not in ALLOWED_HOSTS or absolute in seen:
            continue
        title = re.sub(r"\s+", " ", anchor.get_text(" ", strip=True)).strip()
        if not title:
            continue
        seen.add(absolute)
        results.append({"title": title, "url": absolute})
        if len(results) >= max(1, min(int(limit), 50)):
            break
    return results
