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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

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

def upload_to_drive(filename, file_bytes):
    try:
        b64_content = base64.b64encode(file_bytes).decode('utf-8')
        payload = {
            "folderName": "مجلس راهبرد",
            "fileName": filename,
            "mimeType": "application/pdf",
            "fileContent": b64_content
        }
        resp = requests.post(GAS_WEB_APP_URL, json=payload, timeout=90)
        if resp.status_code == 200:
            res_data = resp.json()
            if res_data.get("status") == "success":
                # لینک دانلود یا نمایش مستقیم از درایو
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

def fetch_actual_pdf(article_page_url):
    """از داخل صفحه اختصاصی مقاله، لینک واقعی و معتبر PDF را استخراج و دانلود می‌کند"""
    try:
        r = requests.get(article_page_url, headers=HEADERS, timeout=30)
        if r.status_code != 200:
            return None
        s = BeautifulSoup(r.text, "html.parser")
        
        # گشتن به دنبال دکمه دانلود اصل مقاله
        pdf_link = None
        for a in s.find_all("a", href=True):
            href = a["href"].strip()
            text = clean_text(a.get_text())
            if "pdf" in href.lower() or "اصل مقاله" in text or "دانلود" in text:
                pdf_link = requests.compat.urljoin(article_page_url, href)
                break
                
        if pdf_link:
            pdf_res = requests.get(pdf_link, headers=HEADERS, timeout=60)
            if pdf_res.status_code == 200 and len(pdf_res.content) > 5000:
                return pdf_res.content
    except Exception as e:
        print(f"Error fetching actual PDF: {e}")
    return None

def main():
    print("در حال دریافت لیست مقالات از سامانه نشریه...")
    try:
        res = requests.get(TARGET_URL, headers=HEADERS, timeout=30)
    except Exception as e:
        print(f"خطای شبکه: {e}")
        return

    soup = BeautifulSoup(res.text, "html.parser")
    saved_articles = load_saved_articles()
    
    # ساخت نگاشت برای بررسی اینکه آیا قبلاً لینک گوگل درایو ثبت شده یا نه
    saved_dict = {a["id"]: a for a in saved_articles if isinstance(a, dict) and "id" in a}

    doi_links = soup.find_all("a", href=re.compile(r"doi\.org/10\.", re.I))
    updated_articles = []

    for doi_tag in doi_links:
        doi_url = doi_tag["href"].strip()
        doi_match = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", doi_url)
        article_id = doi_match.group(0) if doi_match else doi_url

        # پیدا کردن عنوان مقاله
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

        title = ""
        for tag in container.find_all(['h5', 'h4', 'h3', 'strong', 'p', 'a', 'span']):
            txt = tag.get_text()
            if is_title_candidate(txt):
                title = clean_text(txt)
                break
        if not title:
            title = f"مقاله {article_id}"

        # اگر قبلاً دانلود شده و لینک آن متعلق به drive.google.com است، نیاز به دانلود مجدد نیست
        existing = saved_dict.get(article_id)
        if existing and "drive.google.com" in existing.get("pdf_url", ""):
            updated_articles.append(existing)
            continue

        print(f"\nدر حال دریافت و آپلود به درایو: {title}")
        
        # پیدا کردن لینک صفحه مقاله
        article_page_url = None
        for a in container.find_all("a", href=True):
            href = a["href"].strip()
            if "article_" in href or "article.php" in href:
                article_page_url = requests.compat.urljoin(TARGET_URL, href)
                break
        
        pdf_bytes = None
        if article_page_url:
            pdf_bytes = fetch_actual_pdf(article_page_url)
        
        # اگر از صفحه مقاله نشد، از لینک‌های داخل خود کانتینر تلاش کن
        if not pdf_bytes:
            for a in container.find_all("a", href=True):
                href = a["href"].strip()
                if ".pdf" in href.lower():
                    full_link = requests.compat.urljoin(TARGET_URL, href)
                    try:
                        r = requests.get(full_link, headers=HEADERS, timeout=45)
                        if r.status_code == 200 and len(r.content) > 5000:
                            pdf_bytes = r.content
                            break
                    except Exception:
                        pass

        drive_url = ""
        if pdf_bytes:
            clean_filename = re.sub(r'[\\/*?:"<>|]', "", title)[:60] + ".pdf"
            print("ارسال فایل به گوگل درایو...")
            drive_url = upload_to_drive(clean_filename, pdf_bytes)
            if drive_url:
                print(f"فایل با موفقیت ذخیره شد: {drive_url}")

        # اگر درایو با موفقیت انجام شد لینک درایو، در غیر اینصورت صفحه DOI
        final_pdf_link = drive_url if drive_url else doi_url

        updated_articles.append({
            "id": article_id,
            "title": title,
            "doi_url": doi_url,
            "pdf_url": final_pdf_link
        })

    save_articles(updated_articles)
    print("\nلیست نهایی به‌روزرسانی شد.")

if __name__ == "__main__":
    main()
