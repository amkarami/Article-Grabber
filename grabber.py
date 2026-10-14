import os
import re
import json
import base64
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = "https://nashr.majles.ir/"
DB_FILE = "downloaded_articles.json"

WEB_APP_URL = os.environ.get(
    "GDRIVE_WEBAPP_URL",
    "https://script.google.com/macros/s/AKfycbz0EDuufk9TvKcFRDvpHWP0WbbsCDWsyVgkMFrNinnSh4S3r31PiRNXGHwjtIM1CK7l/exec"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36"
}

def upload_to_drive(filename: str, content_bytes: bytes, mime_type: str = "application/octet-stream") -> bool:
    """ارسال فایل به وب‌اپلیکیشن گوگل‌اسکریپت و ذخیره در پوشه مجلس راهبرد"""
    try:
        b64_content = base64.b64encode(content_bytes).decode("utf-8")
        payload = {
            "filename": filename,
            "mimeType": mime_type,
            "base64": b64_content
        }
        res = requests.post(WEB_APP_URL, json=payload, timeout=90, allow_redirects=True)
        if res.status_code == 200:
            print(f"✔ فایل با موفقیت در گوگل‌درایو ذخیره شد: {filename}")
            return True
        else:
            print(f"✖ خطا در آپلود {filename} - وضعیت سرور: {res.status_code}")
            return False
    except Exception as e:
        print(f"✖ خطا در ارتباط با گوگل‌درایو: {e}")
        return False

def load_history():
    if os.path.exists(DB_FILE):
        try:
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []

def save_history(history):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

def clean_filename(text: str) -> str:
    cleaned = re.sub(r'[\\/*?:"<>|]', "", text).strip()
    return re.sub(r'\s+', " ", cleaned)[:100]

def main():
    history = load_history()
    # اطمینان از وجود فایل تاریخچه در شروع کار تا دستور git add با خطا مواجه نشود
    save_history(history)

    print("در حال بررسی وب‌سایت نشریه مجلس...")

    try:
        res = requests.get(BASE_URL, headers=HEADERS, timeout=30)
        res.raise_for_status()
        res.encoding = res.apparent_encoding
    except Exception as e:
        print(f"خطا در باز کردن وب‌سایت نشریه: {e}")
        return

    soup = BeautifulSoup(res.text, "html.parser")

    # پیدا کردن لینک‌های دانلود PDF بر اساس الگوهای آدرس یا متن
    pdf_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True)
        if ".pdf" in href.lower() or "اصل مقاله" in text:
            if not any(item["href"] == href for item in pdf_links):
                pdf_links.append(a)

    if not pdf_links:
        print("هیچ پیوندی برای دریافت مقالات یافت نشد.")
        return

    print(f"تعداد {len(pdf_links)} پیوند مقاله پیدا شد.")
    new_articles_count = 0

    for a_pdf in pdf_links:
        pdf_url = urljoin(BASE_URL, a_pdf["href"])

        # پیدا کردن کانتینر دربرگیرنده این مقاله
        parent = a_pdf.parent
        for _ in range(6):
            if parent and (parent.find(re.compile(r"h[2-6]")) or parent.find("a", href=re.compile(r"10\.\d{4,9}|doi\.org"))):
                break
            if parent and parent.parent:
                parent = parent.parent

        block = parent if parent else soup

        # استخراج عنوان مقاله
        title_tag = block.find(re.compile(r"h[2-6]"))
        if not title_tag:
            title_tag = block.find("a", href=re.compile(r"article_"))
        title = title_tag.get_text(strip=True) if title_tag else f"مقاله_{clean_filename(os.path.basename(pdf_url))}"
        clean_title = clean_filename(title)

        # استخراج لینک یا متن DOI
        doi_link_tag = block.find("a", href=re.compile(r"10\.\d{4,9}|doi\.org"))
        doi_url = None
        doi_val = None

        if doi_link_tag:
            doi_url = doi_link_tag["href"].strip()
            doi_val = doi_link_tag.get_text(strip=True)
        else:
            # جستجو در متن بلاک برای رشته DOI
            doi_match = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", block.get_text())
            if doi_match:
                doi_val = doi_match.group(0)
                doi_url = f"https://doi.org/{doi_val}"

        unique_id = doi_val or pdf_url

        if unique_id in history:
            continue

        print(f"\n================================")
        print(f"مقاله جدید یافت شد: {clean_title}")
        new_articles_count += 1

        # ۱) دانلود و آپلود اصل فایل PDF
        try:
            print("در حال دریافت فایل PDF...")
            r_pdf = requests.get(pdf_url, headers=HEADERS, timeout=60)
            if r_pdf.status_code == 200:
                upload_to_drive(f"{clean_title}.pdf", r_pdf.content, "application/pdf")
        except Exception as e:
            print(f"خطا در دریافت PDF: {e}")

        # ۲) کپی محتوای صفحه هایپرلینک DOI
        if doi_url:
            try:
                if doi_url.startswith("10."):
                    doi_url = "https://doi.org/" + doi_url
                elif doi_url.startswith("//"):
                    doi_url = "https:" + doi_url

                print(f"در حال کپی محتوای DOI از: {doi_url}")
                r_doi = requests.get(doi_url, headers=HEADERS, timeout=40, allow_redirects=True)
                if r_doi.status_code == 200:
                    upload_to_drive(f"{clean_title}_DOI.html", r_doi.content, "text/html")
            except Exception as e:
                print(f"خطا در کپی DOI: {e}")

        history.append(unique_id)

    save_history(history)

    if new_articles_count > 0:
        print(f"\nعملیات با موفقیت انجام شد: {new_articles_count} مقاله کپی شد.")
    else:
        print("\nتمام مقالات موجود قبلاً دانلود شده بودند.")

if __name__ == "__main__":
    main()
