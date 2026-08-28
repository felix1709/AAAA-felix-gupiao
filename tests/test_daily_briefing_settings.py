from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SIBLING_BRIEFING_DIR = PROJECT_ROOT.parent / "daily_briefing"
BRIEFING_DIR = (
    Path(os.environ["A_STOCK_BRIEFING_DIR"])
    if os.environ.get("A_STOCK_BRIEFING_DIR")
    else SIBLING_BRIEFING_DIR
    if SIBLING_BRIEFING_DIR.exists()
    else PROJECT_ROOT / "daily_briefing"
)
sys.path.insert(0, str(BRIEFING_DIR))

import data_fetch  # noqa: E402
import llm_api  # noqa: E402
import mailer  # noqa: E402
import report_builder  # noqa: E402
import run_briefing  # noqa: E402
import settings_store  # noqa: E402


def test_parse_recipients_accepts_common_separators_and_removes_duplicates():
    recipients = settings_store.parse_recipients(
        " first@qq.com; second@qq.com，first@qq.com\nthird@qq.com "
    )

    assert recipients == ["first@qq.com", "second@qq.com", "third@qq.com"]


def test_save_and_load_settings_normalizes_stock_entries(tmp_path):
    settings_path = tmp_path / "service_settings.json"

    settings_store.save_settings(
        {
            "recipients": "desk@qq.com, backup@qq.com",
            "stocks": [
                {
                    "code": "600153",
                    "name": "建发股份",
                    "shares": "300",
                    "cost": "8.97",
                    "risk": "8.87",
                    "clear": "7.68",
                    "reduce_low": "9.13",
                    "reduce_high": "9.25",
                    "enabled": True,
                }
            ],
        },
        path=settings_path,
    )

    loaded = settings_store.load_settings(path=settings_path, env_recipients="fallback@qq.com")

    assert loaded["recipients"] == ["desk@qq.com", "backup@qq.com"]
    assert loaded["stocks"] == [
        {
            "code": "600153",
            "suffix": "SS",
            "full_code": "600153.SS",
            "name": "建发股份",
            "shares": 300,
            "cost": 8.97,
            "risk": 8.87,
            "risk2": None,
            "clear": 7.68,
            "hard_stop": None,
            "reduce_low": 9.13,
            "reduce_high": 9.25,
            "enabled": True,
        }
    ]


def test_saved_empty_recipients_stay_empty(tmp_path):
    settings_path = tmp_path / "service_settings.json"

    settings_store.save_settings(
        {"recipients": [], "stocks": settings_store.DEFAULT_STOCKS},
        path=settings_path,
    )

    loaded = settings_store.load_settings(path=settings_path, env_recipients="fallback@qq.com")

    assert loaded["recipients"] == []


def test_settings_to_recipients_preserves_explicit_empty_list():
    recipients = settings_store.settings_to_recipients(
        {"recipients": []},
        fallback="fallback@qq.com",
    )

    assert recipients == []


def test_saved_empty_stock_list_stays_empty(tmp_path):
    settings_path = tmp_path / "service_settings.json"

    settings_store.save_settings(
        {"recipients": ["desk@qq.com"], "stocks": []},
        path=settings_path,
    )

    loaded = settings_store.load_settings(path=settings_path, env_recipients="fallback@qq.com")

    assert loaded["stocks"] == []


def test_default_settings_do_not_include_personal_recipients_or_stocks():
    defaults = settings_store.default_settings(env_recipients="")

    assert defaults["recipients"] == []
    assert defaults["stocks"] == []


def test_save_and_load_smtp_settings(tmp_path):
    settings_path = tmp_path / "service_settings.json"

    settings_store.save_settings(
        {
            "recipients": ["desk@qq.com"],
            "stocks": [],
            "smtp": {
                "host": " smtp.example.com ",
                "port": "465",
                "user": " sender@example.com ",
                "auth_code": " auth-code ",
            },
        },
        path=settings_path,
    )

    loaded = settings_store.load_settings(path=settings_path)

    assert loaded["smtp"] == {
        "host": "smtp.example.com",
        "port": 465,
        "user": "sender@example.com",
        "auth_code": "auth-code",
    }


def test_settings_to_smtp_settings_uses_saved_values_over_env():
    resolved = settings_store.settings_to_smtp_settings(
        {
            "smtp": {
                "host": "smtp.saved.example",
                "port": 587,
                "user": "saved@example.com",
                "auth_code": "saved-code",
            }
        },
        env_host="smtp.env.example",
        env_port="465",
        env_user="env@example.com",
        env_auth_code="env-code",
    )

    assert resolved == {
        "host": "smtp.saved.example",
        "port": 587,
        "user": "saved@example.com",
        "auth_code": "saved-code",
    }


def test_save_and_load_openai_compatible_api_settings(tmp_path):
    settings_path = tmp_path / "service_settings.json"

    settings_store.save_settings(
        {
            "recipients": ["desk@qq.com"],
            "stocks": [],
            "llm_api": {
                "base_url": " https://api.example.com/v1/ ",
                "api_key": " sk-test-key ",
                "model": " gpt-test ",
            },
        },
        path=settings_path,
    )

    loaded = settings_store.load_settings(path=settings_path)

    assert loaded["llm_api"] == {
        "base_url": "https://api.example.com/v1",
        "api_key": "sk-test-key",
        "model": "gpt-test",
    }


