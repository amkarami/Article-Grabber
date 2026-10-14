import os
import re
import json
import base64
import requests
from bs4 import BeautifulSoup

TARGET_URL = "https://nashr.majles.ir/"
GAS_WEB_APP_URL = "https://script.google.com/macros/s/AKfycbzsgIumCWxyAhQ55f5DG61vLZ2UOQlyfr1v8JzGHEmWiHTr4TtQPYsIqnI8lzNdykFR/exec"
DATA_FILE = "downloaded_articles.json"

IGNORE_WORDS = [
    "شماره‌های پیشین نشریه", "مقالات آماده انتشار", "شماره جاری",
    "مقاله پژوهشی", "مقاله ترویجی", "مقاله مروری", "مشاهده مقاله",
    "اصل مقاله", "فایل کلی", "دانلود", "doi"
]

def load_saved_articles():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else []
        except Exception:
            return []
    return []

def save_articles(articles):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(articles, f, ensure_ascii=False, indent=2)

def upload_to_drive(filename, file_bytes, mime_type="application/pdf"):
    try:
        b64_content = base64.b64encode(file_bytes).decode('utf-8')
        payload = {
            "folderName": "مجلس راهبرد",
            "fileName": filename,
            "mimeType": mime_type,
            "fileContent": b64_content
        }
        resp = requests.post(GAS_WEB_APP_URL, json=payload, timeout=90)
        if resp.status_code == 200:
            res_data = resp.json()
            if res_data.get("status") == "success":
                # لینک مشاهده یا دانلود از گوگل درایو
                return res_data.get("downloadUrl") or res_data.get("fileUrl")
    except Exception as e:
        print(f"Drive upload error: {e}")
    return None

def clean_text(text):
    return re.sub(r'\s+', ' ', text).strip() if text else ""

def is_title_candidate(text):
    t = clean_text(text)
    if len(t) < 15 or re.search(r'^\d+\.\d{4,9}/', t) or re.search(r'^صفحه\s+\d+', t):
        return False
    for ign in IGNORE_WORDS:
        if t.startswith(ign) or ign in t:
            return False
    return True

def main():
    print("در حال دریافت صفحه اصلی نشریه...")
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(TARGET_URL, headers=headers, timeout=30)
    except Exception as e:
        print(f"خطا در اتصال به سایت: {e}")
        return

    soup = BeautifulSoup(res.text, "html.parser")
    saved_articles = load_saved_articles()
    saved_ids = {a.get("id") if isinstance(a, dict) else a for a in saved_articles}

    doi_links = soup.find_all("a", href=re.compile(r"doi\.org/10\.", re.I))
    new_count = 0

    for doi_tag in doi_links:
        doi_url = doi_tag["href"].strip()
        doi_match = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", doi_url)
        article_id = doi_match.group(0) if doi_match else doi_url

        if article_id in saved_ids:
            continue

        parent = doi_tag.parent
        container = None
        for _ in range(4):
            if parent and (parent.name in ['li', 'div', 'tr']):
                if len(parent.find_all("a", href=re.compile(r"doi\.org/10\.", re.I))) == 1:
                    container = parent
            if parent:
                parent = parent.parent

        if not container:
            container = doi_tag.parent

        # یافتن عنوان مقاله
        title = ""
        for tag in container.find_all(['h5', 'h4', 'h3', 'strong', 'p', 'a', 'span']):
            txt = tag.get_text()
            if is_title_candidate(txt):
                title = clean_text(txt)
                break

        if not title:
            for s in [clean_text(st) for st in container.stripped_strings]:
                if is_title_candidate(s):
                    title = s
                    break

        if not title:
            title = f"مقاله {article_id}"

        print(f"\nدر حال پردازش: {title}")

        # پیدا کردن لینک دانلود فایل PDF از داخل صفحه
        pdf_download_link = ""
        for a in container.find_all("a", href=True):
            href = a["href"].strip()
            if ".pdf" in href.lower() or "download" in href.lower():
                if not href.startswith("http"):
                    href = requests.compat.urljoin(TARGET_URL, href)
                pdf_download_link = href
                break

        drive_file_url = ""
        if pdf_download_link:
            try:
                print(f"دانلود فایل PDF از: {pdf_download_link}")
                pdf_file_res = requests.get(pdf_download_link, headers=headers, timeout=45)
                if pdf_file_res.status_code == 200 and len(pdf_file_res.content) > 5000:
                    clean_filename = re.sub(r'[\\/*?:"<>|]', "", title)[:60] + ".pdf"
                    print("در حال انتقال فایل به گوگل درایو...")
                    drive_file_url = upload_to_drive(clean_filename, pdf_file_res.content)
                    if drive_file_url:
                        print(f"فایل با موفقیت در درایو قرار گرفت: {drive_file_url}")
            except Exception as ex:
                print(f"خطا در دانلود یا آپلود درایو: {ex}")

        # اگر به درایو آپلود نشد، لینک خود مقاله یا DOI را قرار می‌دهیم
        final_pdf_url = drive_file_url if drive_file_url else doi_url

        saved_articles.append({
            "id": article_id,
            "title": title,
            "doi_url": doi_url,
            "pdf_url": final_pdf_url
        })
        saved_ids.add(article_id)
        new_count += 1

    save_articles(saved_articles)
    print(f"\nعملیات به پایان رسید. {new_count} مقاله به گوگل درایو و دیتابیس اضافه شدند.")

if __name__ == "__main__":
    main()
