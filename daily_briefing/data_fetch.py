"""数据抓取层：腾讯行情、东财数据中心、财联社快讯、板块涨跌。"""
import hashlib
import re
import time
import urllib.request
from datetime import datetime

import config
import requests

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"


def _get(url: str, params: dict | None = None, referer: str = "") -> requests.Response:
    headers = {"User-Agent": UA}
    if referer:
        headers["Referer"] = referer
    last_error = None
    for attempt in range(3):
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=20)
            resp.raise_for_status()
            return resp
        except Exception as exc:
            last_error = exc
            time.sleep(0.6 * (attempt + 1))
    raise last_error


def _json(url: str, params: dict | None = None, referer: str = "") -> dict:
    return _get(url, params, referer).json()


def _float(value, default: float = 0.0) -> float:
    try:
        if value in (None, "", "-", "--"):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _str(value, default: str = "") -> str:
    if value is None:
        return default
    return str(value)


def _safe_list(value) -> list:
    return value if isinstance(value, list) else []


def _em_report(report_name: str, filter_str: str, sort_columns: str = "", sort_types: str = "-1", page_size: int = 500, page_number: int = 1) -> list[dict]:
    """东方财富统一数据中心查询。"""
    params = {
        "reportName": report_name,
        "columns": "ALL",
        "filter": filter_str,
        "pageNumber": str(page_number),
        "pageSize": str(page_size),
        "sortColumns": sort_columns,
        "sortTypes": sort_types,
        "source": "WEB",
        "client": "WEB",
    }
    data = _json("https://datacenter-web.eastmoney.com/api/data/v1/get", params, "https://data.eastmoney.com/")
    result = data.get("result") or {}
    return result.get("data") or []


def _normalize_tencent_code(code: str) -> str:
    code = code.strip().upper()
    if code.endswith(".SH") or code.endswith(".SS"):
        return "sh" + code.split(".")[0]
    if code.endswith(".SZ"):
        return "sz" + code.split(".")[0]
    if code.endswith(".BJ"):
        return "bj" + code.split(".")[0]
    if re.fullmatch(r"\d{6}", code):
        if code.startswith(("5", "6", "9")):
            return "sh" + code
        if code.startswith(("0", "3", "2")):
            return "sz" + code
        if code.startswith(("4", "8")):
            return "bj" + code
        return "sz" + code
    return code


def fetch_tencent_quotes(codes: list[str]) -> dict[str, dict]:
    """抓取腾讯行情。codes 可为 6 位代码、sz000001 或港股美股代码。"""
    codes = [c for c in codes if c]
    if not codes:
        return {}
    url = "https://qt.gtimg.cn/q=" + ",".join(codes)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    raw = urllib.request.urlopen(req, timeout=15).read().decode("gbk", "ignore")

    out: dict[str, dict] = {}
    for line in raw.strip().split(";"):
        line = line.strip()
        if "=" not in line:
            continue
        var, value = line.split("=", 1)
        fields = value.strip('"').split("~")
        if len(fields) < 35 or not fields[2]:
            continue
        key = var.replace("v_", "")
        item = {
            "tencent_code": key,
            "name": fields[1],
            "code": fields[2],
            "price": _float(fields[3]),
            "prev_close": _float(fields[4]),
            "open": _float(fields[5]),
            "change": _float(fields[31]),
            "change_pct": _float(fields[32]),
            "high": _float(fields[33]),
            "low": _float(fields[34]),
            "volume_hand": _float(fields[36]),
            "amount_wan": _float(fields[37]),
            "turnover_pct": _float(fields[38]),
            "pe": _float(fields[39]),
            "amplitude_pct": _float(fields[43]) if len(fields) > 43 else 0.0,
            "quote_time": fields[30] if len(fields) > 30 else "",
        }
        out[key] = item
    return out


def _parse_holdings_md() -> list[dict]:
    path = config.HOLDINGS_FILE
    if not path.exists():
        return []
    rows = []
    text = path.read_text(encoding="utf-8")
    for line in text.splitlines():
        m = re.match(r"\|\s*(\d{6})\.(SH|SS|SZ|BJ)\s*\|\s*([\d,]+)\s*\|\s*([\d.]+)\s*\|", line)
        if not m:
            continue
        code, suffix, shares, cost = m.groups()
        rows.append({"code": code, "suffix": suffix, "shares": _int(shares.replace(",", "")), "cost": _float(cost)})
    return rows


