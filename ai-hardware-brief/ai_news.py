from datetime import datetime
from urllib.parse import quote_plus
import xml.etree.ElementTree as ET

import requests
from deep_translator import GoogleTranslator
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()
translator = GoogleTranslator(source="auto", target="zh-CN")

QUERIES = [
    "AI hardware NVIDIA Blackwell GPU chips robotics funding",
    "AI chips semiconductor accelerator startup funding",
    "NVIDIA AMD Intel AI hardware data center chip news",
    "robotics AI hardware humanoid robot chip sensor funding",
    "edge AI device NPU inference chip hardware startup",
    "China AI chip hardware robot semiconductor latest news",
]

TARGET_COUNT = 12
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
}


def translate_text(text):
    """Translate text safely; return original text if translation fails."""
    if not text:
        return ""
    try:
        return translator.translate(text[:1000])
    except Exception:
        return text


def google_news_url(query, days):
    q = quote_plus(f"{query} when:{days}d")
    return f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en"


def clean_google_url(url):
    # Google News RSS links are redirect links. Keep them clickable and stable.
    return url or ""


def fetch_google_news(days):
    news = []
    seen = set()

    for query in QUERIES:
        if len(news) >= TARGET_COUNT:
            break

        url = google_news_url(query, days)
        try:
            response = requests.get(url, headers=HEADERS, timeout=20)
            response.raise_for_status()
            root = ET.fromstring(response.content)
        except Exception as e:
            console.print(f"[dim]跳过一个新闻源: {e}[/dim]")
            continue

        for item in root.findall(".//item"):
            title = item.findtext("title") or "无标题"
            link = clean_google_url(item.findtext("link"))
            source_node = item.find("source")
            source = source_node.text if source_node is not None and source_node.text else "Google News"
            published = item.findtext("pubDate") or ""

            key = link or title
            if not key or key in seen:
                continue

            seen.add(key)
            news.append({
                "title": translate_text(title),
                "source": source,
                "url": link,
                "date": published,
            })

            if len(news) >= TARGET_COUNT:
                break

    return news


def fetch_ai_hardware_news():
    console.print("[dim]正在搜索全球 AI 硬件动态，先看过去 24 小时...[/dim]")
    news = fetch_google_news(1)

    if len(news) < 6:
        console.print("[dim]24 小时内结果偏少，自动扩展到最近一周...[/dim]")
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

    return news[:TARGET_COUNT]


def main():
    console.print(Panel(
        f"[bold magenta]象哥 AI 硬件投资内参[/bold magenta]\n[dim]生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}[/dim]",
        expand=False,
        border_style="magenta",
    ))

    news = fetch_ai_hardware_news()

    if not news:
        console.print("[yellow]当前网络环境下未抓取到更新，请检查网络或稍后再试。[/yellow]")
        return

    table = Table(show_header=True, header_style="bold cyan", box=None)
    table.add_column("序号", width=4, justify="right")
    table.add_column("来源", width=18)
    table.add_column("核心动态 (中文翻译)")

    for index, item in enumerate(news, 1):
        table.add_row(
            str(index),
            f"[{item['source']}]",
            f"[bold]{item['title']}[/bold]\n[link={item['url']}][dim]{item['url']}[/dim][/link]",
        )

    console.print(table)
    console.print("\n[italic blue]提示：默认先抓过去 24 小时；少于 6 条时自动扩展到最近一周。[/italic blue]")


if __name__ == "__main__":
    main()