def test_openai_compatible_api_settings_accept_chat_completions_endpoint(tmp_path):
    settings_path = tmp_path / "service_settings.json"

    settings_store.save_settings(
        {
            "llm_api": {
                "base_url": "https://api.example.com/v1/chat/completions/",
                "api_key": "sk-test-key",
                "model": "gpt-test",
            },
            "recipients": [],
            "stocks": [],
        },
        path=settings_path,
    )

    loaded = settings_store.load_settings(path=settings_path)

    assert loaded["llm_api"]["base_url"] == "https://api.example.com/v1"


def test_settings_to_llm_api_settings_uses_saved_values_over_env():
    resolved = settings_store.settings_to_llm_api_settings(
        {
            "llm_api": {
                "base_url": "https://api.saved.example/v1",
                "api_key": "saved-key",
                "model": "saved-model",
            }
        },
        env_base_url="https://api.env.example/v1",
        env_api_key="env-key",
        env_model="env-model",
    )

    assert resolved == {
        "base_url": "https://api.saved.example/v1",
        "api_key": "saved-key",
        "model": "saved-model",
    }


def test_settings_to_llm_api_settings_falls_back_to_env_when_settings_are_blank():
    resolved = settings_store.settings_to_llm_api_settings(
        {"llm_api": {"base_url": "", "api_key": "", "model": ""}},
        env_base_url="https://api.env.example/v1",
        env_api_key="env-key",
        env_model="env-model",
    )

    assert resolved == {
        "base_url": "https://api.env.example/v1",
        "api_key": "env-key",
        "model": "env-model",
    }


def test_redact_secret_hides_api_key_body():
    assert settings_store.redact_secret("sk-1234567890abcdef") == "sk-************cdef"
    assert settings_store.redact_secret("") == ""


def test_openai_compatible_connectivity_uses_models_endpoint(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200
        text = '{"data":[{"id":"gpt-test"}]}'

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "gpt-test"}]}

    def fake_get(url, *, headers, timeout):
        calls.append((url, headers, timeout))
        return FakeResponse()

    monkeypatch.setattr(llm_api.requests, "get", fake_get)

    result = llm_api.test_openai_compatible_connection(
        {
            "base_url": "https://api.example.com/v1/",
            "api_key": "sk-test-key",
            "model": "gpt-test",
        }
    )

    assert result.ok is True
    assert result.message == "连接成功，已找到模型 gpt-test。"
    assert result.models == ("gpt-test",)
    assert calls == [
        (
            "https://api.example.com/v1/models",
            {"Authorization": "Bearer sk-test-key"},
            15,
        )
    ]


def test_openai_compatible_connectivity_reports_http_error(monkeypatch):
    class FakeResponse:
        status_code = 401
        text = "Unauthorized"

        def raise_for_status(self):
            raise llm_api.requests.HTTPError("401 Client Error")

        def json(self):
            return {}

    monkeypatch.setattr(llm_api.requests, "get", lambda *args, **kwargs: FakeResponse())

    result = llm_api.test_openai_compatible_connection(
        {
            "base_url": "https://api.example.com/v1",
            "api_key": "bad-key",
            "model": "gpt-test",
        }
    )

    assert result.ok is False
    assert result.message == "连接失败：HTTP 401 Unauthorized"


def test_openai_compatible_connectivity_trims_chat_completions_endpoint(monkeypatch):
    calls = []

    class FakeResponse:
        status_code = 200
        text = '{"data":[{"id":"gpt-test"},{"id":"gpt-other"}]}'

        def raise_for_status(self):
            return None

        def json(self):
            return {"data": [{"id": "gpt-test"}, {"id": "gpt-other"}]}

    def fake_get(url, *, headers, timeout):
        calls.append(url)
        return FakeResponse()

    monkeypatch.setattr(llm_api.requests, "get", fake_get)

    result = llm_api.test_openai_compatible_connection(
        {
            "base_url": "https://api.example.com/v1/chat/completions",
            "api_key": "sk-test-key",
            "model": "",
        }
    )

    assert result.ok is True
    assert result.models == ("gpt-test", "gpt-other")
    assert calls == ["https://api.example.com/v1/models"]


def test_settings_to_position_risk_lines_keeps_optional_fields():
    settings = {
        "stocks": [
            {
                "code": "003038",
                "suffix": "SZ",
                "name": "鑫铂股份",
                "risk": 10.40,
                "clear": 10.00,
                "hard_stop": 9.42,
                "reduce_low": 11.15,
                "reduce_high": 11.48,
                "enabled": True,
            }
        ]
    }

    lines = settings_store.settings_to_position_risk_lines(settings)

    assert lines == {
        "003038": {
            "name": "鑫铂股份",
            "risk": 10.40,
            "clear": 10.00,
            "hard_stop": 9.42,
            "reduce_zone": (11.15, 11.48),
        }
    }


