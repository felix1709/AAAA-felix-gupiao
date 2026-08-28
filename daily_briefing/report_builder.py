"""报告生成：把数据组装成 HTML，并调用 OpenAI 兼容接口生成简短点评。"""
import html
import json
from datetime import datetime

import config
import requests

DISCLAIMER = "本邮件由程序自动生成，内容仅供研究参考，不构成投资建议，不承诺收益。"


def _esc(value) -> str:
    return html.escape(str(value if value is not None else ""))


def _fmt(value, digits: int = 2, suffix: str = "") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:,.{digits}f}{suffix}"


def _pct(value, digits: int = 2) -> str:
    try:
        return f"{float(value):+.{digits}f}%"
    except (TypeError, ValueError):
        return "-"


def _wan(value, digits: int = 2, suffix: str = "万元") -> str:
    """把东财接口中的元金额转换为万元显示。"""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number / 10000:,.{digits}f}{suffix}"


def _safe_list(value) -> list:
    return value if isinstance(value, list) else []


def llm_chat(system: str, user: str, max_tokens: int = 700) -> str | None:
    """调用 OpenAI 兼容 Chat Completions 接口；失败时返回 None。"""
    if not config.LLM_API_KEY or not config.LLM_BASE_URL or not config.LLM_MODEL:
        return None
    url = config.LLM_BASE_URL.rstrip("/") + "/chat/completions"
    payload = {
        "model": config.LLM_MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.3,
        "max_tokens": max_tokens,
        "stream": False,
    }
    try:
        resp = requests.post(
            url,
            headers={
                "Authorization": f"Bearer {config.LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def deepseek_chat(system: str, user: str, max_tokens: int = 700) -> str | None:
    """Backward-compatible wrapper for older callers."""
    return llm_chat(system, user, max_tokens=max_tokens)


def _index_table(indices: list) -> str:
    rows = []
    for q in indices:
        if not q:
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(q.get('name'))}</td>"
            f"<td>{_fmt(q.get('price'))}</td>"
            f"<td>{_fmt(q.get('change'))}</td>"
            f"<td>{_pct(q.get('change_pct'))}</td>"
            f"<td>{_fmt(q.get('amount_wan'), 0, '万')}</td>"
            "</tr>"
        )
    if not rows:
        return "<p>暂无指数数据</p>"
    return (
        '<table><thead><tr><th>指数</th><th>最新</th><th>涨跌</th><th>涨跌幅</th><th>成交额</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _overseas_table(overseas: list) -> str:
    rows = []
    for q in overseas:
        if not q:
            continue
        rows.append(
            "<tr>"
            f"<td>{_esc(q.get('name'))}</td>"
            f"<td>{_fmt(q.get('price'))}</td>"
            f"<td>{_pct(q.get('change_pct'))}</td>"
            "</tr>"
        )
    if not rows:
        return "<p>暂无外盘数据</p>"
    return (
        '<table><thead><tr><th>市场</th><th>最新</th><th>涨跌幅</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _calendar_table(calendar: dict) -> str:
    parts = []
    jjsj = _safe_list(calendar.get("jjsj"))
    if jjsj:
        items = []
        for group in jjsj[:8]:
            date_time = group.get("Date", "")
            city = group.get("City", "")
            for row in _safe_list(group.get("Data"))[:4]:
                items.append(f"<li><b>{_esc(date_time)} · {_esc(city)}</b>：{_esc(row.get('Name'))}</li>")
        parts.append("<h3>宏观经济数据</h3><ul>" + "".join(items) + "</ul>")

    hyhy = _safe_list(calendar.get("hyhy"))
    if hyhy:
        items = []
        for row in hyhy[:8]:
            items.append(f"<li><b>{_esc(row.get('FE_NAME'))}</b>（{_esc(row.get('FE_TYPE'))}）：{_esc(row.get('CONTENT'))}</li>")
        parts.append("<h3>行业会议</h3><ul>" + "".join(items) + "</ul>")

    gddh = _safe_list(calendar.get("gddh"))
    if gddh:
        names = []
        for row in gddh[:1]:
            data = _safe_list(row.get("Data"))
            names = [f"{_esc(x.get('Sname'))}({_esc(x.get('Scode'))})" for x in data[:20]]
        parts.append("<h3>股东大会</h3><p>" + "、".join(names) + "</p>")

    tfpxx = _safe_list(calendar.get("tfpxx"))
    if tfpxx:
        names = []
        for group in tfpxx[:2]:
            for x in _safe_list(group.get("Data"))[:20]:
                names.append(f"{_esc(x.get('Sname'))}({_esc(x.get('Scode'))})")
        parts.append("<h3>停复牌</h3><p>" + "、".join(names) + "</p>")

    return "".join(parts) if parts else "<p>今日暂无重要宏观日历</p>"


def _announcement_list(announcements: list, limit: int = 18) -> str:
    rows = []
    for item in announcements[:limit]:
        rows.append(
            "<li>"
            f"<b>{_esc(item.get('title'))}</b>"
            f"<div class='muted'>{_esc(item.get('codes'))} · {_esc(item.get('column'))} · {_esc(item.get('display_time'))}</div>"
            "</li>"
        )
    return "<ul>" + "".join(rows) + "</ul>" if rows else "<p>暂无公告数据</p>"


def _new_stock_table(new_stocks: dict) -> str:
    listing = _safe_list(new_stocks.get("listing"))
    applying = _safe_list(new_stocks.get("applying"))
    parts = []
    if listing:
        rows = []
        for item in listing[:20]:
            rows.append(
                "<tr>"
                f"<td>{_esc(item.get('SECURITY_CODE'))}</td>"
                f"<td>{_esc(item.get('SECURITY_NAME'))}</td>"
                f"<td>{_esc(item.get('TRADE_MARKET'))}·{_esc(item.get('MARKET_TYPE'))}</td>"
                f"<td>{_fmt(item.get('ISSUE_PRICE'))}</td>"
                f"<td>{_esc(item.get('LISTING_DATE'))}</td>"
                "</tr>"
            )
        parts.append("<h3>今日上市</h3><table><thead><tr><th>代码</th><th>名称</th><th>板块</th><th>发行价</th><th>上市日</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")
    if applying:
        rows = []
        for item in applying[:20]:
            rows.append(
                "<tr>"
                f"<td>{_esc(item.get('SECURITY_CODE'))}</td>"
                f"<td>{_esc(item.get('SECURITY_NAME'))}</td>"
                f"<td>{_esc(item.get('TRADE_MARKET'))}·{_esc(item.get('MARKET_TYPE'))}</td>"
                f"<td>{_fmt(item.get('ISSUE_PRICE'))}</td>"
                f"<td>{_esc(item.get('APPLY_DATE'))}</td>"
                "</tr>"
            )
        parts.append("<h3>今日可申购</h3><table><thead><tr><th>代码</th><th>名称</th><th>板块</th><th>发行价</th><th>申购日</th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>")
    return "".join(parts) if parts else "<p>今日暂无新股上市/申购数据</p>"


def _unlock_table(unlocks: list, limit: int = 30) -> str:
    rows = []
    for item in unlocks[:limit]:
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('SECURITY_CODE'))}</td>"
            f"<td>{_esc(item.get('SECURITY_NAME_ABBR'))}</td>"
            f"<td>{_esc(item.get('FREE_SHARES_TYPE'))}</td>"
            f"<td>{_fmt(item.get('FREE_SHARES'), 2, '万股')}</td>"
            f"<td>{_pct(item.get('FREE_RATIO', 0) * 100 if item.get('FREE_RATIO') not in (None, '') else 0)}</td>"
            f"<td>{_fmt(item.get('LIFT_MARKET_CAP'), 0, '万元')}</td>"
            "</tr>"
        )
    if not rows:
        return "<p>今日暂无解禁数据</p>"
    return (
        '<table><thead><tr><th>代码</th><th>名称</th><th>解禁类型</th><th>解禁数量</th><th>占总股本</th><th>解禁市值</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _sector_table(sectors: dict) -> str:
    gainers = _safe_list(sectors.get("gainers"))
    losers = _safe_list(sectors.get("losers"))
    def make_rows(items):
        rows = []
        for x in items:
            rows.append(
                "<tr>"
                f"<td>{_esc(x.get('f14'))}</td>"
                f"<td>{_pct(x.get('f3'))}</td>"
                f"<td>{_fmt(x.get('f8'), 2, '%')}</td>"
                f"<td>{_esc(x.get('f128'))}</td>"
                f"<td>{_esc(x.get('f140'))}</td>"
                f"<td>{_esc(x.get('f104'))}涨/{_esc(x.get('f105'))}跌</td>"
                "</tr>"
            )
        return "".join(rows)
    html_parts = []
    if gainers:
        html_parts.append("<h3>领涨行业</h3><table><thead><tr><th>板块</th><th>涨跌幅</th><th>换手率</th><th>领涨股</th><th>代码</th><th>成分涨跌</th></tr></thead><tbody>" + make_rows(gainers) + "</tbody></table>")
    if losers:
        html_parts.append("<h3>领跌行业</h3><table><thead><tr><th>板块</th><th>涨跌幅</th><th>换手率</th><th>领跌股</th><th>代码</th><th>成分涨跌</th></tr></thead><tbody>" + make_rows(losers) + "</tbody></table>")
    return "".join(html_parts) if html_parts else "<p>暂无板块数据</p>"


def _news_list(news: list, limit: int = 30) -> str:
    rows = []
    for item in news[:limit]:
        rows.append(f"<li><b>{_esc(item.get('time'))}</b> {_esc(item.get('content'))} <span class='muted'>{_esc(item.get('subjects'))}</span></li>")
    return "<ul>" + "".join(rows) + "</ul>" if rows else "<p>暂无快讯</p>"


def _holdings_table(market: dict) -> str:
    holdings = _safe_list(market.get("holdings"))
    rows = []
    total_pnl = 0.0
    has_position = False
    for h in holdings:
        q = h.get("quote") or {}
        price = q.get("price") or 0
        cost = h.get("cost") or 0
        shares = h.get("shares") or 0
        watch_only = bool(h.get("watch_only")) or not shares or not cost
        pnl = (price - cost) * shares if price and not watch_only else 0
        pnl_pct = ((price - cost) / cost * 100) if cost and not watch_only else 0
        if not watch_only:
            total_pnl += pnl
            has_position = True
        risk = h.get("risk") or {}
        tags = []
        if cost:
            if price and "clear" in risk and price <= float(risk.get("clear") or 99999):
                tags.append("跌破清仓线")
            elif price and "risk" in risk and price <= float(risk.get("risk") or 99999):
                tags.append("跌破风险线")
            zone = risk.get("reduce_zone")
            if price and isinstance(zone, (list, tuple)) and len(zone) == 2 and zone[0] <= price <= zone[1]:
                tags.append("进入减仓区")
        if q.get("change_pct") and abs(float(q.get("change_pct"))) >= config.ALERT_THRESHOLDS["single_day_change_pct"]:
            tags.append("单日异动")
        if q.get("turnover_pct") and float(q.get("turnover_pct")) >= config.ALERT_THRESHOLDS["turnover_pct"]:
            tags.append("高换手")
        tag_html = " ".join(f"<span class='tag'>{_esc(t)}</span>" for t in tags) if tags else "-"
        rows.append(
            "<tr>"
            f"<td>{_esc(h.get('full_code'))}</td>"
            f"<td>{_esc(h.get('name'))}</td>"
            f"<td>{'关注' if watch_only else '持仓'}</td>"
            f"<td>{_fmt(price)}</td>"
            f"<td>{_pct(q.get('change_pct'))}</td>"
            f"<td>{_fmt(q.get('turnover_pct'), 2, '%')}</td>"
            f"<td>{_fmt(cost) if not watch_only else '-'}</td>"
            f"<td>{_fmt(pnl, 0) if not watch_only else '-'}</td>"
            f"<td>{_pct(pnl_pct) if not watch_only else '-'}</td>"
            f"<td>{tag_html}</td>"
            "</tr>"
        )
    if not rows:
        return "<p>未读取到持仓记录</p>"
    summary = f"<p>持仓合计浮动盈亏：<b>{_fmt(total_pnl, 0)} 元</b></p>" if has_position else ""
    table = (
        '<table><thead><tr><th>代码</th><th>名称</th><th>类型</th><th>现价</th><th>涨跌</th><th>换手</th><th>成本</th><th>浮动盈亏</th><th>盈亏比</th><th>风险提示</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
    )
    return summary + table


def evaluate_alerts(market: dict) -> list[dict]:
    """检查持仓与指数异动。

    返回项带 priority：
    - high：重要异动，盘中可单独发提醒；
    - normal：普通风险线/减仓区提示，只放进三封固定简报。
    """
    alerts = []
    for q in _safe_list(market.get("indices")):
        if q.get("change_pct") and abs(float(q.get("change_pct"))) >= config.ALERT_THRESHOLDS["index_change_pct"]:
            alerts.append({"type": "指数异动", "text": f"{q.get('name')} {_pct(q.get('change_pct'))}", "priority": "high"})

    for h in _safe_list(market.get("holdings")):
        q = h.get("quote") or {}
        name = h.get("name") or h.get("code")
        price = q.get("price") or 0
        if q.get("change_pct") and abs(float(q.get("change_pct"))) >= config.ALERT_THRESHOLDS["single_day_change_pct"]:
            alerts.append({"type": "持仓异动", "text": f"{name} {_pct(q.get('change_pct'))}", "priority": "high"})
        if q.get("turnover_pct") and float(q.get("turnover_pct")) >= config.ALERT_THRESHOLDS["turnover_pct"]:
            alerts.append({"type": "高换手", "text": f"{name} 换手 {_fmt(q.get('turnover_pct'), 2, '%')}", "priority": "high"})
        if q.get("high") and price and float(q.get("high")) > 0:
            drawdown = (float(q.get("high")) - float(price)) / float(q.get("high")) * 100
            if drawdown >= config.ALERT_THRESHOLDS["from_high_drawdown_pct"]:
                alerts.append({"type": "高位回落", "text": f"{name} 距日内高点回撤 {_fmt(drawdown, 1, '%')}", "priority": "high"})
        risk = h.get("risk") or {}
        if price:
            for key, label, priority in (
                ("clear", "跌破清仓线", "high"),
                ("hard_stop", "触发硬止损", "high"),
                ("risk", "跌破风险线", "normal"),
                ("risk2", "跌破第二风险线", "normal"),
            ):
                if key in risk and price <= float(risk[key]):
                    alerts.append({"type": label, "text": f"{name} 现价 {_fmt(price)} ≤ {risk[key]}", "priority": priority})
            zone = risk.get("reduce_zone")
            if isinstance(zone, (list, tuple)) and len(zone) == 2 and zone[0] <= price <= zone[1]:
                alerts.append({"type": "进入减仓区", "text": f"{name} 现价 {_fmt(price)}", "priority": "normal"})
    return alerts


def _alerts_html(alerts: list) -> str:
    if not alerts:
        return "<p class='ok'>当前无触发异动。</p>"
    rows = "".join(f"<li><b>{_esc(a['type'])}</b>：{_esc(a['text'])}</li>" for a in alerts)
    return "<ul class='alert'>" + rows + "</ul>"


def _ai_block(title: str, text: str | None) -> str:
    if not text:
        return f"<h2>{title}</h2><p class='muted'>AI 点评暂不可用。</p>"
    paragraphs = "".join(f"<p>{_esc(line)}</p>" for line in text.splitlines() if line.strip())
    return f"<h2>{title}</h2>{paragraphs}"


def _style() -> str:
    return """
    <style>
      body{font-family:'Microsoft YaHei',Arial,sans-serif;background:#f4f6f9;margin:0;padding:24px;color:#1f2933;}
      .container{max-width:1000px;margin:0 auto;background:#fff;border-radius:10px;padding:28px;box-shadow:0 2px 12px rgba(0,0,0,.08);}
      h1{font-size:22px;margin:0 0 8px;} h2{font-size:18px;margin:26px 0 10px;border-left:4px solid #2563eb;padding-left:8px;}
      h3{font-size:15px;margin:14px 0 6px;color:#334e68;}
      table{width:100%;border-collapse:collapse;margin:10px 0;font-size:13px;}
      th,td{border:1px solid #e2e8f0;padding:7px 8px;text-align:right;white-space:nowrap;}
      th{background:#eef2f7;color:#334e68;} td:first-child,th:first-child{text-align:left;}
      ul{padding-left:20px;line-height:1.65;} li{margin:4px 0;}
      .muted{color:#718096;font-size:12px;} .ok{color:#0f766e;} .alert{color:#b91c1c;}
      .tag{display:inline-block;background:#fee2e2;color:#b91c1c;border-radius:4px;padding:1px 5px;margin:0 2px;font-size:12px;}
      .footer{margin-top:28px;padding-top:12px;border-top:1px dashed #cbd5e1;color:#64748b;font-size:12px;}
    </style>
    """


def _page(title: str, body: str) -> str:
    return (
        "<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
        f"<title>{_esc(title)}</title>{_style()}</head><body><div class='container'>"
        f"<h1>{_esc(title)}</h1><p class='muted'>生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>"
        f"{body}<div class='footer'>{DISCLAIMER}</div></div></body></html>"
    )


def _premarket_comment(payload: dict) -> str | None:
    market = payload.get("market") or {}
    holdings_summary = [
        {
            "code": h.get("full_code"),
            "name": h.get("name"),
            "price": (h.get("quote") or {}).get("price"),
            "change_pct": (h.get("quote") or {}).get("change_pct"),
        }
        for h in _safe_list(market.get("holdings"))
    ]
    compact = json.dumps({
        "指数": [{"name": q.get("name"), "change_pct": q.get("change_pct")} for q in _safe_list(market.get("indices"))],
        "外盘": [{"name": q.get("name"), "change_pct": q.get("change_pct")} for q in _safe_list(market.get("overseas"))],
        "宏观日历数量": len(_safe_list(payload.get("calendar", {}).get("jjsj"))),
        "公告前5条": [a.get("title") for a in _safe_list(payload.get("announcements"))[:5]],
        "持仓": holdings_summary,
    }, ensure_ascii=False)
    return deepseek_chat(
        "你是A股开盘前简报编辑。请用150字以内给出今日早评，重点：外盘影响、主要风险、持仓需注意事项。语气克制，不喊单，不承诺收益，不构成投资建议。",
        compact,
        max_tokens=500,
    )


def _midday_comment(payload: dict) -> str | None:
    market = payload.get("market") or {}
    compact = json.dumps({
        "指数": [{"name": q.get("name"), "price": q.get("price"), "change_pct": q.get("change_pct")} for q in _safe_list(market.get("indices"))],
        "领涨行业": [x.get("f14") for x in _safe_list((payload.get("sectors") or {}).get("gainers"))[:5]],
        "领跌行业": [x.get("f14") for x in _safe_list((payload.get("sectors") or {}).get("losers"))[:5]],
        "快讯前10条": [n.get("content") for n in _safe_list(payload.get("news"))[:10]],
    }, ensure_ascii=False)
    return deepseek_chat(
        "你是A股午间复盘编辑。请用150字以内总结上午盘面、板块轮动和风险，语气克制，不喊单，不承诺收益，不构成投资建议。",
        compact,
        max_tokens=500,
    )


def _close_comment(payload: dict) -> str | None:
    market = payload.get("market") or {}
    dragon = _safe_list(payload.get("dragon_tiger"))
    block = _safe_list(payload.get("block_trades"))
    block_total = sum(float(x.get("DEAL_AMT") or 0) for x in block)
    compact = json.dumps({
        "指数": [{"name": q.get("name"), "price": q.get("price"), "change_pct": q.get("change_pct")} for q in _safe_list(market.get("indices"))],
        "龙虎榜数量": len(dragon),
        "大宗交易笔数": len(block),
        "大宗成交总额万元": round(block_total / 10000, 0),
        "领涨行业": [x.get("f14") for x in _safe_list((payload.get("sectors") or {}).get("gainers"))[:5]],
        "领跌行业": [x.get("f14") for x in _safe_list((payload.get("sectors") or {}).get("losers"))[:5]],
    }, ensure_ascii=False)
    return deepseek_chat(
        "你是A股收盘总结编辑。请用150字以内总结今日收盘、资金与风险，并提醒关注明日。语气克制，不喊单，不承诺收益，不构成投资建议。",
        compact,
        max_tokens=500,
    )


def build_report(mode: str, payload: dict) -> tuple[str, str]:
    """返回 (邮件主题, HTML)。"""
    date = payload.get("date") or datetime.now().strftime("%Y-%m-%d")
    market = payload.get("market") or {}
    alerts = evaluate_alerts(market)

    if mode == "premarket":
        title = f"A股盘前简报 {date}"
        body = []
        body.append("<h2>指数与外盘</h2>" + _index_table(_safe_list(market.get("indices"))) + _overseas_table(_safe_list(market.get("overseas"))))
        body.append("<h2>宏观日历</h2>" + _calendar_table(payload.get("calendar") or {}))
        body.append("<h2>昨晚公告</h2>" + _announcement_list(_safe_list(payload.get("announcements")), 18))
        body.append("<h2>新股</h2>" + _new_stock_table(payload.get("new_stocks") or {}))
        body.append("<h2>限售解禁</h2>" + _unlock_table(_safe_list(payload.get("unlocks")), 30))
        body.append("<h2>持仓监控</h2>" + _alerts_html(alerts) + _holdings_table(market))
        body.append(_ai_block("早评", _premarket_comment(payload)))
    elif mode == "midday":
        title = f"A股午间简报 {date}"
        body = [
            "<h2>上午盘面</h2>" + _index_table(_safe_list(market.get("indices"))),
            "<h2>板块轮动</h2>" + _sector_table(payload.get("sectors") or {}),
            "<h2>实时流资讯</h2>" + _news_list(_safe_list(payload.get("news")), 30),
            "<h2>持仓监控</h2>" + _alerts_html(alerts) + _holdings_table(market),
            _ai_block("午间点评", _midday_comment(payload)),
        ]
    elif mode == "close":
        title = f"A股收盘总结 {date}"
        block = _safe_list(payload.get("block_trades"))
        block_total = sum(float(x.get("DEAL_AMT") or 0) for x in block)
        body = [
            "<h2>收盘核心数据</h2>" + _index_table(_safe_list(market.get("indices"))),
            f"<h2>两市大宗交易汇总</h2><p>共 {len(block)} 笔，合计成交额约 {_wan(block_total, 2, '万元')}。</p>" + _block_trade_table(block),
            "<h2>当日龙虎榜完整榜单</h2>" + _dragon_table(_safe_list(payload.get("dragon_tiger"))),
            "<h2>持仓监控</h2>" + _alerts_html(alerts) + _holdings_table(market),
            _ai_block("收盘总结", _close_comment(payload)),
        ]
    else:
        title = f"A股监控提醒 {date}"
        body = [
            "<h2>指数与持仓快照</h2>" + _index_table(_safe_list(market.get("indices"))),
            _alerts_html(alerts),
            _holdings_table(market),
        ]

    return title, _page(title, "".join(body))


def _block_trade_table(block: list, limit: int = 200) -> str:
    rows = []
    for item in block[:limit]:
        rows.append(
            "<tr>"
            f"<td>{_esc(item.get('TRADE_DATE'))}</td>"
            f"<td>{_esc(item.get('SECURITY_CODE'))}</td>"
            f"<td>{_esc(item.get('SECURITY_NAME_ABBR'))}</td>"
            f"<td>{_fmt(item.get('DEAL_PRICE'))}</td>"
            f"<td>{_fmt(item.get('DEAL_VOLUME'), 0)}</td>"
            f"<td>{_wan(item.get('DEAL_AMT'), 2, '万元')}</td>"
            f"<td>{_pct(item.get('PREMIUM_RATIO'))}</td>"
            f"<td>{_esc(item.get('BUYER_NAME'))}</td>"
            f"<td>{_esc(item.get('SELLER_NAME'))}</td>"
            "</tr>"
        )
    if not rows:
        return "<p>今日无大宗交易数据。</p>"
    return (
        '<table><thead><tr><th>日期</th><th>代码</th><th>名称</th><th>成交价</th><th>成交量</th><th>成交额</th><th>溢价率</th><th>买方</th><th>卖方</th></tr></thead>'
        f"<tbody>{''.join(rows)}</tbody></table>"
    )


def _dragon_table(rows: list) -> str:
    html_rows = []
    for item in rows:
        html_rows.append(
            "<tr>"
            f"<td>{_esc(item.get('SECURITY_CODE'))}</td>"
            f"<td>{_esc(item.get('SECURITY_NAME_ABBR'))}</td>"
            f"<td>{_fmt(item.get('CLOSE_PRICE'))}</td>"
            f"<td>{_pct(item.get('CHANGE_RATE'))}</td>"
            f"<td>{_fmt(item.get('TURNOVERRATE'), 2, '%')}</td>"
            f"<td>{_wan(item.get('BILLBOARD_NET_AMT'), 2, '万元')}</td>"
            f"<td>{_esc(item.get('reason_clean'))}</td>"
            "</tr>"
        )
    if not html_rows:
        return "<p>当日暂无龙虎榜数据。</p>"
    return (
        '<table><thead><tr><th>代码</th><th>名称</th><th>收盘价</th><th>涨跌幅</th><th>换手率</th><th>龙虎榜净买额</th><th>上榜原因</th></tr></thead>'
        f"<tbody>{''.join(html_rows)}</tbody></table>"
    )


def build_alert_email(market: dict, alerts: list[dict] | None = None) -> tuple[str, str]:
    """监控模式触发的提醒邮件；alerts 为空时按全部信号生成。"""
    alerts = evaluate_alerts(market) if alerts is None else alerts
    date = datetime.now().strftime("%Y-%m-%d")
    title = f"A股持仓异动提醒 {date} {datetime.now().strftime('%H:%M')}"
    body = [
        "<h2>指数快照</h2>" + _index_table(_safe_list(market.get("indices"))),
        "<h2>触发信号</h2>" + _alerts_html(alerts),
        "<h2>持仓明细</h2>" + _holdings_table(market),
    ]
    return title, _page(title, "".join(body))
