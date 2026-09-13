"""每日简报统一入口。

用法（在项目根目录执行）：
  python daily_briefing/run_briefing.py --mode premarket
  python daily_briefing/run_briefing.py --mode midday
  python daily_briefing/run_briefing.py --mode close
  python daily_briefing/run_briefing.py --mode monitor
  python daily_briefing/run_briefing.py --mode github

可选参数：
  --date 2026-08-25   指定日期（默认今天）
  --no-send           只生成 HTML，不发送邮件
  --force             非交易日也强制执行
"""
import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import config
import data_fetch
import github_trending
import report_builder

LOG_FILE = config.LOG_DIR / "briefing.log"
REPORT_DIR = config.DATA_DIR / "reports"
REPORT_DIR.mkdir(exist_ok=True)


def _setup_logging() -> None:
    handlers = [logging.FileHandler(LOG_FILE, encoding="utf-8")]
    if sys.stderr is not None:
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )


def _save_report(mode: str, html: str, date: str, extra: str = "") -> Path:
    suffix = f"_{extra}" if extra else ""
    path = REPORT_DIR / f"{mode}_{date}{suffix}.html"
    path.write_text(html, encoding="utf-8")
    return path


def _send_or_skip(subject: str, html: str, send: bool, from_name: str = "A股每日简报") -> bool:
    if not send:
        logging.info("邮件发送已跳过（--no-send）。")
        return False
    try:
        import mailer
        ok = mailer.send_html(subject, html, from_name=from_name)
        logging.info("邮件已发送：%s", subject)
        return ok
    except Exception as exc:
        logging.error("邮件发送失败：%s", exc)
        return False


def run_report(mode: str, date: str, send: bool) -> None:
    logging.info("开始生成 %s 简报，日期=%s", mode, date)
    payload = data_fetch.fetch_snapshot_for_mode(mode, date)
    subject, html = report_builder.build_report(mode, payload)
    path = _save_report(mode, html, date)
    logging.info("HTML 已保存：%s", path)
    _send_or_skip(subject, html, send)


def run_github_report(date: str, send: bool) -> None:
    """GitHub Trending 每日推送，不依赖 A 股交易日。"""
    logging.info("开始生成 GitHub Trending 每日推送，日期=%s", date)
    subject, html = github_trending.build_report()
    path = _save_report("github", html, date)
    logging.info("HTML 已保存：%s", path)
    _send_or_skip(subject, html, send, from_name="GitHub 每日推送")


def _load_state() -> dict:
    path = config.DATA_DIR / "monitor_state.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_state(state: dict) -> None:
    path = config.DATA_DIR / "monitor_state.json"
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def run_monitor(date: str, send: bool) -> None:
    logging.info("开始盘中监控，日期=%s", date)
    market = data_fetch.fetch_market_snapshot()
    alerts = report_builder.evaluate_alerts(market)
    now = datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    urgent_alerts = [a for a in alerts if a.get("priority") == "high"]

    snapshot_path = REPORT_DIR / f"monitor_latest_{date}.html"
    _, snapshot_html = report_builder.build_alert_email(market, alerts)
    snapshot_path.write_text(snapshot_html, encoding="utf-8")

    if not urgent_alerts:
        logging.info("无重要异动，仅 %d 条普通风险提示（不单独发信）：%s", len(alerts), stamp)
        return

    # 盘中额外提醒：至少间隔 60 分钟，全天最多 3 封。
    state = _load_state()
    today_state = state.setdefault(date, {})
    last_sent = today_state.get("last_sent")
    sent_count = int(today_state.get("sent_count", 0))

    if last_sent:
        try:
            last_dt = datetime.strptime(last_sent, "%Y-%m-%d %H:%M:%S")
            if (now - last_dt).total_seconds() < config.MONITOR_COOLDOWN_MINUTES * 60:
                logging.info("重要异动存在，但距上次提醒不足 %d 分钟，跳过：%s", config.MONITOR_COOLDOWN_MINUTES, urgent_alerts)
                return
        except ValueError:
            pass

    if sent_count >= config.MONITOR_MAX_EMAILS_PER_DAY:
        logging.info("今日盘中提醒已达上限 %d 封，跳过：%s", config.MONITOR_MAX_EMAILS_PER_DAY, urgent_alerts)
        return

    logging.info("触发重要异动，准备发送提醒：%s", urgent_alerts)
    subject, html = report_builder.build_alert_email(market, urgent_alerts)
    sent = _send_or_skip(subject, html, send)
    if send and sent:
        today_state["last_sent"] = stamp
        today_state["sent_count"] = sent_count + 1
        _save_state(state)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="A股每日简报")
    parser.add_argument("--mode", choices=["premarket", "midday", "close", "monitor", "github"], required=True)
    parser.add_argument("--date", default=datetime.now().strftime("%Y-%m-%d"), help="YYYY-MM-DD")
    parser.add_argument("--no-send", action="store_true", help="只生成 HTML，不发送邮件")
    parser.add_argument("--force", action="store_true", help="非交易日也执行")
    args = parser.parse_args(argv)

    _setup_logging()
    send = not args.no_send

    try:
        if args.mode == "monitor":
            run_monitor(args.date, send)
        elif args.mode == "github":
            run_github_report(args.date, send)
        else:
            if not args.force and not data_fetch.is_trading_day(args.date):
                logging.info("%s 不是A股交易日，跳过。", args.date)
                return 0
            run_report(args.mode, args.date, send)
        return 0
    except Exception as exc:
        logging.exception("运行失败：%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
