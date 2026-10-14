import os
import re
import json
import base64
import requests
from bs4 import BeautifulSoup

TARGET_URL = "https://nashr.majles.ir/"
# همان وب‌اپلیکیشن گوگل اپس اسکریپت شما
GAS_WEB_APP_URL = "https://script.google.com/macros/s/AKfycbz0EDuufk9TvKcFRDvpHWP0WbbsCDWsyVgkMFrNinnSh4S3r31PiRNXGHwjtIM1CK7l/exec"
DATA_FILE = "downloaded_articles.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
}

IGNORE_WORDS = [
    "شماره‌های پیشین نشریه", "مقالات آماده انتشار", "شماره جاری",
    "مقاله پژوهشی", "مقاله ترویجی", "مقاله مروری", "مشاهده مقاله",
    "اصل مقاله", "فایل کلی", "دانلود", "doi"
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

def upload_to_google_drive(filename, pdf_content):
    """ارسال مستقیم فایل به اکانت گوگل درایو و دریافت لینک دانلود از درایو"""
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
                # لینک فایل در گوگل درایو
                return result.get("downloadUrl") or result.get("fileUrl")
    except Exception as e:
        print(f"Error uploading to Drive: {e}")
    return None

def clean_title(container, fallback_id):
    for tag in container.find_all(['h5', 'h4', 'h3', 'strong', 'p', 'a', 'span']):
        txt = re.sub(r'\s+', ' ', tag.get_text()).strip()
        if len(txt) > 15 and not any(ign in txt for ign in IGNORE_WORDS) and not re.search(r'^\d+\.\d{4,9}/', txt):
            return txt
    return f"مقاله {fallback_id}"

def main():
    print("در حال دریافت اطلاعات از نشریه مجلس...")
    r = requests.get(TARGET_URL, headers=HEADERS, timeout=30)
    soup = BeautifulSoup(r.text, "html.parser")

    current_data = load_data()
    saved_ids = {item["id"] for item in current_data if isinstance(item, dict) and "id" in item}
    
    doi_tags = soup.find_all("a", href=re.compile(r"doi\.org/10\.", re.I))
    new_articles = []

    for tag in doi_tags:
        doi_url = tag["href"].strip()
        m = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", doi_url)
        article_id = m.group(0) if m else doi_url

        # کانتینر دربرگیرنده مقاله
        parent = tag.parent
        container = None
        for _ in range(4):
            if parent and parent.name in ['li', 'div', 'tr']:
                container = parent
            if parent:
                parent = parent.parent
        if not container:
            container = tag.parent

        title = clean_title(container, article_id)

        # پیدا کردن لینک فایل اصل مقاله
        pdf_source_url = None
        for a in container.find_all("a", href=True):
            href = a["href"].strip()
            if ".pdf" in href.lower() or "download" in href.lower():
                pdf_source_url = requests.compat.urljoin(TARGET_URL, href)
                break

        drive_link = ""
        if pdf_source_url:
            try:
                print(f"دانلود PDF برای: {title}")
                resp_pdf = requests.get(pdf_source_url, headers=HEADERS, timeout=45)
                if resp_pdf.status_code == 200 and len(resp_pdf.content) > 3000:
                    filename = re.sub(r'[\\/*?:"<>|]', "", title)[:60] + ".pdf"
                    print("در حال آپلود در گوگل درایو (پوشه مجلس راهبرد)...")
                    drive_link = upload_to_google_drive(filename, resp_pdf.content)
            except Exception as e:
                print(f"خطا در دانلود/آپلود: {e}")

        # دکمه دانلود فقط باید به گوگل درایو برود
        # اگر هنوز در درایو آپلود نشده، لینک مستقیم DOI قرار می‌گیرد نه فایل خراب نشریه
        final_download_url = drive_link if drive_link else doi_url

        new_articles.append({
            "id": article_id,
            "title": title,
            "doi_url": doi_url,
            "pdf_url": final_download_url
        })

    save_data(new_articles)
    print("به‌روزرسانی با موفقیت انجام شد.")

if __name__ == "__main__":
    main()
