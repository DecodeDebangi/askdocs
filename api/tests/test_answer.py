from types import SimpleNamespace

import pytest

from askdocs import answer
from askdocs.answer import HANDOFF_MESSAGE, answer_stream, build_context, cited_numbers
from askdocs.search import Hit


def hit(title: str, section: str | None, content: str, anchor: str | None = None) -> Hit:
    return Hit("https://docs.example.com/" + title.lower(), title, section, anchor, content, 0.8, 1, 1, 0.03)


RANKED = [(hit("Storage", "Limits", "Free projects can upload files up to 50 MB. " * 10, "limits"), 6.1),
          (hit("Buckets", None, "Buckets hold files and set upload restrictions. " * 10), 2.3)]


def fake_llm(tokens: list[str]):
    chunks = [SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=t))]) for t in tokens]
    create = lambda **_: iter(chunks)  # noqa: E731
    return lambda: SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def run(monkeypatch, ranked, tokens):
    monkeypatch.setattr(answer, "retrieve", lambda conn, q: ranked)
    monkeypatch.setattr(answer, "llm", fake_llm(tokens))
    events = list(answer_stream(None, "question"))
    shown = "".join(e["text"] for e in events if e["type"] == "token")
    return events, shown, events[-1]


def test_cited_numbers_ignores_out_of_range():
    assert cited_numbers("Yes [1]. Also [3][1] and [9].", 3) == [1, 3]


def test_build_context_numbers_sources_and_links_to_section():
    context, sources = build_context(RANKED)
    assert context.startswith("[1] Storage > Limits\n")
    assert "\n\n[2] Buckets\n" in context
    assert sources[0].url == "https://docs.example.com/storage#limits"
    assert sources[1].url == "https://docs.example.com/buckets"


def test_build_context_keeps_sources_after_a_short_chunk():
    short = (hit("Errors", "Code", "Function failed to load."), 4.0)
    _, sources = build_context([RANKED[0], short, RANKED[1]])
    assert [s.title for s in sources] == ["Storage", "Errors", "Buckets"]


def test_build_context_stops_when_budget_is_spent(monkeypatch):
    monkeypatch.setattr(answer, "MAX_CONTEXT_CHARS", 7000)
    big = [(hit(f"Page{i}", None, "x" * 3000), 1.0) for i in range(5)]
    context, sources = build_context(big)
    assert len(sources) == 3  # 3000 + 3000 + the last 1000 chars of the 7000 budget
    assert len(context) < 7200


def test_streams_answer_with_citations(monkeypatch):
    events, shown, done = run(monkeypatch, RANKED, ["The limit", " is 50 MB", " [1]."])
    assert [e["type"] for e in events][:2] == ["sources", "token"]
    assert shown == "The limit is 50 MB [1]."
    assert done["answered"] and done["cited"] == [1]


@pytest.mark.parametrize("tokens", [["NO_", "ANSWER"], [" NO_ANSWER", ".", " Sorry, not in the sources."]])
def test_model_no_answer_marker_is_never_shown(monkeypatch, tokens):
    _, shown, done = run(monkeypatch, RANKED, tokens)
    assert "NO_ANSWER" not in shown
    assert shown == HANDOFF_MESSAGE
    assert done["handoff"] and not done["answered"]


def test_short_answer_that_looks_like_marker_prefix_is_still_shown(monkeypatch):
    _, shown, done = run(monkeypatch, RANKED, ["NO"])
    assert shown == "NO" and done["answered"]


def test_llm_error_shows_busy_message_without_handoff(monkeypatch):
    import httpx
    from openai import RateLimitError

    def rate_limited(**_):
        resp = httpx.Response(429, request=httpx.Request("POST", "https://llm.example"))
        raise RateLimitError("quota", response=resp, body=None)

    monkeypatch.setattr(answer, "retrieve", lambda conn, q: RANKED)
    monkeypatch.setattr(answer, "llm", lambda: SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=rate_limited))))
    done = list(answer_stream(None, "question"))[-1]
    assert done["error"] == "RateLimitError"
    assert not done["answered"] and not done["handoff"]


@pytest.mark.parametrize("question", [
    "What's your refund policy?",
    "I was charged twice, can I get my money back?",
    "How do I dispute a charge on my invoice?",
])
def test_money_and_legal_questions_escalate_before_search(monkeypatch, question):
    def boom(*_):
        raise AssertionError("should not search or call the LLM")

    monkeypatch.setattr(answer, "retrieve", boom)
    monkeypatch.setattr(answer, "llm", boom)
    done = list(answer_stream(None, question))[-1]
    assert done["reason"] == "escalated" and done["handoff"]


@pytest.mark.parametrize("question", ["How do I cancel my subscription?", "How are credits applied to my invoice?"])
def test_billing_how_to_questions_are_not_escalated(question):
    assert not answer.should_escalate(question)


def test_no_relevant_sources_hands_off_without_calling_llm(monkeypatch):
    def boom():
        raise AssertionError("LLM should not be called")

    monkeypatch.setattr(answer, "retrieve", lambda conn, q: [])
    monkeypatch.setattr(answer, "llm", boom)
    events = list(answer_stream(None, "what's the capital of France?"))
    assert events[0] == {"type": "sources", "sources": []}
    assert events[-1]["handoff"] and events[-1]["timings"]["llm_ms"] == 0