def get_holdings() -> list[dict]:
    """从持仓 Markdown 解析持仓，并补上中文名与风控线。"""
    configured_stocks = getattr(config, "WATCHLIST_STOCKS", [])
    if configured_stocks:
        rows = []
        for stock in configured_stocks:
            if not stock.get("enabled", True):
                continue
            row = dict(stock)
            row["watch_only"] = bool(row.get("watch_only")) or not row.get("shares") or not row.get("cost")
            rows.append(row)
        return rows

    rows = _parse_holdings_md()
    for row in rows:
        risk = config.POSITION_RISK_LINES.get(row["code"], {})
        row["name"] = risk.get("name") or row["code"]
        row["risk"] = risk
        row["full_code"] = f'{row["code"]}.{row["suffix"]}'
    return rows


def fetch_market_snapshot() -> dict:
    """指数、外盘与持仓合并快照。"""
    index_codes = ["sh000001", "sz399001", "sh000300", "sz399006"]
    overseas_codes = ["hkHSI", "usDJI", "usIXIC", "usINX"]
    holdings = get_holdings()
    holding_codes = [_normalize_tencent_code(h["full_code"]) for h in holdings]
    quotes = fetch_tencent_quotes(index_codes + overseas_codes + holding_codes)
    for h in holdings:
        tc = _normalize_tencent_code(h["full_code"])
        h["quote"] = quotes.get(tc, {})
    return {
        "indices": [quotes.get(c, {}) for c in index_codes],
        "overseas": [quotes.get(c, {}) for c in overseas_codes],
        "holdings": holdings,
    }


def fetch_announcements(limit: int = 30) -> list[dict]:
    """昨晚/最新 A 股公告。"""
    params = {
        "sr": "-1",
        "page_size": str(min(max(limit, 5), 100)),
        "page_index": "1",
        "ann_type": "A",
        "client_source": "web",
        "f_node": "0",
        "s_node": "0",
    }
    data = _json("https://np-anotice-stock.eastmoney.com/api/security/ann", params, "https://data.eastmoney.com/")
    result = []
    for item in (data.get("data") or {}).get("list") or []:
        codes = item.get("codes") or []
        code_names = [f'{c.get("short_name", "")}({c.get("stock_code", "")})' for c in codes[:2]]
        result.append({
            "title": item.get("title", ""),
            "display_time": item.get("display_time", ""),
            "notice_date": item.get("notice_date", ""),
            "column": ", ".join(c.get("column_name", "") for c in (item.get("columns") or [])[:2]),
            "codes": "、".join(code_names),
        })
    return result


def fetch_calendar(target_date: str | None = None) -> dict:
    """东方财富财经日历：停复牌、新股、经济数据、行业会议、股东大会等。"""
    target_date = target_date or datetime.now().strftime("%Y-%m-%d")
    params = {
        "fromdate": target_date,
        "todate": target_date,
        "option": "xsap,xgsg,tfpxx,hsgg,nbjb,jjsj,hyhy,gddh",
    }
    return _json("https://data.eastmoney.com/dataapi/dcrl/dstx", params, "https://data.eastmoney.com/dcrl/dashi.html")


def is_trading_day(date: str | None = None) -> bool:
    """用周末 + 东财休市安排判断是否为 A 股交易日。"""
    date = date or datetime.now().strftime("%Y-%m-%d")
    day = datetime.strptime(date, "%Y-%m-%d")
    if day.weekday() >= 5:
        return False
    try:
        calendar = fetch_calendar(date)
    except Exception:
        return True
    xsap = _safe_list(calendar.get("xsap"))
    for item in xsap:
        if item.get("MKT") != "A股":
            continue
        start = str(item.get("SDATE") or "")[:10]
        end = str(item.get("EDATE") or "")[:10]
        if start <= date <= end:
            return False
    return True


def fetch_new_stocks(date: str | None = None) -> dict:
    """新股申购与上市。"""
    date = date or datetime.now().strftime("%Y-%m-%d")
    applying = _em_report(
        "RPTA_APP_IPOAPPLY",
        f"(APPLY_DATE>='{date}')(APPLY_DATE<='{date}')",
        "APPLY_DATE,SECURITY_CODE",
        "-1,-1",
        100,
    )
    listing = _em_report(
        "RPTA_APP_IPOAPPLY",
        f"(LISTING_DATE>='{date}')(LISTING_DATE<='{date}')",
        "LISTING_DATE,SECURITY_CODE",
        "-1,-1",
        100,
    )
    return {"applying": applying, "listing": listing}


