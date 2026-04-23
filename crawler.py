import os
import json
import hashlib
import requests
import feedparser
from datetime import datetime, timezone, timedelta
from bs4 import BeautifulSoup
from email.utils import parsedate_to_datetime

# ── 환경변수 ──────────────────────────────────────────────────
TELEGRAM_TOKEN      = os.environ["TELEGRAM_TOKEN"]
TELEGRAM_CHAT_ID    = os.environ["TELEGRAM_CHAT_ID"]
NAVER_CLIENT_ID     = os.environ["NAVER_CLIENT_ID"]
NAVER_CLIENT_SECRET = os.environ["NAVER_CLIENT_SECRET"]

KEYWORD     = "휴게소"
SENT_FILE   = "sent_news.json"
MAX_HISTORY = 1000
HEADERS     = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

# ── 날짜 기준선 (KST 기준 2026-04-15 00:00) ──────────────────
KST = timezone(timedelta(hours=9))
DATE_FROM = datetime(2026, 4, 15, 0, 0, 0, tzinfo=KST)

def is_after_cutoff(date_str: str) -> bool:
    if not date_str:
        return True
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=KST)
        return dt >= DATE_FROM
    except Exception:
        try:
            dt = datetime.strptime(date_str[:25], "%a, %d %b %Y %H:%M:%S")
            dt = dt.replace(tzinfo=KST)
            return dt >= DATE_FROM
        except Exception:
            return True

# ── 유틸 ─────────────────────────────────────────────────────
def load_sent() -> set:
    if os.path.exists(SENT_FILE):
        with open(SENT_FILE, "r") as f:
            return set(json.load(f))
    return set()

def save_sent(sent: set):
    with open(SENT_FILE, "w") as f:
        json.dump(list(sent)[-MAX_HISTORY:], f)

def make_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()

def now_str() -> str:
    return datetime.now(KST).strftime("%Y-%m-%d %H:%M")

# ── 텔레그램 전송 ─────────────────────────────────────────────
def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    requests.post(url, data={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }, timeout=10)

# ════════════════════════════════════════════
#  📰 뉴스 크롤러
# ════════════════════════════════════════════

def fetch_naver_news(keyword: str) -> list[dict]:
    url = "https://openapi.naver.com/v1/search/news.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    res = requests.get(url, headers=headers,
                       params={"query": keyword, "display": 10, "sort": "date"}, timeout=10)
    results = []
    for item in res.json().get("items", []):
        if not is_after_cutoff(item.get("pubDate", "")):
            continue
        title = item["title"].replace("<b>", "").replace("</b>", "")
        results.append({"source": "네이버 뉴스", "title": title,
                         "url": item["link"], "date": item.get("pubDate", "")})
    return results

def fetch_google_news(keyword: str) -> list[dict]:
    rss = f"https://news.google.com/rss/search?q={requests.utils.quote(keyword)}&hl=ko&gl=KR&ceid=KR:ko"
    feed = feedparser.parse(rss)
    results = []
    for e in feed.entries[:10]:
        pub = e.get("published", "")
        if not is_after_cutoff(pub):
            continue
        results.append({"source": "구글 뉴스", "title": e.title, "url": e.link, "date": pub})
    return results