def test_mailer_sends_to_all_configured_recipients(monkeypatch):
    sent = []

    class FakeSMTP:
        def __init__(self, host, port, timeout):
            self.host = host
            self.port = port
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def login(self, user, auth_code):
            assert user == "sender@qq.com"
            assert auth_code == "auth-code"

        def sendmail(self, sender, recipients, message):
            sent.append((sender, recipients, message))

    monkeypatch.setattr(mailer.smtplib, "SMTP_SSL", FakeSMTP)
    monkeypatch.setattr(mailer.config, "SMTP_USER", "sender@qq.com")
    monkeypatch.setattr(mailer.config, "SMTP_AUTH_CODE", "auth-code")
    monkeypatch.setattr(mailer.config, "SMTP_TO", "one@qq.com; two@qq.com")

    assert mailer.send_html("测试", "<b>hello</b>")

    assert sent
    assert sent[0][0] == "sender@qq.com"
    assert sent[0][1] == ["one@qq.com", "two@qq.com"]
    assert "one@qq.com, two@qq.com" in sent[0][2]


def test_get_holdings_uses_configured_watchlist_when_available(monkeypatch):
    monkeypatch.setattr(
        data_fetch.config,
        "WATCHLIST_STOCKS",
        [
            {
                "code": "002739",
                "suffix": "SZ",
                "full_code": "002739.SZ",
                "name": "儒意电影",
                "shares": 400,
                "cost": 12.5175,
                "risk": {"name": "儒意电影", "risk": 8.44, "clear": 7.55},
                "enabled": True,
            },
            {
                "code": "600000",
                "suffix": "SS",
                "full_code": "600000.SS",
                "name": "浦发银行",
                "shares": 0,
                "cost": 0.0,
                "risk": {"name": "浦发银行"},
                "enabled": True,
            },
        ],
        raising=False,
    )

    holdings = data_fetch.get_holdings()

    assert [item["full_code"] for item in holdings] == ["002739.SZ", "600000.SS"]
    assert holdings[1]["watch_only"] is True


def test_holdings_table_marks_watch_only_stock_without_fake_pnl():
    table_html = report_builder._holdings_table(
        {
            "holdings": [
                {
                    "code": "600000",
                    "full_code": "600000.SS",
                    "name": "浦发银行",
                    "shares": 0,
                    "cost": 0.0,
                    "watch_only": True,
                    "quote": {"price": 9.11, "change_pct": 1.2, "turnover_pct": 0.8},
                    "risk": {},
                }
            ]
        }
    )

    assert "关注" in table_html
    assert "持仓合计浮动盈亏" not in table_html
    assert "<td>-</td>" in table_html


def test_llm_chat_uses_configured_openai_compatible_endpoint(monkeypatch):
    calls = []

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": " 简短点评 "}}]}

    def fake_post(url, *, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return FakeResponse()

    monkeypatch.setattr(report_builder.config, "LLM_BASE_URL", "https://api.example.com/v1")
    monkeypatch.setattr(report_builder.config, "LLM_API_KEY", "sk-test-key")
    monkeypatch.setattr(report_builder.config, "LLM_MODEL", "gpt-test")
    monkeypatch.setattr(report_builder.requests, "post", fake_post)

    result = report_builder.llm_chat("system", "user", max_tokens=123)

    assert result == "简短点评"
    assert calls == [
        (
            "https://api.example.com/v1/chat/completions",
            {
                "Authorization": "Bearer sk-test-key",
                "Content-Type": "application/json",
            },
            {
                "model": "gpt-test",
                "messages": [
                    {"role": "system", "content": "system"},
                    {"role": "user", "content": "user"},
                ],
                "temperature": 0.3,
                "max_tokens": 123,
                "stream": False,
            },
            60,
        )
    ]


def test_monitor_preview_does_not_consume_alert_quota(tmp_path, monkeypatch):
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    sends = []

    monkeypatch.setattr(run_briefing.config, "DATA_DIR", tmp_path)
    monkeypatch.setattr(run_briefing, "REPORT_DIR", reports_dir)
    monkeypatch.setattr(run_briefing.data_fetch, "fetch_market_snapshot", lambda: {"holdings": []})
    monkeypatch.setattr(
        run_briefing.report_builder,
        "evaluate_alerts",
        lambda market: [{"type": "持仓异动", "text": "测试 +6.00%", "priority": "high"}],
    )
    monkeypatch.setattr(
        run_briefing.report_builder,
        "build_alert_email",
        lambda market, alerts: ("测试提醒", "<html>preview</html>"),
    )
    monkeypatch.setattr(
        run_briefing,
        "_send_or_skip",
        lambda subject, html, send: sends.append(send) or False,
    )

    run_briefing.run_monitor("2026-08-27", send=False)

    state_path = tmp_path / "monitor_state.json"
    state = json.loads(state_path.read_text(encoding="utf-8")) if state_path.exists() else {}
    assert state == {}
    assert sends == [False]
