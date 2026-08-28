"""User-editable settings for the daily A-share briefing service."""
from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any

BASE_DIR = Path(os.getenv("A_STOCK_BRIEFING_DIR") or Path(__file__).resolve().parent)
DATA_DIR = BASE_DIR / "data"
SETTINGS_FILE = DATA_DIR / "service_settings.json"

DEFAULT_RECIPIENTS: list[str] = []
DEFAULT_SMTP_SETTINGS = {
    "host": "smtp.qq.com",
    "port": 465,
    "user": "",
    "auth_code": "",
}
DEFAULT_LLM_API_SETTINGS = {
    "base_url": "",
    "api_key": "",
    "model": "",
}
OPENAI_ENDPOINT_SUFFIXES = (
    "/chat/completions",
    "/responses",
    "/completions",
    "/models",
)

DEFAULT_EMAIL_SCHEDULE = [
    {
        "mode": "premarket",
        "task_name": "A股盘前简报",
        "time": "09:35",
        "title": "盘前简报",
        "content": "外盘、宏观日历、昨晚公告、新股、解禁、早评、持仓/关注股票盘前提醒",
    },
    {
        "mode": "midday",
        "task_name": "A股午间简报",
        "time": "11:45",
        "title": "午间简报",
        "content": "上午盘面、板块轮动、财联社实时快讯、持仓/关注股票异动",
    },
    {
        "mode": "close",
        "task_name": "A股收盘总结",
        "time": "18:00",
        "title": "收盘总结",
        "content": "收盘核心数据、两市大宗交易汇总、当日龙虎榜完整榜单、持仓盈亏总结",
    },
    {
        "mode": "monitor",
        "task_name": "A股盘中监控",
        "time": "09:35-11:30, 13:05-15:00 / 每5分钟",
        "title": "重要异动提醒",
        "content": "仅重要异动额外发信；两封至少间隔60分钟；全天最多3封",
    },
]

DEFAULT_STOCKS: list[dict[str, Any]] = []


def parse_recipients(value: Any) -> list[str]:
    """Parse recipient emails from a string or list while preserving order."""
    if isinstance(value, str):
        parts = re.split(r"[,;，；\s]+", value)
    elif isinstance(value, list):
        parts = []
        for item in value:
            parts.extend(parse_recipients(item))
    else:
        parts = []

    recipients: list[str] = []
    seen: set[str] = set()
    for part in parts:
        email = str(part).strip()
        if not email or "@" not in email:
            continue
        key = email.casefold()
        if key in seen:
            continue
        seen.add(key)
        recipients.append(email)
    return recipients


def _infer_suffix(code: str) -> str:
    if code.startswith(("5", "6", "9")):
        return "SS"
    if code.startswith(("4", "8")):
        return "BJ"
    return "SZ"


def _split_code(value: Any) -> tuple[str, str]:
    raw = str(value or "").strip().upper().replace(" ", "")
    if raw.startswith(("SH", "SZ", "BJ")) and len(raw) >= 8:
        prefix = raw[:2]
        code = raw[2:]
        suffix = "SS" if prefix == "SH" else prefix
    elif "." in raw:
        code, suffix = raw.split(".", 1)
        suffix = "SS" if suffix == "SH" else suffix
    else:
        code = raw
        suffix = _infer_suffix(code)

    if not re.fullmatch(r"\d{6}", code):
        raise ValueError(f"Invalid A-share stock code: {value}")
    if suffix not in {"SS", "SZ", "BJ"}:
        raise ValueError(f"Invalid A-share suffix: {suffix}")
    return code, suffix


def _to_int(value: Any, default: int = 0) -> int:
    if value in (None, ""):
        return default
    try:
        return max(int(float(str(value).replace(",", ""))), 0)
    except (TypeError, ValueError):
        return default


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _clean_text(value: Any) -> str:
    return str(value or "").strip()


def normalize_openai_base_url(value: Any) -> str:
    base_url = _clean_text(value).rstrip("/")
    lowered = base_url.casefold()
    for suffix in OPENAI_ENDPOINT_SUFFIXES:
        if lowered.endswith(suffix):
            return base_url[: -len(suffix)].rstrip("/")
    return base_url


def normalize_llm_api_settings(
    value: dict[str, Any] | None,
    *,
    fallback: dict[str, Any] | None = None,
) -> dict[str, str]:
    raw = value if isinstance(value, dict) else {}
    fallback = fallback if isinstance(fallback, dict) else {}
    base_url = normalize_openai_base_url(raw.get("base_url") or fallback.get("base_url"))
    api_key = _clean_text(raw.get("api_key") or fallback.get("api_key"))
    model = _clean_text(raw.get("model") or fallback.get("model"))
    return {
        "base_url": base_url,
        "api_key": api_key,
        "model": model,
    }


def normalize_smtp_settings(
    value: dict[str, Any] | None,
    *,
    fallback: dict[str, Any] | None = None,
) -> dict[str, Any]:
    raw = value if isinstance(value, dict) else {}
    fallback = fallback if isinstance(fallback, dict) else {}
    return {
        "host": _clean_text(raw.get("host") or fallback.get("host") or DEFAULT_SMTP_SETTINGS["host"]),
        "port": _to_int(raw.get("port") or fallback.get("port"), DEFAULT_SMTP_SETTINGS["port"]),
        "user": _clean_text(raw.get("user") or fallback.get("user")),
        "auth_code": _clean_text(raw.get("auth_code") or fallback.get("auth_code")),
    }


