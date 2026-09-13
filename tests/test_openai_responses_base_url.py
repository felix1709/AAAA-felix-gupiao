"""The Responses API only exists on native OpenAI; a custom base_url on the
openai provider must fall back to Chat Completions (#1024)."""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from tradingagents.llm_clients.openai_client import (
    NormalizedChatOpenAI,
    OpenAIClient,
    _is_native_openai_base_url,
    _sanitize_responses_input,
)


@pytest.mark.unit
class TestNativeBaseUrl:
    def test_unset_is_native(self):
        assert _is_native_openai_base_url(None) is True
        assert _is_native_openai_base_url("") is True

    def test_openai_hosts_are_native(self):
        assert _is_native_openai_base_url("https://api.openai.com/v1") is True
        assert _is_native_openai_base_url("api.openai.com/v1") is True

    def test_custom_endpoints_are_not_native(self):
        assert _is_native_openai_base_url("http://localhost:1234/v1") is False
        assert _is_native_openai_base_url("https://my-gateway.example.com/v1") is False
        assert _is_native_openai_base_url("https://api.openai.com.evil.com/v1") is False


@pytest.mark.unit
class TestResponsesApiSelection:
    def test_native_openai_enables_responses_api(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        llm = OpenAIClient("gpt-5.5", provider="openai").get_llm()
        assert getattr(llm, "use_responses_api", False) is True

    def test_custom_base_url_disables_responses_api(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        llm = OpenAIClient(
            "gpt-5.5", base_url="http://localhost:1234/v1", provider="openai"
        ).get_llm()
        # use_responses_api should be absent/False so the client speaks Chat Completions.
        assert getattr(llm, "use_responses_api", False) in (False, None)


@pytest.mark.unit
def test_responses_payload_drops_reasoning_output_items_with_phase():
    """OpenAI Responses API input rejects response-only reasoning fields."""
    client = NormalizedChatOpenAI(
        model="gpt-5.5",
        api_key="sk-test",
        use_responses_api=True,
    )
    payload = client._get_request_payload(
        [
            AIMessage(
                content=[
                    {
                        "type": "reasoning",
                        "summary": [{"type": "summary_text", "text": "checked trend"}],
                        "phase": "analysis",
                    },
                    {"type": "text", "text": "Buy-side case is stronger."},
                ]
            ),
            HumanMessage(content="Continue."),
        ]
    )

    assert payload["input"] == [
        {
            "type": "message",
            "content": [
                {
                    "type": "output_text",
                    "text": "Buy-side case is stronger.",
                    "annotations": [],
                }
            ],
            "role": "assistant",
        },
        {"content": "Continue.", "role": "user", "type": "message"},
    ]


@pytest.mark.unit
def test_responses_input_sanitizer_removes_phase_from_single_item():
    """A single Responses input item must not keep response-only phase fields."""
    assert _sanitize_responses_input(
        {
            "type": "message",
            "role": "assistant",
            "phase": "final_answer",
            "content": [
                {
                    "type": "output_text",
                    "text": "Done.",
                    "phase": "final_answer",
                }
            ],
        }
    ) == {
        "type": "message",
        "role": "assistant",
        "content": [
            {
                "type": "output_text",
                "text": "Done.",
            }
        ],
    }
