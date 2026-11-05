#!/usr/bin/env python3
"""銅建値チェック
JX金属「銅建値」ページ（https://www.jx-nmm.com/cuprice/）から改定履歴を取得し、
docs/data.json を更新する。建値が改定されていたら ntfy でスマホへ通知する。
標準ライブラリだけで動く（追加インストール不要）。

環境変数
  NTFY_TOPIC   通知先トピック（未設定なら docs/config.json の ntfyTopic）
  TEST_NOTIFY  "true" ならテスト通知を1件送る
  CUPRICE_HTML 動作確認用：ページの代わりに読むローカルHTMLファイル
"""
import datetime as dt
import html
import json
import os
import re
import sys
import time
import unicodedata
import urllib.request

URL = "https://www.jx-nmm.com/cuprice/"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "docs", "data.json")
CONFIG = os.path.join(ROOT, "docs", "config.json")
KEEP = 120  # data.json に残す改定回数
JST = dt.timezone(dt.timedelta(hours=9))


def log(*a):
    print(*a, flush=True)


# ------------------------------------------------------------------ 取得
def download(url: str) -> str:
    local = os.environ.get("CUPRICE_HTML")
    if local:
        with open(local, "rb") as f:
            raw = f.read()
    else:
        last = None
        for i in range(3):
            try:
                req = urllib.request.Request(url, headers={
                    "User-Agent": "Mozilla/5.0 (compatible; CuPriceChecker/1.0)",
                    "Accept-Language": "ja,en;q=0.5",
                })
                with urllib.request.urlopen(req, timeout=30) as r:
                    raw = r.read()
                break
            except Exception as e:  # 一時的な失敗は少し待って再試行
                last = e
                log(f"取得失敗 {i + 1}回目: {e}")
                time.sleep(10 * (i + 1))
        else:
            raise RuntimeError(f"JX金属のページに接続できませんでした: {last}")
    m = re.search(rb'charset=["\']?([\w-]+)', raw[:3000], re.I)
    enc = (m.group(1).decode() if m else "utf-8").lower()
    if enc in ("shift_jis", "sjis", "x-sjis"):
        enc = "cp932"
    try:
        return raw.decode(enc)
    except (LookupError, UnicodeDecodeError):
        return raw.decode("utf-8", errors="replace")


# ------------------------------------------------------------------ 解析
RE_YEAR = re.compile(r"^((?:19|20)\d{2})年$")
RE_DATE = re.compile(r"^(?:((?:19|20)\d{2})年)?(\d{1,2})月(\d{1,2})日(.*)$")


def to_price(s: str):
    s = re.sub(r"[,円¥￥\s]|/t|/トン", "", s)
    if s.isdigit() and len(s) <= 9:
        n = int(s)
        if 100_000 <= n <= 20_000_000:  # 円/トンとしてあり得る範囲
            return n
    return None


def parse(page: str, today: dt.date):
    t = re.sub(r"(?is)<(script|style|noscript)\b.*?</\1>", " ", page)
    t = re.sub(r"(?s)<!--.*?-->", " ", t)
    t = re.sub(r"<[^>]+>", "\n", t)
    t = unicodedata.normalize("NFKC", html.unescape(t))
    tokens = [re.sub(r"\s+", "", x) for x in t.split("\n")]
    tokens = [x for x in tokens if x]

    start = next((i for i, x in enumerate(tokens) if "改定の履歴" in x), -1)
    if start >= 0:
        tokens = tokens[start + 1:]

    year = None
    pending = None
    found = {}
    for tok in tokens:
        m = RE_YEAR.match(tok)
        if m:
            year, pending = int(m.group(1)), None
            continue
        m = RE_DATE.match(tok)
        if m:
            y = int(m.group(1)) if m.group(1) else year
            row = (y, int(m.group(2)), int(m.group(3)))
            p = to_price(m.group(4)) if m.group(4) else None
            if p:
                found[row] = p
                pending = None
            else:
                pending = row
            continue
        p = to_price(tok)
        if p and pending:
            found[pending] = p
            pending = None

    out = {}
    for (y, mo, d), p in found.items():
        if y is None:  # 年が書かれていなければ今年（未来の月なら昨年）
            y = today.year - (1 if mo > today.month else 0)
        try:
            day = dt.date(y, mo, d)
        except ValueError:
            continue
        if day <= today + dt.timedelta(days=7):
            out[day] = p
    return sorted(out.items())


