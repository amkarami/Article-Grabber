import os
import re
import json
import time
import hashlib
import requests
from bs4 import BeautifulSoup

TARGET_URL = "https://nashr.majles.ir/"
DATA_FILE = "downloaded_articles.json"
GOOGLE_SCRIPT_URL = "https://script.google.com/macros/s/AKfycbz0EDuufk9TvKcFRDvpHWP0WbbsCDWsyVgkMFrNinnSh4S3r31PiRNXGHwjtIM1CK7l/exec"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0 Safari/537.36"
}

IGNORE_PHRASES = [
    "مقالات آماده انتشار",
    "شماره جاری",
    "شماره‌های پیشین نشریه",
    "شماره های پیشین نشریه",
    "مقاله پژوهشی",
    "مقاله ترویجی",
    "مقاله مروری",
    "مشاهده مقاله",
    "اصل مقاله",
    "فایل کلی مقالات این شماره",
    "فایل کلی مقالات",
    "جستجو",
    "جستجوی پیشرفته",
    "شناسنامه نشریه",
    "بانک ها و نمایه نامه ها",
    "بانک‌ها و نمایه‌نامه‌ها",
]

def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = text.replace("\u200c", " ")
    text = text.replace("\xa0", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text

def is_probable_doi(text: str) -> bool:
    if not text:
        return False
    return bool(re.search(r"10\.\d{4,9}/\S+", text))

def is_bad_title(text: str) -> bool:
    t = normalize_text(text)
    if not t:
        return True
    if len(t) < 8:
        return True
    if any(x in t for x in IGNORE_PHRASES):
        return True
    if is_probable_doi(t):
        return True
    if t.startswith("صفحه"):
        return True
    if re.fullmatch(r"\d+(\.\d+)?\s*[Mm]", t):
        return True
    if re.fullmatch(r"[0-9\-– ]+", t):
        return True
    return False

def sanitize_filename(name: str, max_len: int = 120) -> str:
    name = normalize_text(name)
    name = re.sub(r'[\\/*?:"<>|]', "", name)
    name = name.strip(" .")
    if len(name) > max_len:
        name = name[:max_len].rstrip()
    return name or "article"

def load_existing_data():
    if not os.path.exists(DATA_FILE):
        return []
    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def extract_article_id(doi_url: str) -> str:
    m = re.search(r"(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)", doi_url or "")
    return m.group(1) if m else doi_url

def absolute_url(url: str) -> str:
    return requests.compat.urljoin(TARGET_URL, url)

def get_soup(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=HEADERS, timeout=60)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")

def find_article_blocks(soup: BeautifulSoup):
    """
    در صفحه اصلی، هر مقاله عملاً در توالی‌ای از عناصر آمده:
    عنوان، صفحه، DOI، نویسندگان، مشاهده/اصل مقاله
    ما از روی DOIها کار می‌کنیم و برای هر DOI نزدیک‌ترین بلوک والد را بررسی می‌کنیم.
    """
    doi_links = soup.find_all("a", href=re.compile(r"doi\.org/10\.", re.I))
    return doi_links

def extract_title_near_doi_anchor(doi_tag) -> str:
    """
    عنوان واقعی همان مقاله را از اطراف تگ DOI پیدا می‌کند،
    نه اولین عنوان صفحه.
    """
    # 1) اول در والد‌های نزدیک بگرد
    parent_candidates = []
    p = doi_tag
    for _ in range(6):
        p = p.parent
        if not p:
            break
        parent_candidates.append(p)

    for container in parent_candidates:
        found = []
        for el in container.find_all(["h1", "h2", "h3", "h4", "h5", "strong", "p", "div", "span"], recursive=True):
            txt = normalize_text(el.get_text(" ", strip=True))
            if is_bad_title(txt):
                continue
            found.append(txt)

        # حذف موارد تکراری
        unique_found = []
        for item in found:
            if item not in unique_found:
                unique_found.append(item)

        # معمولاً اولین متن خوب یا بلندترین متن خوب عنوان است
        if unique_found:
            # اولویت با متن‌های بلندتر ولی نه خیلی غیرعادی
            ranked = sorted(unique_found, key=lambda x: len(x), reverse=True)
            for item in ranked:
                if len(item) >= 15:
                    return item
            return unique_found[0]

    # 2) اگر نشد، به عقب در سند حرکت کن
    for el in doi_tag.previous_elements:
        if isinstance(el, str):
            txt = normalize_text(el)
            if not is_bad_title(txt):
                return txt

    return ""

def extract_pdf_url_near_doi(doi_tag) -> str:
    """
    نزدیک‌ترین لینک PDF مربوط به همین مقاله را پیدا می‌کند.
    """
    # در والد‌های نزدیک بگرد
    parent_candidates = []
    p = doi_tag
    for _ in range(6):
        p = p.parent
        if not p:
            break
        parent_candidates.append(p)

    for container in parent_candidates:
        links = container.find_all("a", href=True)
        for a in links:
            href = a["href"].strip()
            text = normalize_text(a.get_text(" ", strip=True))

            if ".pdf" in href.lower():
                return absolute_url(href)

            if "اصل مقاله" in text:
                return absolute_url(href)

            if "download" in href.lower():
                return absolute_url(href)

    # اگر در همین بلوک پیدا نشد، بین لینک‌های بعدی نزدیک جستجو کن
    next_anchors = doi_tag.find_all_next("a", href=True, limit=12)
    for a in next_anchors:
        href = a["href"].strip()
        text = normalize_text(a.get_text(" ", strip=True))

        if ".pdf" in href.lower():
            return absolute_url(href)
        if "اصل مقاله" in text:
            return absolute_url(href)

    return ""

def download_pdf(pdf_url: str) -> bytes:
    r = requests.get(pdf_url, headers=HEADERS, timeout=90)
    r.raise_for_status()

    content_type = r.headers.get("Content-Type", "").lower()
    content = r.content

    # گاهی هدر اشتباه است ولی فایل PDF واقعی است
    if content.startswith(b"%PDF"):
        return content

    if "pdf" in content_type:
        return content

    raise ValueError(f"Downloaded content is not a valid PDF: {pdf_url}")

def upload_to_google_drive(file_name: str, file_bytes: bytes, article_id: str = "", doi_url: str = "") -> str:
    """
    فایل را به وب‌اپ Google Apps Script می‌فرستد.
    انتظار داریم Apps Script یک JSON برگرداند که یکی از این‌ها را داشته باشد:
    downloadUrl / fileUrl / url
    """
    files = {
        "file": (file_name, file_bytes, "application/pdf")
    }
    data = {
        "folderName": "مجلس راهبرد",
        "fileName": file_name,
        "articleId": article_id,
        "doiUrl": doi_url
    }

    r = requests.post(GOOGLE_SCRIPT_URL, data=data, files=files, timeout=180)
    r.raise_for_status()

    text = r.text.strip()

    try:
        result = r.json()
    except Exception:
        # اگر پاسخ JSON نبود، خطا را واضح نشان بده
        raise ValueError(f"Google Script response is not valid JSON: {text[:500]}")

    if not isinstance(result, dict):
        raise ValueError(f"Unexpected Google Script response: {result}")

    for key in ["downloadUrl", "fileUrl", "url"]:
        if result.get(key):
            return result[key]

    if result.get("success") is False:
        raise ValueError(f"Upload failed: {result}")

    raise ValueError(f"No usable file URL returned from Google Script: {result}")

def build_articles():
    soup = get_soup(TARGET_URL)
    doi_links = find_article_blocks(soup)

    articles = []
    seen_ids = set()

    for doi_tag in doi_links:
        doi_url = normalize_text(doi_tag.get("href", ""))
        if not doi_url:
            continue

        article_id = extract_article_id(doi_url)
        if not article_id or article_id in seen_ids:
            continue

        title = extract_title_near_doi_anchor(doi_tag)
        if not title:
            title = f"مقاله {article_id}"

        pdf_source_url = extract_pdf_url_near_doi(doi_tag)

        articles.append({
            "id": article_id,
            "title": title,
            "doi_url": doi_url,
            "pdf_source_url": pdf_source_url
        })
        seen_ids.add(article_id)

    return articles

def merge_with_existing(new_items, old_items):
    """
    اگر قبلاً مقاله‌ای آپلود شده و pdf_url معتبر دارد،
    بیهوده دوباره آپلود نکن.
    """
    old_map = {item.get("id"): item for item in old_items if item.get("id")}
    merged = []

    for item in new_items:
        old = old_map.get(item["id"])
        if old and old.get("pdf_url"):
            merged.append({
                "id": item["id"],
                "title": item["title"],
                "doi_url": item["doi_url"],
                "pdf_url": old["pdf_url"]
            })
        else:
            merged.append({
                "id": item["id"],
                "title": item["title"],
                "doi_url": item["doi_url"],
                "pdf_url": ""
            })

    return merged

def process_articles():
    old_data = load_existing_data()
    fresh_articles = build_articles()
    merged_articles = merge_with_existing(fresh_articles, old_data)

    # نقشه برای دسترسی به pdf_source_url
    source_map = {item["id"]: item.get("pdf_source_url", "") for item in fresh_articles}

    changed = False

    for item in merged_articles:
        if item.get("pdf_url"):
            continue

        article_id = item["id"]
        title = item["title"]
        doi_url = item["doi_url"]
        pdf_source_url = source_map.get(article_id, "")

        print(f"\nProcessing article: {title}")
        print(f"DOI: {doi_url}")
        print(f"PDF source: {pdf_source_url or 'NOT FOUND'}")

        if not pdf_source_url:
            print(" -> PDF source URL not found, skipping upload.")
            # برای اینکه لینک خالی نماند، موقتاً DOI را بگذار
            item["pdf_url"] = doi_url
            changed = True
            continue

        try:
            pdf_bytes = download_pdf(pdf_source_url)
            safe_name = sanitize_filename(title, 100)
            file_name = f"{safe_name}.pdf"

            drive_url = upload_to_google_drive(
                file_name=file_name,
                file_bytes=pdf_bytes,
                article_id=article_id,
                doi_url=doi_url
            )

            item["pdf_url"] = drive_url
            changed = True
            print(f" -> Uploaded to Google Drive: {drive_url}")

            # برای جلوگیری از فشار زیاد روی سرورها
            time.sleep(2)

        except Exception as e:
            print(f" -> Upload/download failed: {e}")
            # اگر آپلود نشد، فعلاً DOI را نگه می‌داریم تا لینک خراب نباشد
            item["pdf_url"] = doi_url
            changed = True

    if changed or not os.path.exists(DATA_FILE):
        save_data(merged_articles)
        print(f"\nSaved {len(merged_articles)} articles to {DATA_FILE}")
    else:
        print("\nNo changes detected.")

def main():
    try:
        process_articles()
    except Exception as e:
        print("Fatal error:", e)
        raise

if __name__ == "__main__":
    main()
