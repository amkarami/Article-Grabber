import os
import re
import json
import base64
import requests
from bs4 import BeautifulSoup

TARGET_URL = "https://nashr.majles.ir/"
GAS_WEB_APP_URL = "https://script.google.com/macros/s/AKfycbz0EDuufk9TvKcFRDvpHWP0WbbsCDWsyVgkMFrNinnSh4S3r31PiRNXGHwjtIM1CK7l/exec"
DATA_FILE = "downloaded_articles.json"

IGNORE_WORDS = [
    "شماره‌های پیشین نشریه",
    "مقالات آماده انتشار",
    "شماره جاری",
    "مقاله پژوهشی",
    "مقاله ترویجی",
    "مقاله مروری",
    "مشاهده مقاله",
    "اصل مقاله",
    "فایل کلی",
    "دانلود",
    "doi"
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
        resp = requests.post(GAS_WEB_APP_URL, json=payload, timeout=60)
        return resp.status_code == 200
    except Exception as e:
        print(f"Drive upload failed: {e}")
        return False

def clean_text(text):
    if not text:
        return ""
    return re.sub(r'\s+', ' ', text).strip()

def is_title_candidate(text):
    t = clean_text(text)
    if len(t) < 15:
        return False
    if re.search(r'^\d+\.\d{4,9}/', t):
        return False
    if re.search(r'^صفحه\s+\d+', t):
        return False
    for ign in IGNORE_WORDS:
        if t.startswith(ign) or ign in t:
            return False
    return True

def get_real_pdf_and_details(container, doi_url):
    headers = {"User-Agent": "Mozilla/5.0"}
    article_page_url = ""
    
    # پیدا کردن لینک صفحه اختصاصی مقاله
    for a in container.find_all("a", href=re.compile(r"/article_\d+", re.I)):
        href = a["href"]
        if not href.startswith("http"):
            href = requests.compat.urljoin(TARGET_URL, href)
        if ".pdf" not in href.lower():
            article_page_url = href
            break

    pdf_url = ""
    if article_page_url:
        try:
            res = requests.get(article_page_url, headers=headers, timeout=20)
            if res.status_code == 200:
                soup_art = BeautifulSoup(res.text, "html.parser")
                # جستجوی لینک اصلی PDF در صفحه مقاله
                pdf_tag = soup_art.find("a", href=re.compile(r"\.pdf", re.I))
                if pdf_tag:
                    pdf_url = pdf_tag["href"].strip()
                    if not pdf_url.startswith("http"):
                        pdf_url = requests.compat.urljoin(TARGET_URL, pdf_url)
        except Exception as e:
            print(f"Error fetching article page: {e}")

    # اگر پیدا نشد، از لینک DOI یا پیش‌فرض استفاده کن
    if not pdf_url:
        pdf_url = doi_url

    return pdf_url

def main():
    print("Fetching website...")
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        res = requests.get(TARGET_URL, headers=headers, timeout=30)
    except Exception as e:
        print(f"Error connecting: {e}")
        return

    soup = BeautifulSoup(res.text, "html.parser")
    saved_articles = load_saved_articles()
    saved_ids = {a.get("id") if isinstance(a, dict) else a for a in saved_articles}

    doi_links = soup.find_all("a", href=re.compile(r"doi\.org/10\.", re.I))
    new_articles_count = 0

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

        title = ""
        for tag in container.find_all(['h5', 'h4', 'h3', 'strong', 'p', 'a', 'span']):
            txt = tag.get_text()
            if is_title_candidate(txt):
                title = clean_text(txt)
                break

        if not title:
            all_strings = [clean_text(s) for s in container.stripped_strings]
            for s in all_strings:
                if is_title_candidate(s):
                    title = s
                    break

        if not title:
            title = "مقاله نشریه مجلس"

        # استخراج لینک واقعی و صحیح PDF از صفحه مقاله
        pdf_url = get_real_pdf_and_details(container, doi_url)

        print(f"Extracted: {title} | PDF: {pdf_url}")

        if pdf_url and ".pdf" in pdf_url:
            try:
                pdf_resp = requests.get(pdf_url, headers=headers, timeout=40)
                if pdf_resp.status_code == 200:
                    clean_title_file = re.sub(r'[\\/*?:"<>|]', "", title)[:60]
                    safe_filename = f"{clean_title_file}.pdf"
                    upload_to_drive(safe_filename, pdf_resp.content, "application/pdf")
            except Exception as e:
                print(f"PDF download/upload warning: {e}")

        article_entry = {
            "id": article_id,
            "title": title,
            "doi_url": doi_url,
            "pdf_url": pdf_url
        }
        saved_articles.append(article_entry)
        saved_ids.add(article_id)
        new_articles_count += 1

    save_articles(saved_articles)
    print(f"Finished. {new_articles_count} new articles recorded.")

if __name__ == "__main__":
    main()
