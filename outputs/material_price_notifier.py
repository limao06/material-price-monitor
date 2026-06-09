#!/usr/bin/env python3
import argparse
import base64
import hashlib
import hmac
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_FILE = ROOT / "work" / "material-price-state.json"
DEFAULT_HISTORY_FILE = ROOT / "work" / "material-price-history.json"


@dataclass
class Quote:
    name: str
    display_name: str
    price: float
    unit: str
    date: str
    source: str
    source_url: str
    change_amount: float | None = None
    change_percent: float | None = None
    previous_price: float | None = None
    note: str = ""
    history_points: list[dict] = field(default_factory=list)


@dataclass
class FetchError:
    name: str
    source: str
    error: str


PLASTIC_SOURCES = [
    {
        "name": "PP",
        "display_name": "PP(拉丝)",
        "match": "PP(拉丝)",
        "url": "https://pp.100ppi.com/kx/list--13-1.html",
    },
    {
        "name": "PE",
        "display_name": "PE(LLDPE)",
        "match": "LLDPE",
        "url": "https://lldpe.100ppi.com/kx/list--13-1.html",
    },
    {
        "name": "PC",
        "display_name": "PC",
        "match": "PC",
        "url": "https://pc.100ppi.com/kx/list--13-1.html",
    },
    {
        "name": "ABS",
        "display_name": "ABS",
        "match": "ABS",
        "url": "https://abs.100ppi.com/kx/list--13-1.html",
    },
    {
        "name": "PMMA",
        "display_name": "亚克力(PMMA)",
        "match": "PMMA",
        "url": "https://pmma.100ppi.com/kx/list--13-1.html",
    },
]

METAL_SOURCES = [
    {"name": "铜", "match": "长江 1#电解铜"},
    {"name": "铝", "match": "长江 铝A00"},
]

CJYS_URL = "https://www.cjys.net/price"


def fetch_url(url: str, timeout: int = 20) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        text = resp.read().decode("utf-8", errors="replace")

    cookie_match = re.search(r'document\.cookie\s*=\s*"([^"]+)"\s*\+\s*"="\s*\+\s*([^;]+);', text)
    direct_cookie = re.search(r'var\s+_0x2\s*=\s*"([^"]+)"', text)
    if "正在进行安全检查" in text and direct_cookie:
        headers["Cookie"] = f"HW_CHECK={direct_cookie.group(1)}"
        time.sleep(0.8)
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    elif cookie_match:
        headers["Cookie"] = f"{cookie_match.group(1)}={cookie_match.group(2)}"
    return text


def strip_tags(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value)).strip()


def parse_chinese_date(month_day: str, timestamp: str | None = None) -> str:
    if timestamp:
        return timestamp[:10]
    now = datetime.now()
    m = re.search(r"(\d+)月(\d+)日", month_day)
    if not m:
        return now.strftime("%Y-%m-%d")
    return f"{now.year}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"


