"""Router unit tests — stubbed adapter, no network (spec 12 § 5)."""
import pytest

from django.conf import settings

from apps.llm.adapter import LLMUnavailable
from apps.rag import router
from apps.rag.router import classify_intent, estimate_tokens, rewrite_standalone, route_question


@pytest.fixture
def router_off(settings):
    settings.LLM_ROUTER_MODEL = ""
    return settings


@pytest.fixture
def stub_answer(monkeypatch):
    """Replace the router LLM call with a scripted answer."""

    def install(text):
        calls = []

        def fake(_messages):
            calls.append(1)
            return text

        monkeypatch.setattr(router, "_router_answer", fake)
        return calls

    return install


def test_estimate_tokens_uses_the_chars_div_four_heuristic():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd") == 1
    assert estimate_tokens("a" * 8) == 2


def test_classify_intent_flags_conversational_follow_ups(stub_answer):
    stub_answer("HISTORY: Tanba sa ita la temi kona ba TOPSIS ohin?")

    intent = classify_intent(
        "Tanba sa o la temi kona ba TOPSIS?", [{"role": "user", "content": "Saida mak TOPSIS?"}]
    )

    assert intent == "history"


def test_classify_intent_routes_factual_questions_to_retrieval(stub_answer):
    stub_answer("RETRIEVE: Saida mak metodu TOPSIS iha desizaun multi-kriteriu?")

    intent = classify_intent("Saida mak TOPSIS?", [])

    assert intent == "retrieve"


def test_malformed_router_output_defaults_to_retrieve(stub_answer):
    stub_answer("basically maybe? I think so")

    assert classify_intent("q?", []) == "retrieve"


def test_router_failure_defaults_to_retrieve(monkeypatch):
    def boom(_messages):
        raise LLMUnavailable("timeout")

    monkeypatch.setattr(router, "_router_answer", boom)

    assert classify_intent("q?", []) == "retrieve"


def test_disabled_router_defaults_to_retrieve(router_off, monkeypatch):
    def fail_test(_messages):
        raise AssertionError("the router must not be called when disabled")

    monkeypatch.setattr(router, "_router_answer", fail_test)

    assert classify_intent("q?", []) == "retrieve"


def test_rewrite_standalone_resolves_the_pronoun(stub_answer):
    stub_answer("RETRIEVE: Saida mak metodu TOPSIS iha desizaun multi-kriteriu?")

    question = rewrite_standalone(
        "What about its weights?",
        [
            {"role": "user", "content": "Saida mak TOPSIS?"},
            {"role": "assistant", "content": "TOPSIS mak ..."},
        ],
    )

    assert question == "Saida mak metodu TOPSIS iha desizaun multi-kriteriu?"


def test_rewrite_failure_returns_the_original_question(monkeypatch):
    def boom(_messages):
        raise LLMUnavailable("down")

    monkeypatch.setattr(router, "_router_answer", boom)

    assert rewrite_standalone("why?", []) == "why?"


def test_route_question_retrieves_with_the_rewritten_question(stub_answer):
    stub_answer("RETRIEVE: Saida mak metodu SAW?")

    intent, question = route_question("Saida mak SAW?", [])

    assert intent == "retrieve"
    assert question == "Saida mak metodu SAW?"


def test_route_question_history_keeps_the_original_question(stub_answer):
    stub_answer("HISTORY: Tanba sa ita la temi?")

    intent, question = route_question("Tanba sa o la temi?", [])

    assert intent == "history"
    assert question == "Tanba sa o la temi?"


def test_settings_default_router_model_is_off(settings):
    assert settings.LLM_ROUTER_MODEL == ""
