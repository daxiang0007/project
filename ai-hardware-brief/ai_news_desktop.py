# -*- coding: utf-8 -*-
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from urllib.parse import quote_plus
import html
import os
import re
import sys
import threading
import webbrowser
import xml.etree.ElementTree as ET

import requests
import trafilatura
from googlenewsdecoder import gnewsdecoder
from deep_translator import GoogleTranslator, MyMemoryTranslator
import tkinter as tk
from tkinter import ttk, messagebox
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

APP_TITLE = "\u8c61\u54e5 AI \u786c\u4ef6\u6295\u8d44\u5185\u53c2"
SUBTITLE = "AI \u82af\u7247\u3001\u673a\u5668\u4eba\u3001\u7b97\u529b\u57fa\u7840\u8bbe\u65bd\u3001\u786c\u4ef6\u878d\u8d44\u52a8\u6001"
TARGET_COUNT = 20
MAX_PER_FEED = 5
REQUEST_TIMEOUT = 10
ARTICLE_TIMEOUT = 12
MAX_WORKERS = 8
TRANSLATE_WORKERS = 6
BAD_TITLE_KEYWORDS = ["Error 500", "Server Error", "Just a moment", "Page ", "Startups - TechCrunch", "Artificial Intelligence News", "\u8bf7\u5b8c\u6210\u4e0b\u5217\u9a8c\u8bc1", "\u7b2c "]

SEARCH_FEEDS = [
    {"query": "AI hardware NVIDIA Blackwell GPU chips robotics funding", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"query": "AI chips semiconductor accelerator startup funding", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"query": "NVIDIA AMD Intel AI hardware data center chip news", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"query": "robotics AI hardware humanoid robot chip sensor funding", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"query": "edge AI device NPU inference chip hardware startup", "hl": "en-US", "gl": "US", "ceid": "US:en"},
    {"query": "China AI chip hardware robot semiconductor latest news", "hl": "en-US", "gl": "US", "ceid": "US:en"},
]

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}


def google_news_url(feed, days):
    q = quote_plus(f"{feed['query']} when:{days}d")
    return f"https://news.google.com/rss/search?q={q}&hl={feed['hl']}&gl={feed['gl']}&ceid={feed['ceid']}"


def is_english_title(title):
    cjk_count = sum(1 for char in title if "\u4e00" <= char <= "\u9fff")
    latin_count = sum(1 for char in title if char.isascii() and char.isalpha())
    return latin_count >= 12 and cjk_count <= 2


def _translate_google_api(text):
    response = requests.get(
        "https://translate.googleapis.com/translate_a/single",
        params={"client": "gtx", "sl": "en", "tl": "zh-CN", "dt": "t", "q": text},
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
    )
    response.raise_for_status()
    return "".join(part[0] for part in response.json()[0] if part and part[0])


def _translate_deep_google(text):
    return GoogleTranslator(source="en", target="zh-CN").translate(text)


def _translate_mymemory(text):
    return MyMemoryTranslator(source="en-US", target="zh-CN").translate(text[:500])


TRANSLATE_BACKENDS = [_translate_google_api, _translate_deep_google, _translate_mymemory]


def translate_text(text, limit=1000):
    """Try each translation backend in turn; return None if all fail."""
    text = text[:limit]
    for backend in TRANSLATE_BACKENDS:
        try:
            translated = backend(text)
            if translated and translated.strip() and translated != text:
                return translated.strip()
        except Exception:
            continue
    return None


def translate_one_item(item):
    item = dict(item)
    if is_english_title(item["title"]):
        translated = translate_text(item["title"])
        if translated:
            item["original_title"] = item["title"]
            item["title"] = translated
    if item.get("summary") and is_english_title(item["summary"]):
        translated_summary = translate_text(item["summary"])
        if translated_summary:
            item["summary"] = translated_summary
    return item


def translate_english_titles(news, status_callback=None):
    if status_callback:
        status_callback("\u6b63\u5728\u7ffb\u8bd1\u82f1\u6587\u6807\u9898...")
    translated_news = [None] * len(news)
    with ThreadPoolExecutor(max_workers=TRANSLATE_WORKERS) as executor:
        futures = {executor.submit(translate_one_item, item): index for index, item in enumerate(news)}
        for future in as_completed(futures):
            translated_news[futures[future]] = future.result()
    return [item for item in translated_news if item is not None]


