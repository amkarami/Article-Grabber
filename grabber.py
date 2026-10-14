import os
import re
import json
import base64
import requests
from bs4 import BeautifulSoup

TARGET_URL = "https://nashr.majles.ir/"
GAS_WEB_APP_URL = "https://script.google.com/macros/s/AKfycbz0EDuufk9TvKcFRDvpHWP0WbbsCDWsyVgkMFrNinnSh4S3r31PiRNXGHwjtIM1CK7l/exec"
DATA_FILE = "downloaded_articles.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

# کلماتی که نباید به عنوان تیتر اصلی مقاله انتخاب شوند
IGNORE_WORDS = [
    "شماره‌های پیشین نشریه", "مقالات آماده انتشار", "شماره جاری",
    "مقاله پژوهشی", "مقاله ترویجی", "مقاله مروری", "مشاهده مقاله",
    "اصل مقاله", "فایل کلی", "دانلود", "doi", "شناسه دیجیتال"
]

def load_data():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def upload_to_drive(filename, pdf_content):
    try:
        payload = {
            "folderName": "مجلس راهبرد",
            "fileName": filename,
            "mimeType": "application/pdf",
            "fileContent": base64.b64encode(pdf_content).decode("utf-8")
        }
        res = requests.post(GAS_WEB_APP_URL, json=payload, timeout=90)
        if res.status_code == 200:
            result = res.json()
            if result.get("status") == "success":
                return result.get("downloadUrl") or result.get("fileUrl")
    except Exception as e:
        print(f"Error Drive: {e}")
    return None

def extract_real_title(container, fallback):
    """استخراج دقیق عنوان واقعی مقاله و فیلتر کردن عناوین بخش و قالب"""
    for tag in container.find_all(['h5', 'h4', 'h3', 'h2', 'strong', 'a', 'p']):
        text = re.sub(r'\s+', ' ', tag.get_text()).strip()
        # رد کردن تیترهای پیش‌فرض و عبارات اضافه
        if len(text) > 15 and not any(ign in text for ign in IGNORE_WORDS) and not re.search(r'^\d+\.\d{4,9}/', text):
            return text
    return fallback

def main():
    print("بررسی مقالات نشریه...")
    r = requests.get(TARGET_URL, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(r.text, "html.parser")

    current_data = load_data()
    saved_ids = {item["id"] for item in current_data if isinstance(item, dict) and "id" in item}

    doi_tags = soup.find_all("a", href=re.compile(r"doi\.org/10\.", re.I))
    articles = list(current_data)
    updated = False

    for tag in doi_tags:
        doi_url = tag["href"].strip()
        m = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", doi_url)
        article_id = m.group(0) if m else doi_url

        # پیدا کردن کانتینر دربرگیرنده
        parent = tag.parent
        container = None
        for _ in range(4):
            if parent and parent.name in ['li', 'div', 'tr']:
                container = parent
            if parent:
                parent = parent.parent
        if not container:
            container = tag.parent

        # اصلاح خط اول: عنوان واقعی مقاله
        real_title = extract_real_title(container, fallback=f"مقاله {article_id}")

        # اگر قبلاً ذخیره شده، فقط عنوانش را در صورت نیاز اصلاح می‌کنیم
        existing = next((item for item in articles if item.get("id") == article_id), None)
        if existing:
            if existing.get("title") != real_title and not any(ign in real_title for ign in IGNORE_WORDS):
                existing["title"] = real_title
                updated = True
            continue

        # مقاله جدید: دانلود و ارسال به گوگل درایو
        pdf_url = ""
        for a in container.find_all("a", href=True):
            href = a["href"].strip()
            if ".pdf" in href.lower() or "download" in href.lower():
                pdf_source = requests.compat.urljoin(TARGET_URL, href)
                try:
                    res_pdf = requests.get(pdf_source, headers=HEADERS, timeout=45)
                    if res_pdf.status_code == 200 and len(res_pdf.content) > 3000:
                        safe_name = re.sub(r'[\\/*?:"<>|]', "", real_title)[:60] + ".pdf"
                        pdf_url = upload_to_drive(safe_name, res_pdf.content)
                except Exception:
                    pass
                break

        articles.append({
            "id": article_id,
            "title": real_title,
            "doi_url": doi_url,
            "pdf_url": pdf_url or doi_url
        })
        updated = True

    if updated:
        save_data(articles)
        print("اطلاعات و عناوین با موفقیت اصلاح شدند.")
    else:
        print("تغییری لازم نبود.")

if __name__ == "__main__":
    main()
