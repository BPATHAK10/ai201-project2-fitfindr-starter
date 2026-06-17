"""
tests/test_tools.py

Tests for the three FitFindr tools, with at least one test per failure mode.

Run from the project root with:
    pytest tests/

Tests are split into two groups:
  - search_listings tests run offline (no API calls).
  - suggest_outfit / create_fit_card happy-path tests call the Groq LLM and are
    marked `llm`. Skip them with:  pytest tests/ -m "not llm"
"""

import pytest

from tools import search_listings, suggest_outfit, create_fit_card
from utils.data_loader import get_example_wardrobe, get_empty_wardrobe


# ── search_listings (offline) ───────────────────────────────────────────────

def test_search_returns_results():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    assert isinstance(results, list)
    assert len(results) > 0
    # every result is a full listing dict
    assert all("price" in item and "title" in item for item in results)


def test_search_empty_results():
    # impossible query — no exception, just an empty list
    results = search_listings("designer ballgown", size="XXS", max_price=5)
    assert results == []


def test_search_price_filter():
    results = search_listings("jacket", size=None, max_price=40)
    assert all(item["price"] <= 40 for item in results)


def test_search_size_filter_case_insensitive():
    # "m" should match listings whose size contains M, e.g. "M" or "S/M"
    results = search_listings("tee", size="M", max_price=None)
    assert all("m" in item["size"].lower() for item in results)


def test_search_sorted_by_relevance():
    # more specific query keywords should still return tops, best match first
    results = search_listings("vintage graphic tee", size=None, max_price=None)
    assert len(results) > 0
    # top result should be a top (tees live in the 'tops' category)
    assert results[0]["category"] == "tops"


# ── create_fit_card failure mode (offline — guard returns before any LLM call) ──

def test_fit_card_empty_outfit_returns_error_string():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    out = create_fit_card("", results[0])
    assert isinstance(out, str)
    assert out.strip() != ""
    # it's the guard message, not a real caption
    assert "outfit" in out.lower()


def test_fit_card_whitespace_outfit_returns_error_string():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    out = create_fit_card("    ", results[0])
    assert isinstance(out, str) and out.strip() != ""


# ── LLM-backed tests (require GROQ_API_KEY; call the network) ────────────────

@pytest.mark.llm
def test_suggest_outfit_empty_wardrobe_gives_advice():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    out = suggest_outfit(results[0], get_empty_wardrobe())
    # empty wardrobe must NOT crash and must return a useful non-empty string
    assert isinstance(out, str)
    assert len(out.strip()) > 0


@pytest.mark.llm
def test_suggest_outfit_with_wardrobe_returns_text():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    out = suggest_outfit(results[0], get_example_wardrobe())
    assert isinstance(out, str)
    assert len(out.strip()) > 0


@pytest.mark.llm
def test_fit_card_varies_across_calls():
    results = search_listings("vintage graphic tee", size=None, max_price=50)
    outfit = "Pair it with baggy jeans and chunky sneakers."
    a = create_fit_card(outfit, results[0])
    b = create_fit_card(outfit, results[0])
    # high temperature should produce different captions for the same input
    assert a != b