def fetch_feed(feed, days):
    try:
        response = requests.get(google_news_url(feed, days), headers=HEADERS, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        root = ET.fromstring(response.content)
    except Exception:
        return []
    news = []
    for item in root.findall(".//item"):
        title = item.findtext("title") or "\u65e0\u6807\u9898"
        if any(keyword in title for keyword in BAD_TITLE_KEYWORDS):
            continue
        source_node = item.find("source")
        news.append({
            "title": title,
            "source": source_node.text if source_node is not None and source_node.text else "Google News",
            "url": item.findtext("link") or "",
            "date": item.findtext("pubDate") or "",
            "summary": clean_summary(item.findtext("description") or ""),
        })
        if len(news) >= MAX_PER_FEED:
            break
    return news


def fetch_google_news(days):
    seen = set()
    news = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        futures = [executor.submit(fetch_feed, feed, days) for feed in SEARCH_FEEDS]
        for future in as_completed(futures):
            for item in future.result():
                key = item["url"] or item["title"]
                if not key or key in seen:
                    continue
                seen.add(key)
                news.append(item)
                if len(news) >= TARGET_COUNT:
                    return news
    return news


def fetch_ai_hardware_news(status_callback=None):
    if status_callback:
        status_callback("\u6b63\u5728\u641c\u7d22\u8fc7\u53bb 24 \u5c0f\u65f6\u7684 AI \u786c\u4ef6\u52a8\u6001...")
    news = fetch_google_news(1)
    if len(news) < 10:
        if status_callback:
            status_callback("24 \u5c0f\u65f6\u7ed3\u679c\u504f\u5c11\uff0c\u6b63\u5728\u6269\u5c55\u5230\u6700\u8fd1\u4e00\u5468...")
        weekly_news = fetch_google_news(7)
        seen = {item["url"] or item["title"] for item in news}
        for item in weekly_news:
            key = item["url"] or item["title"]
            if key in seen:
                continue
            seen.add(key)
            news.append(item)
            if len(news) >= TARGET_COUNT:
                break
    return translate_english_titles(news[:TARGET_COUNT], status_callback)


def app_base_dir():
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def clean_text(raw_text, limit=None):
    if not raw_text:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw_text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] if limit else text


def clean_summary(raw_text):
    return clean_text(raw_text, 360)


def extract_core_data(text):
    patterns = [
        r"\$?\d+(?:\.\d+)?\s?(?:million|billion|trillion|M|B|T)",
        r"\d+(?:\.\d+)?\s?(?:\u4e07|\u4ebf|\u4e07\u5143|\u4ebf\u5143|\u4e07\u7f8e\u5143|\u4ebf\u7f8e\u5143|\u4e07\u6b27\u5143|\u4ebf\u6b27\u5143)",
        r"\d+(?:\.\d+)?%",
        r"(?:Pre-)?[ABCD]\+?\s?\u8f6e",
        r"Series\s?[ABCD]",
        r"IPO|M&A|\u5e76\u8d2d|\u6536\u8d2d|\u4e0a\u5e02|\u878d\u8d44|\u91cf\u4ea7|\u8425\u6536|\u51c0\u5229\u6da6",
        r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}|20\d{2}\u5e74\d{1,2}\u6708(?:\d{1,2}\u65e5)?|\u4e0a\u534a\u5e74|\u4e0b\u534a\u5e74|Q[1-4]|\u7b2c[\u4e00\u4e8c\u4e09\u56db]\u5b63\u5ea6",
    ]
    hits = []
    for pattern in patterns:
        for match in re.findall(pattern, text, flags=re.IGNORECASE):
            value = match if isinstance(match, str) else "".join(match)
            value = value.strip()
            if value and value not in hits:
                hits.append(value)
    return hits[:8]


def resolve_article_url(url):
    if not url:
        return ""
    if "news.google.com" not in url:
        return url
    try:
        decoded = gnewsdecoder(url)
        if isinstance(decoded, dict) and decoded.get("status") and decoded.get("decoded_url"):
            return decoded["decoded_url"]
    except Exception:
        return url
    return url


def fetch_article_text(url):
    if not url:
        return ""
    url = resolve_article_url(url)
    try:
        downloaded = trafilatura.fetch_url(url, no_ssl=True, config=None)
        if not downloaded:
            response = requests.get(url, headers=HEADERS, timeout=ARTICLE_TIMEOUT, allow_redirects=True)
            response.raise_for_status()
            downloaded = response.text
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
            url=url,
        )
        return clean_text(text or "", 6000)
    except Exception:
        return ""


