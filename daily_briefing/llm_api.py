"""OpenAI-compatible LLM API helpers for daily briefing comments."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests
import settings_store


@dataclass(frozen=True)
class ConnectionTestResult:
    ok: bool
    message: str
    models: tuple[str, ...] = ()


def _join_endpoint(base_url: str, path: str) -> str:
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def _extract_http_error(response: requests.Response) -> str:
    text = ""
    try:
        data = response.json()
    except ValueError:
        data = None
    if isinstance(data, dict):
        error = data.get("error")
        if isinstance(error, dict):
            text = str(error.get("message") or "")
        elif error:
            text = str(error)
    if not text:
        text = (response.text or "").strip()
    text = text[:200]
    return f"HTTP {response.status_code} {text}".strip()


def test_openai_compatible_connection(
    api_settings: dict[str, Any],
    *,
    timeout: int = 15,
) -> ConnectionTestResult:
    settings = settings_store.normalize_llm_api_settings(api_settings)
    base_url = settings["base_url"]
    api_key = settings["api_key"]
    model = settings["model"]

    if not base_url:
        return ConnectionTestResult(False, "连接失败：请填写 Base URL。")
    if not api_key:
        return ConnectionTestResult(False, "连接失败：请填写 API Key。")

    try:
        response = requests.get(
            _join_endpoint(base_url, "/models"),
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
    except requests.HTTPError:
        return ConnectionTestResult(False, f"连接失败：{_extract_http_error(response)}")
    except requests.RequestException as exc:
        return ConnectionTestResult(False, f"连接失败：{exc}")
    except ValueError:
        return ConnectionTestResult(False, "连接失败：服务返回内容不是 JSON。")

    model_ids = [
        item.get("id")
        for item in data.get("data", [])
        if isinstance(item, dict) and item.get("id")
    ]
    models = tuple(str(model_id) for model_id in model_ids)
    if model and model in model_ids:
        return ConnectionTestResult(True, f"连接成功，已找到模型 {model}。", models)
    if model and models:
        return ConnectionTestResult(True, f"连接成功，但模型列表中未看到 {model}。", models)
    return ConnectionTestResult(True, "连接成功，服务已响应 /models。", models)