def load_state(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def save_state(path: Path, quotes: list[Quote]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        quote.name: {
            "price": quote.price,
            "date": quote.date,
            "source": quote.source,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
        for quote in quotes
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_history(path: Path) -> dict:
    if not path.exists():
        return {"records": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {"records": {}}
    if not isinstance(data, dict):
        return {"records": {}}
    data.setdefault("records", {})
    return data


def save_history(path: Path, history: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def update_history(history: dict, quotes: list[Quote]) -> dict:
    records = history.setdefault("records", {})
    for quote in quotes:
        for point in quote.history_points:
            point_date = point.get("date")
            point_price = point.get("price")
            if not point_date or not isinstance(point_price, (int, float)):
                continue
            daily = records.setdefault(point_date, {})
            daily[quote.name] = {
                "name": quote.name,
                "display_name": quote.display_name,
                "price": point_price,
                "unit": quote.unit,
                "source": quote.source,
                "source_url": quote.source_url,
                "change_amount": point.get("change_amount"),
                "change_percent": point.get("change_percent"),
                "saved_at": datetime.now().isoformat(timespec="seconds"),
            }
        daily = records.setdefault(quote.date, {})
        daily[quote.name] = {
            "name": quote.name,
            "display_name": quote.display_name,
            "price": quote.price,
            "unit": quote.unit,
            "source": quote.source,
            "source_url": quote.source_url,
            "change_amount": quote.change_amount,
            "change_percent": quote.change_percent,
            "previous_price": quote.previous_price,
            "saved_at": datetime.now().isoformat(timespec="seconds"),
        }
    history["updated_at"] = datetime.now().isoformat(timespec="seconds")
    return history


def trend_for(history: dict, quote: Quote, days: int = 7) -> str:
    points = []
    for date in sorted(history.get("records", {})):
        item = history["records"].get(date, {}).get(quote.name)
        if item and isinstance(item.get("price"), (int, float)):
            points.append((date, float(item["price"])))
    points = points[-days:]
    if len(points) < 2:
        return "暂无"
    first_date, first_price = points[0]
    last_date, last_price = points[-1]
    direction = "↑" if last_price > first_price else "↓" if last_price < first_price else "→"
    delta = round(last_price - first_price, 2)
    return f"{direction} {fmt_num(delta)} ({first_date[5:]} {first_price:,.0f} -> {last_date[5:]} {last_price:,.0f})"


def summary_for(quotes: list[Quote], errors: list[FetchError]) -> str:
    up = sum(1 for quote in quotes if quote.change_amount is not None and quote.change_amount > 0)
    down = sum(1 for quote in quotes if quote.change_amount is not None and quote.change_amount < 0)
    flat = sum(1 for quote in quotes if quote.change_amount == 0)
    return f"共 {len(quotes)} 项：上涨 {up}，下跌 {down}，持平 {flat}，异常 {len(errors)}。"


def compute_change(current: float, previous: float | None) -> tuple[float | None, float | None]:
    if previous is None or previous == 0:
        return None, None
    amount = round(current - previous, 2)
    percent = round(amount / previous * 100, 2)
    return amount, percent


def parse_change_amount(value: str) -> float:
    clean = value.replace(",", "").strip()
    number_match = re.search(r"-?\d+(?:\.\d+)?", clean)
    if not number_match:
        return 0.0
    amount = abs(float(number_match.group(0)))
    if "↓" in clean or clean.startswith("-"):
        return -amount
    return amount


def fetch_plastic(source: dict, state: dict) -> Quote:
    text = fetch_url(source["url"])
    pattern = re.compile(
        r"\](?P<md>\d+月\d+日)(?P<name>[^<为]+?)为(?P<price>\d+(?:\.\d+)?)\s*"
        r"<span>(?P<timestamp>\d{4}-\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2})</span>",
        re.S,
    )
    entries = [
        {
            "name": html.unescape(m.group("name")).strip(),
            "price": float(m.group("price")),
            "date": parse_chinese_date(m.group("md"), m.group("timestamp")),
        }
        for m in pattern.finditer(text)
        if html.unescape(m.group("name")).strip() == source["match"]
    ]
    if not entries:
        raise RuntimeError(f"未在页面解析到 {source['match']} 参考价")

    current = entries[0]
    previous_price = entries[1]["price"] if len(entries) > 1 else state.get(source["name"], {}).get("price")
    change_amount, change_percent = compute_change(current["price"], previous_price)
    return Quote(
        name=source["name"],
        display_name=source["display_name"],
        price=current["price"],
        unit="元/吨",
        date=current["date"],
        source="生意社参考价",
        source_url=source["url"],
        previous_price=previous_price,
        change_amount=change_amount,
        change_percent=change_percent,
        note="均价口径采用生意社参考价，涨跌为相邻可用报价对比",
        history_points=[
            {
                "date": entry["date"],
                "price": entry["price"],
                "change_amount": compute_change(entry["price"], entries[index + 1]["price"])[0] if index + 1 < len(entries) else None,
                "change_percent": compute_change(entry["price"], entries[index + 1]["price"])[1] if index + 1 < len(entries) else None,
            }
            for index, entry in enumerate(entries)
        ],
    )


def fetch_metals() -> list[Quote]:
    text = fetch_url(CJYS_URL)
    rows = re.findall(r"<tr>(.*?)</tr>", text, flags=re.S)
    quotes: list[Quote] = []
    for row in rows:
        cells = [strip_tags(cell) for cell in re.findall(r"<td[^>]*>(.*?)</td>", row, flags=re.S)]
        if len(cells) < 9:
            continue
        product, unit, avg, change, date = cells[0], cells[3], cells[4], cells[5], cells[8]
        for source in METAL_SOURCES:
            if product == source["match"]:
                avg_price = float(avg.replace(",", ""))
                change_amount = parse_change_amount(change)
                previous = avg_price - change_amount
                _, change_percent = compute_change(avg_price, previous)
                quotes.append(
                    Quote(
                        name=source["name"],
                        display_name=product,
                        price=avg_price,
                        unit=unit,
                        date=date,
                        source="长江有色现货均价",
                        source_url=CJYS_URL,
                        previous_price=previous,
                        change_amount=change_amount,
                        change_percent=change_percent,
                        note="涨跌额来自长江有色页面，涨跌幅按昨日均价反算",
                    )
                )
    found = {quote.name for quote in quotes}
    missing = [source["name"] for source in METAL_SOURCES if source["name"] not in found]
    if missing:
        raise RuntimeError(f"未在长江有色页面解析到：{', '.join(missing)}")
    return quotes


def fmt_num(value: float | None, suffix: str = "") -> str:
    if value is None:
        return "-"
    sign = "+" if value > 0 else ""
    return f"{sign}{value:,.2f}{suffix}"


def build_markdown(quotes: list[Quote], errors: list[FetchError], history: dict) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"### 原料市场均价日报",
        f"> 触发时间：{now}",
        f"> {summary_for(quotes, errors)}",
        "",
        "| 原料 | 今日均价 | 7天趋势 | 日期 | 来源 |",
        "|---|---:|---|---|---|",
    ]
    for quote in quotes:
        lines.append(
            "| {name} | {price} {unit} | {trend} | {date} | {source} |".format(
                name=quote.display_name,
                price=f"{quote.price:,.2f}",
                unit=quote.unit,
                trend=trend_for(history, quote),
                date=quote.date,
                source=quote.source,
            )
        )
    if errors:
        lines.extend(["", "**抓取异常**"])
        for error in errors:
            lines.append(f"- {error.name}：{error.error}")
    lines.extend(
        [
            "",
            "说明：通知展示今日均价和7天趋势；涨跌额、涨跌幅继续保存到历史 JSON。",
        ]
    )
    return "\n".join(lines)


def sign_dingtalk_url(webhook: str, secret: str | None) -> str:
    if not secret:
        return webhook
    timestamp = str(round(time.time() * 1000))
    string_to_sign = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), string_to_sign, hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(digest))
    sep = "&" if "?" in webhook else "?"
    return f"{webhook}{sep}timestamp={timestamp}&sign={sign}"


def send_dingtalk(markdown: str, webhook: str, secret: str | None = None) -> None:
    url = sign_dingtalk_url(webhook, secret)
    payload = {
        "msgtype": "markdown",
        "markdown": {"title": "原料市场均价日报", "text": markdown},
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        body = resp.read().decode("utf-8", errors="replace")
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        data = {"raw": body}
    if data.get("errcode") not in (None, 0):
        raise RuntimeError(f"钉钉返回错误：{body}")


def collect_quotes(state_file: Path) -> tuple[list[Quote], list[FetchError]]:
    state = load_state(state_file)
    quotes: list[Quote] = []
    errors: list[FetchError] = []

    for source in PLASTIC_SOURCES:
        try:
            quotes.append(fetch_plastic(source, state))
        except Exception as exc:
            errors.append(FetchError(source["display_name"], "生意社", str(exc)))

    try:
        quotes.extend(fetch_metals())
    except Exception as exc:
        for source in METAL_SOURCES:
            errors.append(FetchError(source["name"], "长江有色", str(exc)))

    return quotes, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch material market average prices and notify DingTalk.")
    parser.add_argument("--webhook", default=os.getenv("DINGTALK_WEBHOOK"), help="DingTalk robot webhook URL")
    parser.add_argument("--secret", default=os.getenv("DINGTALK_SECRET"), help="DingTalk robot signature secret")
    parser.add_argument("--state-file", default=str(DEFAULT_STATE_FILE), help="Local state JSON path")
    parser.add_argument("--history-file", default=str(DEFAULT_HISTORY_FILE), help="Historical quote JSON path")
    parser.add_argument("--dry-run", action="store_true", help="Print message only, do not send DingTalk")
    parser.add_argument("--json", action="store_true", help="Print collected quote JSON")
    args = parser.parse_args()

    state_file = Path(args.state_file).expanduser().resolve()
    history_file = Path(args.history_file).expanduser().resolve()
    quotes, errors = collect_quotes(state_file)
    history = update_history(load_history(history_file), quotes)
    markdown = build_markdown(quotes, errors, history)

    if args.json:
        print(json.dumps({"quotes": [asdict(q) for q in quotes], "errors": [asdict(e) for e in errors], "history_file": str(history_file)}, ensure_ascii=False, indent=2))
    else:
        print(markdown)

    if not args.dry_run:
        if not args.webhook:
            print("\n未设置 DINGTALK_WEBHOOK，已跳过发送。", file=sys.stderr)
        else:
            send_dingtalk(markdown, args.webhook, args.secret)
            print("\n已发送到钉钉。")

    if quotes:
        save_state(state_file, quotes)
        save_history(history_file, history)
    return 0 if quotes else 2


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (urllib.error.URLError, TimeoutError, RuntimeError) as exc:
        print(f"执行失败：{exc}", file=sys.stderr)
        raise SystemExit(1)
