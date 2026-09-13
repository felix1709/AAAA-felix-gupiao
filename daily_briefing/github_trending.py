"""GitHub Trending 每日榜单分析与中文 HTML 邮件生成。"""
import html
import json
import re
from datetime import datetime

import data_fetch
import report_builder

TRENDING_URL = "https://github.com/trending"
TOP_N = 10
DISCLAIMER = (
    "本邮件由程序自动生成：榜单数据来自 GitHub Trending，项目分析由 AI 依据公开信息推测，"
    "可能存在偏差或滞后，仅供技术选题与趋势参考，不构成任何投资或采购建议。"
)

_ANALYSIS_KEYS = {
    "problem": "解决的问题",
    "users": "目标用户",
    "business_model": "商业模式",
    "potential": "商业化潜力",
    "risk": "主要风险",
}
_FALLBACK_ANALYSIS = dict.fromkeys(_ANALYSIS_KEYS, "AI 分析暂不可用，请点击项目链接自行了解。")

_ANALYSIS_SYSTEM = (
    "你是一名资深科技行业分析师，熟悉开源生态与软件商业模式。"
    "请依据给定信息做克制、务实的判断，不夸大、不编造事实。只输出一个 JSON 对象，不要输出任何其他文字。"
)


# --------------------------------------------------------------------------
# 抓取与解析
# --------------------------------------------------------------------------
def _clean_text(fragment: str) -> str:
    text = re.sub(r"<[^>]+>", " ", fragment or "")
    return re.sub(r"\s+", " ", html.unescape(text)).strip()


