import os
import re
import json
import base64
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

BASE_URL = "https://nashr.majles.ir/"
DB_FILE = "downloaded_articles.json"

# لینک اختصاصی وب‌اپلیکیشن گوگل‌اسکریپت شما
# بهتر است از Secrets گیت‌هاب خوانده شود؛ اگر نبود از این پیش‌فرض استفاده می‌کند:
WEB_APP_URL = os.environ.get("GDRIVE_WEBAPP_URL", "https://script.google.com/macros/s/AKfycbz0EDuufk9TvKcFRDvpHWP0WbbsCDWsyVgkMFrNinnSh4S3r31PiRNXGHwjtIM1CK7l/exec")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0 Safari/537.36"
}

def upload_to_drive(filename: str, content_bytes: bytes, mime_type: str = "application/octet-stream") -> bool:
    """ارسال مستقیم فایل به وب‌اپلیکیشن گوگل و ساخت خودکار پوشه مجلس راهبرد"""
    try:
        b64_content = base64.b64encode(content_bytes).decode("utf-8")
        payload = {
            "filename": filename,
            "mimeType": mime_type,
            "base64": b64_content
        }
        # گوگل اسکریپت بعد از POST یک ریدایرکت 302 می‌دهد؛ requests خودکار آن را دنبال می‌کند
        res = requests.post(WEB_APP_URL, json=payload, timeout=60, allow_redirects=True)
        if res.status_code == 200:
            print(f"✔ فایل با موفقیت در گوگل‌درایو ذخیره شد: {filename}")
            return True
        else:
            print(f"✖ خطا در آپلود {filename} - وضعیت: {res.status_code}")
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
    print("در حال بررسی وب‌سایت نشریه مجلس...")

    try:
        res = requests.get(BASE_URL, headers=HEADERS, timeout=30)
        res.raise_for_status()
        res.encoding = res.apparent_encoding
    except Exception as e:
        print(f"خطا در باز کردن وب‌سایت نشریه: {e}")
        return

    soup = BeautifulSoup(res.text, "lxml")
    
    # پیدا کردن تمامی دکمه‌های «اصل مقاله»
    pdf_links = soup.find_all("a", href=True, string=re.compile(r"اصل\s*مقاله"))

    if not pdf_links:
        print("هیچ پیوندی برای «اصل مقاله» در صفحه اصلی یافت نشد.")
        return

    new_articles_count = 0

    for a_pdf in pdf_links:
        pdf_url = urljoin(BASE_URL, a_pdf["href"])

        # پیدا کردن کانتینر دربرگیرنده این مقاله برای دسترسی به عنوان و DOI
        parent = a_pdf.find_parent("div") or a_pdf.parent
        for _ in range(5):
            if parent and (parent.find(re.compile(r"h[2-6]")) or parent.find("a", href=re.compile(r"doi\.org|10\.\d{4,9}"))):
                break
            if parent and parent.parent:
                parent = parent.parent
        block = parent if parent else soup

        # ۱) استخراج عنوان مقاله
        title_tag = block.find(re.compile(r"h[2-6]"))
        title = title_tag.get_text(strip=True) if title_tag else "مقاله_بدون_عنوان"
        clean_title = clean_filename(title)

        # ۲) استخراج هایپرلینک کنار آیکون زرد DOI
        doi_link_tag = block.find("a", href=re.compile(r"doi\.org|10\.\d{4,9}"))
        doi_url = doi_link_tag["href"].strip() if doi_link_tag else None
        doi_text = doi_link_tag.get_text(strip=True) if doi_link_tag else None

        # شناسه اختصاصی مقاله جهت جلوگیری از دانلود تکراری
        unique_id = doi_text or pdf_url

        if unique_id in history:
            continue

        print(f"\n================================")
        print(f"مقاله جدید یافت شد: {clean_title}")
        new_articles_count += 1

        # الف) دانلود و آپلود اصل مقاله (PDF)
        try:
            print("در حال دانلود فایل PDF...")
            r_pdf = requests.get(pdf_url, headers=HEADERS, timeout=60)
            if r_pdf.status_code == 200:
                upload_to_drive(f"{clean_title}.pdf", r_pdf.content, "application/pdf")
        except Exception as e:
            print(f"خطا در دریافت PDF: {e}")

        # ب) دریافت و کپی محتوای صفحه هایپرلینک DOI
        if doi_url:
            try:
                # استانداردسازی آدرس DOI
                if doi_url.startswith("10."):
                    doi_url = "https://doi.org/" + doi_url
                elif doi_url.startswith("//"):
                    doi_url = "https:" + doi_url

                print(f"در حال کپی محتوای صفحه DOI از: {doi_url}")
                r_doi = requests.get(doi_url, headers=HEADERS, timeout=40, allow_redirects=True)
                if r_doi.status_code == 200:
                    upload_to_drive(f"{clean_title}_DOI.html", r_doi.content, "text/html")
            except Exception as e:
                print(f"خطا در کپی محتوای پیوند DOI: {e}")

        # ثبت شناسه در تاریخچه
        history.append(unique_id)

    if new_articles_count > 0:
        save_history(history)
        print(f"\nپایان عملیات: {new_articles_count} مقاله جدید با موفقیت پردازش شد.")
    else:
        print("هیچ مقاله جدیدی وجود ندارد (تمام مقالات قبلاً کپی شده‌اند).")

if __name__ == "__main__":
    main()