# ------------------------------------------------------------------ 通知
def notify(topic: str, title: str, message: str, tags, click: str, priority: int = 4):
    if not topic:
        log("NTFY_TOPIC が未設定のため通知しません")
        return
    body = json.dumps({
        "topic": topic, "title": title, "message": message,
        "tags": tags, "priority": priority, "click": click,
    }).encode("utf-8")
    req = urllib.request.Request("https://ntfy.sh/", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            log("通知を送信しました:", r.status)
    except Exception as e:  # 通知に失敗してもデータ更新は続ける
        log("通知の送信に失敗:", e)


def yen(n: int) -> str:
    return f"{n:,}"


def site_url() -> str:
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    if "/" in repo:
        owner, name = repo.split("/", 1)
        return f"https://{owner.lower()}.github.io/{name}/"
    return URL


# ------------------------------------------------------------------ 本体
def main():
    now = dt.datetime.now(JST)
    cfg = {}
    if os.path.exists(CONFIG):
        with open(CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
    topic = os.environ.get("NTFY_TOPIC") or cfg.get("ntfyTopic", "")
    click = site_url()

    if os.environ.get("TEST_NOTIFY", "").lower() == "true":
        notify(topic, "銅建値アプリ：テスト通知", "この通知が届けば設定は完了です。建値が改定されると、ここにお知らせが届きます。",
               ["bell"], click, 3)

    rows = parse(download(URL), now.date())
    log(f"取得した改定履歴: {len(rows)}件", f"最新 {rows[-1][0]} {yen(rows[-1][1])}円" if rows else "")
    if len(rows) < 3:
        sys.exit("建値の表が見つかりません（JX金属のページのつくりが変わった可能性があります）")

    old = {}
    if os.path.exists(DATA):
        with open(DATA, encoding="utf-8") as f:
            old = json.load(f)
    hist = {dt.date.fromisoformat(r["date"]): r["price"] for r in old.get("history", [])}
    before = sorted(hist.items())
    hist.update(dict(rows))  # 過去分は残しつつ、取得した分で上書き
    merged = sorted(hist.items())[-KEEP:]

    if merged == before[-KEEP:]:
        log("改定なし")
        return

    data = {
        "source": URL,
        "unit": "円/t",
        "updatedAt": now.isoformat(timespec="minutes"),
        "history": [{"date": d.isoformat(), "price": p} for d, p in merged],
    }
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
        f.write("\n")
    log("data.json を更新しました")

    if not before:
        log("初回のため通知はしません")
        return
    (d1, p1) = merged[-1]
    (d0, p0) = before[-1]
    if (d1, p1) == (d0, p0):
        log("最新の建値に変化なし（過去分の修正のみ）")
        return
    prev = merged[-2][1] if len(merged) >= 2 else p0
    diff = p1 - prev
    mark = f"▲{yen(diff)}" if diff > 0 else (f"▼{yen(-diff)}" if diff < 0 else "±0")
    tag = "chart_with_upwards_trend" if diff > 0 else ("chart_with_downwards_trend" if diff < 0 else "bar_chart")
    notify(topic,
           f"銅建値 {yen(p1)}円/t（{mark}）",
           f"{d1.month}月{d1.day}日改定　{yen(p1 // 1000)}円/kg\n前回 {yen(prev)}円/t から {mark}円",
           [tag], click)


if __name__ == "__main__":
    main()