def _to_int(value, default: int = 0) -> int:
    try:
        return int(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return default


def _first_int(pattern: str, block: str, default: int = 0) -> int:
    match = re.search(pattern, block, re.S)
    if not match:
        return default
    digits = re.search(r"[\d,]+", _clean_text(match.group(1)))
    return _to_int(digits.group(0), default) if digits else default


def parse_trending(page_html: str) -> list[dict]:
    """把 GitHub Trending 页面解析成项目列表，按今日新增 Star 从高到低排序。"""
    projects: list[dict] = []
    for block in re.split(r'<article class="Box-row">', page_html or "")[1:]:
        name_match = re.search(r'<h2 class="h3 lh-condensed">\s*<a[^>]*href="([^"]+)"', block, re.S)
        if not name_match:
            continue
        name = name_match.group(1).strip().strip("/")
        if name.count("/") != 1:
            continue

        description = ""
        desc_match = re.search(r'<p class="col-9[^"]*">\s*(.*?)\s*</p>', block, re.S)
        if desc_match:
            description = _clean_text(desc_match.group(1))

        language = ""
        lang_match = re.search(r'itemprop="programmingLanguage">(.*?)</span>', block, re.S)
        if lang_match:
            language = _clean_text(lang_match.group(1))

        stars_today = _first_int(r"([\d,]+)\s+stars today", block)
        if not stars_today:
            continue

        projects.append(
            {
                "full_name": name,
                "url": f"https://github.com/{name}",
                "description": description,
                "language": language,
                "stars_today": stars_today,
                "stars_total": _first_int(r'stargazers"[^>]*>(.*?)</a>', block),
                "forks_total": _first_int(r'forks"[^>]*>(.*?)</a>', block),
            }
        )

    projects.sort(key=lambda item: item["stars_today"], reverse=True)
    return projects


def fetch_trending(limit: int = TOP_N) -> list[dict]:
    """抓取 GitHub Trending 日榜，返回今日新增 Star 最多的前 limit 个项目。"""
    resp = data_fetch._get(TRENDING_URL, params={"since": "daily"})
    projects = parse_trending(resp.text)
    if not projects:
        raise RuntimeError("GitHub Trending 页面结构可能已变化，未能解析出任何项目。")
    return projects[:limit]


# --------------------------------------------------------------------------
# AI 分析
# --------------------------------------------------------------------------
def _strip_code_fence(text: str) -> str:
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*\s*", "", cleaned)
        cleaned = re.sub(r"```\s*$", "", cleaned)
    return cleaned.strip()


def _parse_analyses(raw: str | None) -> dict[str, dict]:
    """把 LLM 返回的 JSON 解析成 {项目名: 五项分析}；失败时返回空。"""
    if not raw:
        return {}
    text = _strip_code_fence(raw)
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return {}
    if not isinstance(data, dict):
        return {}

    result: dict[str, dict] = {}
    for name, item in data.items():
        if not isinstance(item, dict):
            continue
        analysis = {}
        for key in _ANALYSIS_KEYS:
            value = item.get(key)
            analysis[key] = str(value).strip() if value not in (None, "") else _FALLBACK_ANALYSIS[key]
        result[str(name).strip().strip("/")] = analysis
    return result


def _analyze(projects: list[dict], llm=report_builder.llm_chat) -> dict[str, dict]:
    compact = [
        {
            "repo": item["full_name"],
            "简介": item["description"] or "（无描述）",
            "语言": item["language"] or "未知",
            "今日新增star": item["stars_today"],
            "star总数": item["stars_total"],
            "fork总数": item["forks_total"],
        }
        for item in projects
    ]
    schema = {
        "owner/repo": {
            "problem": "该项目解决的问题（40字以内）",
            "users": "目标用户（30字以内）",
            "business_model": "可能采用的商业模式（40字以内，无则说明目前无商业化迹象）",
            "potential": "商业化潜力（40字以内，包含判断依据）",
            "risk": "主要风险（40字以内）",
        }
    }
    user_prompt = (
        "以下是 GitHub Trending 今日榜上新增 Star 最多的项目，请逐个分析。\n"
        f"返回 JSON，key 必须与 repo 字段完全一致，结构示例：\n"
        f"{json.dumps(schema, ensure_ascii=False)}\n\n"
        f"项目数据：\n{json.dumps(compact, ensure_ascii=False)}"
    )
    return _parse_analyses(llm(_ANALYSIS_SYSTEM, user_prompt, max_tokens=4000))


# --------------------------------------------------------------------------
# HTML 邮件
# --------------------------------------------------------------------------
def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def _number(value) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return "-"


def _rank_badge(rank: int) -> str:
    return (
        '<span style="display:inline-block;min-width:22px;padding:2px 7px;margin-right:8px;'
        'background:#2563eb;color:#ffffff;border-radius:11px;font-size:12px;text-align:center;">'
        f"{rank}</span>"
    )


def _meta_line(item: dict) -> str:
    parts = []
    if item.get("language"):
        parts.append(f"语言 {_esc(item['language'])}")
    parts.append(f"今日新增 <strong style='color:#b91c1c;'>+{_number(item['stars_today'])}</strong> Star")
    parts.append(f"总 Star {_number(item['stars_total'])}")
    parts.append(f"Fork {_number(item['forks_total'])}")
    return " · ".join(parts)


def _card(item: dict, rank: int, analysis: dict) -> str:
    rows = "".join(
        "<tr>"
        "<td style='width:88px;padding:5px 8px;background:#f8fafc;border:1px solid #e2e8f0;"
        "color:#334e68;text-align:left;vertical-align:top;white-space:nowrap;'>" + label + "</td>"
        "<td style='padding:5px 8px;border:1px solid #e2e8f0;color:#1f2933;text-align:left;white-space:normal;line-height:1.6;'>"
        + _esc(analysis.get(key)) + "</td></tr>"
        for key, label in _ANALYSIS_KEYS.items()
    )
    description = _esc(item.get("description") or "（GitHub 未提供项目描述）")
    return (
        '<div class="repo">'
        f'<h3 style="margin:0 0 6px;font-size:16px;">{_rank_badge(rank)}'
        f'<a href="{_esc(item["url"])}" style="color:#1d4ed8;text-decoration:none;">'
        f'{_esc(item["full_name"])}</a></h3>'
        f'<p style="margin:0 0 4px;color:#334e68;line-height:1.6;">{description}</p>'
        f'<p class="muted" style="margin:0 0 10px;">{_meta_line(item)}</p>'
        f'<table style="width:100%;border-collapse:collapse;font-size:13px;text-align:left;">{rows}</table>'
        '</div>'
    )


def build_report(projects: list[dict] | None = None, *, llm=report_builder.llm_chat) -> tuple[str, str]:
    """返回 (邮件主题, HTML)，内容为 GitHub Trending 前十项目的中文分析。"""
    projects = projects if projects is not None else fetch_trending()
    projects = projects[:TOP_N]
    if not projects:
        raise RuntimeError("今日 GitHub Trending 没有可用项目。")

    analyses = _analyze(projects, llm=llm)
    date = datetime.now().strftime("%Y-%m-%d")
    title = f"GitHub Trending 每日十强 · {date}"
    total_today = sum(item["stars_today"] for item in projects)

    body = [
        "<h2>今日概览</h2>",
        f"<p>按今日新增 Star 排序，取 GitHub Trending 日榜前 {len(projects)} 个项目，"
        f"合计新增 Star {_number(total_today)}。数据抓取时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}。</p>",
    ]
    for rank, item in enumerate(projects, start=1):
        analysis = analyses.get(item["full_name"]) or dict(_FALLBACK_ANALYSIS)
        body.append(_card(item, rank, analysis))

    return title, report_builder._page(title, "".join(body), disclaimer=DISCLAIMER)
