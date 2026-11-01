from askdocs.evaluate import facts_found, first_gold_rank, page_of, summarize

BASE = "https://supabase.com/docs/guides/"


def test_page_of_strips_prefix_and_anchor():
    assert page_of(BASE + "storage/uploads/file-limits#global-file-size") == "storage/uploads/file-limits"
    assert page_of(BASE + "cron") == "cron"


def test_first_gold_rank_matches_any_gold_page():
    urls = [BASE + "a#x", BASE + "b", BASE + "c#y"]
    assert first_gold_rank(urls, ["c", "b"]) == 2
    assert first_gold_rank(urls, ["z"]) is None


def test_facts_found_needs_every_group_with_any_alternative():
    facts = [["50 MB", "50MB"], ["free"]]
    assert facts_found("On the Free plan the limit is 50MB [1].", facts)
    assert not facts_found("The limit is 50 MB [1].", facts)


def test_summarize_retrieval_only():
    results = [
        {"answerable": True, "gold_rank": 1, "gate_handoff": False, "retrieve_ms": 400},
        {"answerable": True, "gold_rank": None, "gate_handoff": False, "retrieve_ms": 600},
        {"answerable": False, "gate_handoff": True, "retrieve_ms": 500},
    ]
    s = summarize(results, retrieval_only=True)
    assert s["retrieval hit@1"] == "50% (1/2)"
    assert s["gate: off-topic handed off"] == "100% (1/1)"
    assert s["retrieval p50"] == "500 ms"