def fetch_daum_news(keyword: str) -> list[dict]:
    url = f"https://search.daum.net/search?w=news&q={requests.utils.quote(keyword)}"
    res = requests.get(url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(res.text, "html.parser")
    results = []
    for item in soup.select(".c-list-basic li, .item-title")[:10]:
        a = item.select_one("a")
        date_tag = item.select_one(".datetime, .date, .f_nb")
        if not a:
            continue
        href = a.get("href", "")
        if not href.startswith("http"):
            href = "https:" + href
        title = a.get_text(strip=True)
        date_str = date_tag.get_text(strip=True) if date_tag else ""
        if date_str:
            try:
                dt = datetime.strptime(date_str[:10], "%Y.%m.%d").replace(tzinfo=KST)
                if dt < DATE_FROM:
                    continue
            except Exception:
                pass
        if title:
            results.append({"source": "다음 뉴스", "title": title, "url": href, "date": date_str})
    return results

# ════════════════════════════════════════════
#  📝 블로그 / 게시글 크롤러
# ════════════════════════════════════════════

def fetch_naver_blog(keyword: str) -> list[dict]:
    url = "https://openapi.naver.com/v1/search/blog.json"
    headers = {
        "X-Naver-Client-Id": NAVER_CLIENT_ID,
        "X-Naver-Client-Secret": NAVER_CLIENT_SECRET
    }
    res = requests.get(url, headers=headers,
                       params={"query": keyword, "display": 10, "sort": "date"}, timeout=10)
    results = []
    for item in res.json().get("items", []):
        pd = item.get("postdate", "")
        if pd:
            try:
                dt = datetime.strptime(pd, "%Y%m%d").replace(tzinfo=KST)
                if dt < DATE_FROM:
                    continue
            except Exception:
                pass
        title = item["title"].replace("<b>", "").replace("</b>", "")
        results.append({"source": "네이버 블로그", "title": title,
                         "url": item["link"], "date": pd})
    return results

def fetch_tistory(keyword: str) -> list[dict]:
    rss = f"https://news.google.com/rss/search?q={requests.utils.quote(keyword)}+site:tistory.com&hl=ko&gl=KR&ceid=KR:ko"
    feed = feedparser.parse(rss)
    results = []
    for e in feed.entries[:10]:
        pub = e.get("published", "")
        if not is_after_cutoff(pub):
            continue
        if "tistory" in e.link:
            results.append({"source": "티스토리", "title": e.title, "url": e.link, "date": pub})
    return results

def fetch_daum_cafe(keyword: str) -> list[dict]:
    url = f"https://search.daum.net/search?w=cafe&q={requests.utils.quote(keyword)}"
    res = requests.get(url, headers=HEADERS, timeout=10)
    soup = BeautifulSoup(res.text, "html.parser")
    results = []
    for item in soup.select(".c-list-basic li")[:10]:
        a = item.select_one("a")
        date_tag = item.select_one(".datetime, .date, .f_nb")
        if not a:
            continue
        href = a.get("href", "")
        if not href.startswith("http"):
            href = "https:" + href
        title = a.get_text(strip=True)
        date_str = date_tag.get_text(strip=True) if date_tag else ""
        if date_str:
            try:
                dt = datetime.strptime(date_str[:10], "%Y.%m.%d").replace(tzinfo=KST)
                if dt < DATE_FROM:
                    continue
            except Exception:
                pass
        if title and "cafe" in href:
            results.append({"source": "다음 카페", "title": title, "url": href, "date": date_str})
    return results

def fetch_google_web(keyword: str) -> list[dict]:
    rss = f"https://news.google.com/rss/search?q={requests.utils.quote(keyword)}&hl=ko&gl=KR&ceid=KR:ko"
    feed = feedparser.parse(rss)
    results = []
    for e in feed.entries[:10]:
        pub = e.get("published", "")
        if not is_after_cutoff(pub):
            continue
        if not any(d in e.link for d in ["news.naver", "news.daum", "google.com/news"]):
            results.append({"source": "구글 웹", "title": e.title, "url": e.link, "date": pub})
    return results

# ════════════════════════════════════════════
#  메인
# ════════════════════════════════════════════

def process_items(items: list[dict], sent: set, category: str, emoji: str) -> tuple[int, set]:
    new_count = 0
    for item in items:
        uid = make_id(item["url"])
        if uid in sent:
            continue
        date_display = item.get("date", "")[:10] if item.get("date") else "날짜 미상"
        msg = (
            f"{emoji} <b>[{category}] [{item['source']}]</b>\n\n"
            f"📌 {item['title']}\n\n"
            f"📅 {date_display}\n"
            f"🔗 {item['url']}\n\n"
            f"🕐 수집: {now_str()}"
        )
        send_telegram(msg)
        sent.add(uid)
        new_count += 1
    return new_count, sent

def main():
    sent = load_sent()
    total = 0

    # 📰 뉴스
    news_items = []
    for fetcher in [fetch_naver_news, fetch_google_news, fetch_daum_news]:
        try:
            news_items += fetcher(KEYWORD)
        except Exception as e:
            print(f"[뉴스 오류] {fetcher.__name__}: {e}")

    count, sent = process_items(news_items, sent, "뉴스", "📰")
    total += count

    # 📝 블로그/게시글
    blog_items = []
    for fetcher in [fetch_naver_blog, fetch_tistory, fetch_daum_cafe, fetch_google_web]:
        try:
            blog_items += fetcher(KEYWORD)
        except Exception as e:
            print(f"[블로그 오류] {fetcher.__name__}: {e}")

    count, sent = process_items(blog_items, sent, "블로그·게시글", "📝")
    total += count

    save_sent(sent)
    print(f"✅ 완료: 총 {total}개 새 항목 전송 (기준일: 2026-04-15 이후)")

if __name__ == "__main__":
    main()