def redact_secret(value: Any, *, visible_prefix: int = 3, visible_suffix: int = 4) -> str:
    secret = _clean_text(value)
    if not secret:
        return ""
    if len(secret) <= visible_prefix + visible_suffix:
        return "*" * len(secret)
    hidden_count = len(secret) - visible_prefix - visible_suffix
    return f"{secret[:visible_prefix]}{'*' * hidden_count}{secret[-visible_suffix:]}"


def normalize_stock(item: dict[str, Any]) -> dict[str, Any]:
    code, suffix = _split_code(item.get("code") or item.get("full_code"))
    cost = _to_float(item.get("cost"))
    normalized = {
        "code": code,
        "suffix": suffix,
        "full_code": f"{code}.{suffix}",
        "name": str(item.get("name") or code).strip(),
        "shares": _to_int(item.get("shares")),
        "cost": cost if cost is not None else 0.0,
        "risk": _to_float(item.get("risk")),
        "risk2": _to_float(item.get("risk2")),
        "clear": _to_float(item.get("clear")),
        "hard_stop": _to_float(item.get("hard_stop")),
        "reduce_low": _to_float(item.get("reduce_low")),
        "reduce_high": _to_float(item.get("reduce_high")),
        "enabled": bool(item.get("enabled", True)),
    }
    return normalized


def normalize_settings(settings: dict[str, Any] | None, *, env_recipients: Any = "") -> dict[str, Any]:
    raw = settings or {}
    if "recipients" in raw:
        recipients = parse_recipients(raw.get("recipients"))
    else:
        recipients = parse_recipients(env_recipients) or DEFAULT_RECIPIENTS

    stocks = []
    seen_codes: set[str] = set()
    stock_source = raw["stocks"] if isinstance(raw.get("stocks"), list) else DEFAULT_STOCKS
    for item in stock_source:
        try:
            stock = normalize_stock(item)
        except ValueError:
            continue
        key = stock["full_code"]
        if key in seen_codes:
            continue
        seen_codes.add(key)
        stocks.append(stock)

    return {
        "version": 1,
        "recipients": recipients,
        "smtp": normalize_smtp_settings(raw.get("smtp")),
        "llm_api": normalize_llm_api_settings(raw.get("llm_api")),
        "schedule": deepcopy(DEFAULT_EMAIL_SCHEDULE),
        "stocks": stocks,
    }


def default_settings(*, env_recipients: Any = "") -> dict[str, Any]:
    return normalize_settings({}, env_recipients=env_recipients)


def load_settings(*, path: Path | str = SETTINGS_FILE, env_recipients: Any = "") -> dict[str, Any]:
    settings_path = Path(path)
    if not settings_path.exists():
        return default_settings(env_recipients=env_recipients)
    try:
        raw = json.loads(settings_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        raw = {}
    return normalize_settings(raw, env_recipients=env_recipients)


def save_settings(settings: dict[str, Any], *, path: Path | str = SETTINGS_FILE) -> dict[str, Any]:
    normalized = normalize_settings(settings)
    settings_path = Path(path)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    settings_path.write_text(
        json.dumps(normalized, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized


def _risk_from_stock(stock: dict[str, Any]) -> dict[str, Any]:
    risk = {"name": stock.get("name") or stock.get("code")}
    for key in ("risk", "risk2", "clear", "hard_stop"):
        if stock.get(key) is not None:
            risk[key] = stock[key]
    if stock.get("reduce_low") is not None and stock.get("reduce_high") is not None:
        risk["reduce_zone"] = (stock["reduce_low"], stock["reduce_high"])
    return risk


def settings_to_position_risk_lines(settings: dict[str, Any]) -> dict[str, dict[str, Any]]:
    lines = {}
    for stock in normalize_settings(settings).get("stocks", []):
        if stock.get("enabled", True):
            lines[stock["code"]] = _risk_from_stock(stock)
    return lines


def settings_to_stock_rows(settings: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for stock in normalize_settings(settings).get("stocks", []):
        if not stock.get("enabled", True):
            continue
        row = dict(stock)
        row["risk"] = _risk_from_stock(stock)
        row["watch_only"] = not row.get("shares") or not row.get("cost")
        rows.append(row)
    return rows


def settings_to_recipients(settings: dict[str, Any], *, fallback: Any = "") -> list[str]:
    if settings and "recipients" in settings:
        return parse_recipients(settings.get("recipients"))
    return parse_recipients(fallback)


def settings_to_llm_api_settings(
    settings: dict[str, Any],
    *,
    env_base_url: Any = "",
    env_api_key: Any = "",
    env_model: Any = "",
) -> dict[str, str]:
    fallback = {
        "base_url": env_base_url,
        "api_key": env_api_key,
        "model": env_model,
    }
    raw = settings.get("llm_api") if isinstance(settings, dict) else {}
    return normalize_llm_api_settings(raw, fallback=fallback)


def settings_to_smtp_settings(
    settings: dict[str, Any],
    *,
    env_host: Any = "",
    env_port: Any = "",
    env_user: Any = "",
    env_auth_code: Any = "",
) -> dict[str, Any]:
    fallback = {
        "host": env_host,
        "port": env_port,
        "user": env_user,
        "auth_code": env_auth_code,
    }
    raw = settings.get("smtp") if isinstance(settings, dict) else {}
    return normalize_smtp_settings(raw, fallback=fallback)