def fetch_unlocks(date: str | None = None) -> list[dict]:
    date = date or datetime.now().strftime("%Y-%m-%d")
    return _em_report(
        "RPT_LIFT_STAGE",
        f"(FREE_DATE>='{date}')(FREE_DATE<='{date}')",
        "FREE_RATIO",
        "-1",
        200,
    )


def fetch_dragon_tiger(date: str | None = None) -> list[dict]:
    date = date or datetime.now().strftime("%Y-%m-%d")
    rows = _em_report(
        "RPT_DAILYBILLBOARD_DETAILSNEW",
        f"(TRADE_DATE>='{date}')(TRADE_DATE<='{date}')",
        "BILLBOARD_NET_AMT",
        "-1",
        1000,
    )
    for row in rows:
        row["reason_clean"] = row.get("EXPLAIN") or row.get("EXPLANATION") or ""
    return rows


def fetch_block_trades(date: str | None = None) -> list[dict]:
    date = date or datetime.now().strftime("%Y-%m-%d")
    return _em_report(
        "RPT_DATA_BLOCKTRADE",
        f"(TRADE_DATE>='{date}')(TRADE_DATE<='{date}')",
        "DEAL_AMT",
        "-1",
        1000,
    )


def fetch_sector_leaders(limit: int = 15) -> dict:
    """行业板块领涨/领跌。"""
    base = "https://push2.eastmoney.com/api/qt/clist/get"
    common = {
        "pn": "1",
        "pz": str(limit),
        "np": "1",
        "fltt": "2",
        "invt": "2",
        "fid": "f3",
        "fs": "m:90+t:2+f:!50",
        "fields": "f12,f14,f2,f3,f8,f104,f105,f128,f140",
    }
    referer = "https://quote.eastmoney.com/center/"
    gainers = _json(base, {**common, "po": "1"}, referer)
    losers = _json(base, {**common, "po": "0"}, referer)
    return {
        "gainers": (gainers.get("data") or {}).get("diff") or [],
        "losers": (losers.get("data") or {}).get("diff") or [],
    }


def _cls_sign(params: dict) -> str:
    qs = "&".join(f"{k}={params[k]}" for k in sorted(params))
    return hashlib.md5(hashlib.sha1(qs.encode()).hexdigest().encode()).hexdigest()


def fetch_cls_news(limit: int = 30) -> list[dict]:
    params = {
        "appName": "CailianpressWeb",
        "os": "web",
        "sv": "7.7.5",
        "last_time": "",
        "refresh_type": "1",
        "rn": str(min(max(limit, 5), 100)),
    }
    sign = _cls_sign(params)
    data = _json(
        "https://www.cls.cn/v1/roll/get_roll_list",
        {**params, "sign": sign},
        "https://www.cls.cn/",
    )
    result = []
    for item in (data.get("data") or {}).get("roll_data") or []:
        subjects = "、".join(s.get("subject_name", "") for s in (item.get("subjects") or [])[:2])
        result.append({
            "time": datetime.fromtimestamp(_int(item.get("ctime"))).strftime("%H:%M") if item.get("ctime") else "",
            "content": item.get("content") or item.get("brief") or item.get("title") or "",
            "subjects": subjects,
        })
    return result


def fetch_snapshot_for_mode(mode: str, date: str | None = None) -> dict:
    """按模式抓取所需数据，返回统一 dict。"""
    date = date or datetime.now().strftime("%Y-%m-%d")
    payload = {"date": date}

    def _try(fn, default):
        try:
            return fn()
        except Exception:
            return default

    if mode in ("premarket", "midday", "close", "monitor"):
        payload["market"] = fetch_market_snapshot()

    if mode in ("premarket", "midday", "close"):
        payload["announcements"] = _try(lambda: fetch_announcements(20), [])
        payload["news"] = _try(lambda: fetch_cls_news(25), [])
        payload["sectors"] = _try(lambda: fetch_sector_leaders(12), {"gainers": [], "losers": []})

    if mode == "premarket":
        payload["calendar"] = _try(lambda: fetch_calendar(date), {})
        payload["new_stocks"] = _try(lambda: fetch_new_stocks(date), {"applying": [], "listing": []})
        payload["unlocks"] = _try(lambda: fetch_unlocks(date), [])

    if mode == "close":
        payload["dragon_tiger"] = _try(lambda: fetch_dragon_tiger(date), [])
        payload["block_trades"] = _try(lambda: fetch_block_trades(date), [])

    return payload
