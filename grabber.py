import os
import re
import json
import base64
import requests
from bs4 import BeautifulSoup

TARGET_URL = "https://nashr.majles.ir/"
GAS_WEB_APP_URL = "https://script.google.com/macros/s/AKfycbz0EDuufk9TvKcFRDvpHWP0WbbsCDWsyVgkMFrNinnSh4S3r31PiRNXGHwjtIM1CK7l/exec"
DATA_FILE = "downloaded_articles.json"

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
    # ایجاد یک مجموعه از شناسه‌ها برای جلوگیری از دانلود تکراری
    saved_ids = {a.get("id") if isinstance(a, dict) else a for a in saved_articles}

    # پیدا کردن مقالات در صفحه
    article_nodes = soup.find_all("li", class_="margin-bottom-15") or soup.find_all("div", class_="article-item")

    # اگر تگ مشخصی پیدا نشد، همه بلوک‌های لینک‌دار را بررسی کن
    if not article_nodes:
        article_nodes = soup.find_all("div")

    new_articles_count = 0

    for node in article_nodes:
        # پیدا کردن لینک DOI
        doi_tag = node.find("a", href=re.compile(r"doi\.org/10\.", re.I))
        if not doi_tag:
            continue

        doi_url = doi_tag["href"].strip()
        doi_id = re.search(r"10\.\d{4,9}/[-._;()/:A-Za-z0-9]+", doi_url)
        article_id = doi_id.group(0) if doi_id else doi_url

        if article_id in saved_ids:
            continue

        # استخراج عنوان فارسی مقاله
        title = "مقاله نشریه مجلس"
        title_tag = node.find("h5") or node.find("h4") or node.find("strong")
        if title_tag:
            title = title_tag.get_text(strip=True)
        else:
            # جستجو در لینک اول
            first_link = node.find("a")
            if first_link and first_link.get_text(strip=True):
                title = first_link.get_text(strip=True)

        # استخراج لینک مستقیم PDF مقاله
        pdf_url = ""
        pdf_tag = node.find("a", href=re.compile(r"\.pdf|/article_\d+_.*\.html|/pdf_", re.I))
        if pdf_tag:
            pdf_url = pdf_tag["href"].strip()
            if not pdf_url.startswith("http"):
                pdf_url = requests.compat.urljoin(TARGET_URL, pdf_url)

        print(f"Found new article: {title}")

        # دانلود و ارسال PDF به درایو در صورت وجود
        if pdf_url:
            try:
                pdf_resp = requests.get(pdf_url, headers=headers, timeout=40)
                if pdf_resp.status_code == 200:
                    clean_title = re.sub(r'[\\/*?:"<>|]', "", title)[:60]
                    safe_filename = f"{clean_title}.pdf"
                    upload_to_drive(safe_filename, pdf_resp.content, "application/pdf")
            except Exception as e:
                print(f"PDF download/upload warning: {e}")

        # ثبت اطلاعات مقاله در لیست
        article_entry = {
            "id": article_id,
            "title": title,
            "doi_url": doi_url,
            "pdf_url": pdf_url or doi_url
        }
        saved_articles.append(article_entry)
        saved_ids.add(article_id)
        new_articles_count += 1

    save_articles(saved_articles)
    print(f"Finished. {new_articles_count} new articles recorded.")

if __name__ == "__main__":
    main()