def split_sentences(text):
    parts = re.split(r"(?<=[\u3002\uff01\uff1f.!?])\s+|(?<=[\u3002\uff01\uff1f])", text)
    return [part.strip() for part in parts if len(part.strip()) >= 12]


def looks_like_reference(sentence):
    lowered = sentence.lower()
    bad_terms = ["retrieved", "accessed", "doi", "isbn", "archive.is", "http://", "https://", "references", "bibliography"]
    if any(term in lowered for term in bad_terms):
        return True
    if re.match(r"^\s*\d+\s*[|.]", sentence):
        return True
    if len(re.findall(r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}", sentence)) >= 2:
        return True
    if sentence.count(".") >= 5 and len(sentence) < 260:
        return True
    return False


def translate_to_chinese(text):
    if not text or not is_english_title(text):
        return text
    return translate_text(text, 1800) or text


def summarize_article_text(article_text):
    sentences = [s for s in split_sentences(article_text) if not looks_like_reference(s)]
    if not sentences:
        return ""
    keyword_re = re.compile(
        r"AI|chip|GPU|NVIDIA|robot|semiconductor|funding|IPO|revenue|mass produc|data center|\u82af\u7247|\u673a\u5668\u4eba|\u534a\u5bfc\u4f53|\u878d\u8d44|\u6536\u8d2d|\u5e76\u8d2d|\u4e0a\u5e02|\u8425\u6536|\u91cf\u4ea7|\u7b97\u529b",
        re.IGNORECASE,
    )
    selected = []
    for sentence in sentences[:18]:
        if keyword_re.search(sentence) or extract_core_data(sentence) or len(selected) < 2:
            selected.append(sentence)
        if len("".join(selected)) >= 360:
            break
    if not selected:
        selected = sentences[:4]
    summary = " ".join(selected).strip()
    return translate_to_chinese(summary[:900])


def enrich_one_article(item):
    item = dict(item)
    item["resolved_url"] = resolve_article_url(item.get("url"))
    article_text = fetch_article_text(item.get("resolved_url"))
    item["article_text"] = article_text
    if article_text:
        item["article_summary"] = summarize_article_text(article_text)
        filtered_text = " ".join(s for s in split_sentences(article_text) if not looks_like_reference(s))
        data = extract_core_data(" ".join([item.get("title", ""), item.get("summary", ""), filtered_text[:3000]]))
        item["core_data"] = "\u3001".join(data) if data else "\u672a\u62ab\u9732"
    else:
        item["article_summary"] = ""
        item["core_data"] = "\u6b63\u6587\u672a\u80fd\u6293\u53d6"
    return item


def enrich_articles_for_pdf(news, status_callback=None):
    if status_callback:
        status_callback("\u6b63\u5728\u6293\u53d6\u65b0\u95fb\u539f\u6587\u5e76\u751f\u6210\u6458\u8981...")
    enriched = [None] * len(news)
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {executor.submit(enrich_one_article, item): index for index, item in enumerate(news)}
        for future in as_completed(futures):
            enriched[futures[future]] = future.result()
    return [item for item in enriched if item is not None]


def build_summary(item):
    article_summary = clean_summary(item.get("article_summary") or "")
    if article_summary:
        facts = article_summary
    else:
        title = clean_summary(item.get("title") or "")
        raw_summary = clean_summary(item.get("summary") or "")
        source = item.get("source") or "Google News"
        date = item.get("date") or ""
        parts = []
        if raw_summary and raw_summary != title:
            parts.append(raw_summary)
        if title:
            parts.append(f"\u6807\u9898\u4fe1\u606f\uff1a{title}")
        parts.append(f"\u6765\u6e90\uff1a{source}" + (f"\uff1b\u53d1\u5e03\u65f6\u95f4\uff1a{date}" if date else ""))
        facts = "\u539f\u6587\u6b63\u6587\u672a\u80fd\u6293\u53d6\uff0c\u4ec5\u8bb0\u5f55 RSS \u4e2d\u53ef\u9a8c\u8bc1\u7684\u4fe1\u606f\uff1a" + " ".join(parts)
    data_text = item.get("core_data") or "\u672a\u62ab\u9732"
    return {"facts": facts[:760], "data": data_text}


def pdf_safe(text):
    return html.escape(str(text or ""))


PDF_FONT_CANDIDATES = [
    ("MicrosoftYaHei", r"C:\Windows\Fonts\msyh.ttc"),
    ("DengXian", r"C:\Windows\Fonts\Deng.ttf"),
    ("SimHei", r"C:\Windows\Fonts\simhei.ttf"),
]


def register_pdf_font():
    """Register a TrueType font that renders both Chinese and English cleanly.
    Falls back to the built-in STSong-Light CID font if none is available."""
    for name, path in PDF_FONT_CANDIDATES:
        if name in pdfmetrics.getRegisteredFontNames():
            return name
        if not os.path.exists(path):
            continue
        try:
            pdfmetrics.registerFont(TTFont(name, path, subfontIndex=0))
            return name
        except Exception:
            continue
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    return "STSong-Light"


def generate_pdf_report(news, output_path):
    pdf_font = register_pdf_font()
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle",
        parent=styles["Title"],
        fontName=pdf_font,
        fontSize=20,
        leading=26,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#171717"),
        spaceAfter=8,
    )
    subtitle_style = ParagraphStyle(
        "ReportSubtitle",
        parent=styles["Normal"],
        fontName=pdf_font,
        fontSize=9,
        leading=13,
        alignment=TA_CENTER,
        textColor=colors.HexColor("#6f624e"),
        spaceAfter=10,
    )
    meta_style = ParagraphStyle(
        "ReportMeta",
        parent=styles["Normal"],
        fontName=pdf_font,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#8b7355"),
    )
    headline_style = ParagraphStyle(
        "Headline",
        parent=styles["Heading2"],
        fontName=pdf_font,
        fontSize=13,
        leading=18,
        textColor=colors.HexColor("#111111"),
        spaceAfter=4,
    )
    label_style = ParagraphStyle(
        "Label",
        parent=styles["BodyText"],
        fontName=pdf_font,
        fontSize=9,
        leading=12,
        textColor=colors.HexColor("#8b7355"),
    )
    body_style = ParagraphStyle(
        "Body",
        parent=styles["BodyText"],
        fontName=pdf_font,
        fontSize=10,
        leading=15,
        textColor=colors.HexColor("#333333"),
        wordWrap="CJK",
    )
    original_style = ParagraphStyle(
        "Original",
        parent=body_style,
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#777777"),
    )
    link_style = ParagraphStyle(
        "Link",
        parent=body_style,
        fontSize=8,
        leading=11,
        textColor=colors.HexColor("#35618a"),
    )

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=14 * mm,
        bottomMargin=14 * mm,
        title=APP_TITLE,
    )
    story = [
        Paragraph(APP_TITLE, title_style),
        Paragraph(f"\u751f\u6210\u65f6\u95f4\uff1a{datetime.now().strftime('%Y-%m-%d %H:%M')}  |  \u5171 {len(news)} \u6761", subtitle_style),
    ]

    for index, item in enumerate(news, 1):
        summary = build_summary(item)
        rows = [
            [Paragraph(f"#{index:02d}  {pdf_safe(item.get('source'))}", meta_style), Paragraph(pdf_safe(item.get('date')), meta_style)],
            [Paragraph(pdf_safe(item.get("title")), headline_style), ""],
            [Paragraph("\u65b0\u95fb\u5b9e\u5f55", label_style), Paragraph(pdf_safe(summary["facts"]), body_style)],
            [Paragraph("\u6838\u5fc3\u6570\u636e", label_style), Paragraph(pdf_safe(summary["data"]), body_style)],
        ]
        if item.get("original_title"):
            rows.append([Paragraph("\u539f\u9898", label_style), Paragraph(pdf_safe(item.get("original_title")), original_style)])
        rows.append([Paragraph("\u94fe\u63a5", label_style), Paragraph(pdf_safe(item.get("resolved_url") or item.get("url")), link_style)])

        table = Table(rows, colWidths=[22 * mm, 148 * mm])
        table.setStyle(TableStyle([
            ("SPAN", (0, 1), (1, 1)),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffdf7")),
            ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#d8c7a6")),
            ("LINEBELOW", (0, 0), (-1, 0), 0.4, colors.HexColor("#eadfca")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.extend([table, Spacer(1, 6)])

    doc.build(story)


class NewsApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("980x760")
        self.minsize(820, 620)
        self.configure(bg="#f4f1ea")
        self.current_news = []
        self._configure_styles()
        self._build_layout()
        self.refresh_news()

    def _configure_styles(self):
        self.style = ttk.Style(self)
        self.style.theme_use("clam")
        font = "Microsoft YaHei UI"
        self.style.configure("Header.TFrame", background="#171717")
        self.style.configure("Body.TFrame", background="#f4f1ea")
        self.style.configure("Card.TFrame", background="#fffdf7", relief="flat")
        self.style.configure("Title.TLabel", background="#171717", foreground="#f8f1df", font=(font, 22, "bold"))
        self.style.configure("Sub.TLabel", background="#171717", foreground="#b9ad95", font=(font, 10))
        self.style.configure("CardTitle.TLabel", background="#fffdf7", foreground="#171717", font=(font, 12, "bold"), wraplength=760)
        self.style.configure("Meta.TLabel", background="#fffdf7", foreground="#8b7355", font=(font, 9))
        self.style.configure("Status.TLabel", background="#f4f1ea", foreground="#6f624e", font=(font, 10))
        self.style.configure("Primary.TButton", font=(font, 10, "bold"), padding=(14, 8))
        self.style.configure("Link.TButton", font=(font, 9), padding=(10, 5))

    def _build_layout(self):
        header = ttk.Frame(self, style="Header.TFrame", padding=(28, 24, 28, 22))
        header.pack(fill="x")
        title_row = ttk.Frame(header, style="Header.TFrame")
        title_row.pack(fill="x")
        left = ttk.Frame(title_row, style="Header.TFrame")
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text=APP_TITLE, style="Title.TLabel").pack(anchor="w")
        ttk.Label(left, text=SUBTITLE, style="Sub.TLabel").pack(anchor="w", pady=(6, 0))
        actions = ttk.Frame(title_row, style="Header.TFrame")
        actions.pack(side="right")
        self.pdf_button = ttk.Button(actions, text="\u751f\u6210PDF", style="Primary.TButton", command=self.export_pdf, state="disabled")
        self.pdf_button.pack(side="left", padx=(0, 10))
        self.refresh_button = ttk.Button(actions, text="\u5237\u65b0\u5185\u53c2", style="Primary.TButton", command=self.refresh_news)
        self.refresh_button.pack(side="left")
        body = ttk.Frame(self, style="Body.TFrame", padding=(24, 18, 24, 12))
        body.pack(fill="both", expand=True)
        self.status_var = tk.StringVar(value="\u51c6\u5907\u5c31\u7eea")
        ttk.Label(body, textvariable=self.status_var, style="Status.TLabel").pack(anchor="w", pady=(0, 12))
        self.canvas = tk.Canvas(body, bg="#f4f1ea", highlightthickness=0)
        scrollbar = ttk.Scrollbar(body, orient="vertical", command=self.canvas.yview)
        self.cards_frame = ttk.Frame(self.canvas, style="Body.TFrame")
        self.cards_window = self.canvas.create_window((0, 0), window=self.cards_frame, anchor="nw")
        self.cards_frame.bind("<Configure>", self._on_frame_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

    def _on_frame_configure(self, _event=None):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.cards_window, width=event.width)

    def set_status(self, message):
        self.after(0, lambda: self.status_var.set(message))

    def refresh_news(self):
        self.refresh_button.configure(state="disabled")
        self.pdf_button.configure(state="disabled")
        self.status_var.set("\u6b63\u5728\u8fde\u63a5\u65b0\u95fb\u6e90...")
        self._clear_cards()
        self._add_loading_card()
        threading.Thread(target=self._load_news_worker, daemon=True).start()

    def _load_news_worker(self):
        try:
            news = fetch_ai_hardware_news(self.set_status)
            self.after(0, lambda: self._render_news(news))
        except Exception as exc:
            self.after(0, lambda: self._show_error(exc))

    def _clear_cards(self):
        for child in self.cards_frame.winfo_children():
            child.destroy()

    def _add_loading_card(self):
        card = ttk.Frame(self.cards_frame, style="Card.TFrame", padding=(18, 18))
        card.pack(fill="x", pady=(0, 12))
        ttk.Label(card, text="\u6b63\u5728\u6293\u53d6\u548c\u7ffb\u8bd1\u65b0\u95fb\uff0c\u8bf7\u7a0d\u7b49...", style="CardTitle.TLabel").pack(anchor="w")

    def _render_news(self, news):
        self._clear_cards()
        self.current_news = news
        self.refresh_button.configure(state="normal")
        self.pdf_button.configure(state="normal" if news else "disabled")
        if not news:
            self.status_var.set("\u6ca1\u6709\u6293\u5230\u65b0\u95fb\uff0c\u8bf7\u68c0\u67e5\u7f51\u7edc\u540e\u91cd\u8bd5\u3002")
            self._add_empty_card()
            return
        self.status_var.set(f"\u5df2\u66f4\u65b0 {len(news)} \u6761 | {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        for index, item in enumerate(news, 1):
            self._add_news_card(index, item)

    def _add_empty_card(self):
        card = ttk.Frame(self.cards_frame, style="Card.TFrame", padding=(18, 18))
        card.pack(fill="x", pady=(0, 12))
        ttk.Label(card, text="\u5f53\u524d\u7f51\u7edc\u73af\u5883\u4e0b\u672a\u6293\u53d6\u5230\u66f4\u65b0\u3002", style="CardTitle.TLabel").pack(anchor="w")

    def _add_news_card(self, index, item):
        outer = tk.Frame(self.cards_frame, bg="#d8c7a6")
        outer.pack(fill="x", pady=(0, 14))
        card = ttk.Frame(outer, style="Card.TFrame", padding=(18, 16))
        card.pack(fill="x", pady=(0, 2))
        meta = f"#{index:02d}  {item['source']}"
        if item.get("date"):
            meta += f"  |  {item['date']}"
        ttk.Label(card, text=meta, style="Meta.TLabel").pack(anchor="w")
        ttk.Label(card, text=item["title"], style="CardTitle.TLabel").pack(anchor="w", pady=(8, 6))
        if item.get("original_title"):
            ttk.Label(card, text=item["original_title"], style="Meta.TLabel", wraplength=760).pack(anchor="w", pady=(0, 10))
        button_row = ttk.Frame(card, style="Card.TFrame")
        button_row.pack(fill="x")
        ttk.Button(button_row, text="\u6253\u5f00\u539f\u6587", style="Link.TButton", command=lambda url=item["url"]: webbrowser.open(url)).pack(side="left")

    def export_pdf(self):
        if not self.current_news:
            messagebox.showinfo(APP_TITLE, "\u8bf7\u5148\u5237\u65b0\u6293\u53d6\u65b0\u95fb\u3002")
            return
        self.pdf_button.configure(state="disabled", text="\u751f\u6210\u4e2d...")
        self.status_var.set("\u6b63\u5728\u751f\u6210 PDF...")
        threading.Thread(target=self._export_pdf_worker, daemon=True).start()

    def _export_pdf_worker(self):
        reports_dir = os.path.join(app_base_dir(), "reports")
        os.makedirs(reports_dir, exist_ok=True)
        filename = f"AI_Hardware_News_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"
        output_path = os.path.join(reports_dir, filename)
        try:
            pdf_news = enrich_articles_for_pdf(self.current_news, self.set_status)
            generate_pdf_report(pdf_news, output_path)
        except Exception as exc:
            log_path = os.path.join(reports_dir, "pdf_error.log")
            with open(log_path, "a", encoding="utf-8") as log_file:
                log_file.write(f"{datetime.now().isoformat()} {exc}\n")
            self.after(0, lambda: self._pdf_failed(exc))
            return
        self.after(0, lambda: self._pdf_done(output_path))

    def _pdf_done(self, output_path):
        self.pdf_button.configure(state="normal", text="\u751f\u6210PDF")
        self.status_var.set(f"PDF \u5df2\u751f\u6210\uff1a{output_path}")
        try:
            os.startfile(os.path.dirname(output_path))
        except Exception:
            pass
        messagebox.showinfo(APP_TITLE, f"PDF \u5df2\u751f\u6210\uff1a\n{output_path}")

    def _pdf_failed(self, exc):
        self.pdf_button.configure(state="normal", text="\u751f\u6210PDF")
        self.status_var.set("PDF \u751f\u6210\u5931\u8d25")
        messagebox.showerror(APP_TITLE, f"PDF \u751f\u6210\u5931\u8d25\uff1a\n{exc}")

    def _show_error(self, exc):
        self._clear_cards()
        self.refresh_button.configure(state="normal")
        self.status_var.set("\u6293\u53d6\u5931\u8d25")
        messagebox.showerror(APP_TITLE, f"\u6293\u53d6\u65b0\u95fb\u5931\u8d25\uff1a\n{exc}")
        self._add_empty_card()


if __name__ == "__main__":
    app = NewsApp()
    app.mainloop()
