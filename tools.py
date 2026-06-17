"""
tools.py

The three required FitFindr tools. Each tool is a standalone function that
can be called and tested independently before being wired into the agent loop.

Complete and test each tool before moving to agent.py.

Tools:
    search_listings(description, size, max_price)  → list[dict]
    suggest_outfit(new_item, wardrobe)              → str
    create_fit_card(outfit, new_item)               → str
"""

import os
import re

from dotenv import load_dotenv
from groq import Groq

from utils.data_loader import load_listings

load_dotenv()

MODEL = "llama-3.3-70b-versatile"

# Tokens too generic to be useful as search keywords.
_STOPWORDS = {
    "a", "an", "the", "and", "or", "for", "with", "to", "of", "in", "on",
    "my", "i", "im", "looking", "want", "need", "some", "something",
    "under", "size", "that", "this", "is", "are", "it", "me", "please",
}


# ── Groq client ───────────────────────────────────────────────────────────────

def _get_groq_client():
    """Initialize and return a Groq client using GROQ_API_KEY from .env."""
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise ValueError(
            "GROQ_API_KEY not set. Add it to a .env file in the project root."
        )
    return Groq(api_key=api_key)


def _chat(prompt: str, temperature: float = 0.7) -> str:
    """Send a single-turn prompt to Groq and return the response text."""
    client = _get_groq_client()
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature,
    )
    return resp.choices[0].message.content.strip()


# ── Tool 1: search_listings ───────────────────────────────────────────────────

def search_listings(
    description: str,
    size: str | None = None,
    max_price: float | None = None,
) -> list[dict]:
    """
    Search the mock listings dataset for items matching the description,
    optional size, and optional price ceiling.

    Args:
        description: Keywords describing what the user is looking for
                     (e.g., "vintage graphic tee").
        size:        Size string to filter by, or None to skip size filtering.
                     Matching is case-insensitive (e.g., "M" matches "S/M").
        max_price:   Maximum price (inclusive), or None to skip price filtering.

    Returns:
        A list of matching listing dicts, sorted by relevance (best match first).
        Returns an empty list if nothing matches — does NOT raise an exception.

    Each listing dict has the following fields:
        id, title, description, category, style_tags (list), size,
        condition, price (float), colors (list), brand, platform

    TODO:
        1. Load all listings with load_listings().
        2. Filter by max_price and size (if provided).
        3. Score each remaining listing by keyword overlap with `description`.
        4. Drop any listings with a score of 0 (no relevant matches).
        5. Sort by score, highest first, and return the listing dicts.

    Before writing code, fill in the Tool 1 section of planning.md.
    """
    listings = load_listings()

    # 1. Filter by price ceiling (inclusive) and size, when provided.
    candidates = []
    for item in listings:
        if max_price is not None and item["price"] > max_price:
            continue
        if size is not None and size.strip().lower() not in item["size"].lower():
            continue
        candidates.append(item)

    # 2. Score remaining listings by keyword overlap with the description.
    query_tokens = {
        tok for tok in re.findall(r"[a-z0-9]+", description.lower())
        if len(tok) > 1 and tok not in _STOPWORDS
    }

    scored = []
    for item in candidates:
        haystack = " ".join([
            item["title"],
            item["description"],
            " ".join(item["style_tags"]),
            item["category"],
        ]).lower()
        score = sum(1 for tok in query_tokens if tok in haystack)
        if score > 0:                      # 3. drop listings with no relevant match
            scored.append((score, item))

    # 4. Sort by score (highest first); break ties by lower price.
    scored.sort(key=lambda pair: (-pair[0], pair[1]["price"]))
    return [item for _, item in scored]


# ── Tool 2: suggest_outfit ────────────────────────────────────────────────────

def suggest_outfit(new_item: dict, wardrobe: dict) -> str:
    """
    Given a thrifted item and the user's wardrobe, suggest 1–2 complete outfits.

    Args:
        new_item: A listing dict (the item the user is considering buying).
        wardrobe: A wardrobe dict with an 'items' key containing a list of
                  wardrobe item dicts. May be empty — handle this gracefully.

    Returns:
        A non-empty string with outfit suggestions.
        If the wardrobe is empty, offer general styling advice for the item
        rather than raising an exception or returning an empty string.

    TODO:
        1. Check whether wardrobe['items'] is empty.
        2. If empty: call the LLM with a prompt for general styling ideas
           (what kinds of items pair well, what vibe it suits, etc.).
        3. If not empty: format the wardrobe items into a prompt and ask
           the LLM to suggest specific outfit combinations using the new item
           and named pieces from the wardrobe.
        4. Return the LLM's response as a string.

    Before writing code, fill in the Tool 2 section of planning.md.
    """
    item_desc = (
        f"{new_item['title']} "
        f"(category: {new_item['category']}, "
        f"colors: {', '.join(new_item['colors'])}, "
        f"style: {', '.join(new_item['style_tags'])})"
    )

    items = wardrobe.get("items", [])

    if not items:
        # Empty-wardrobe branch: general styling advice, no specific pieces.
        prompt = (
            "You are a personal stylist. The user just found this secondhand item:\n"
            f"{item_desc}\n\n"
            "They have not entered any wardrobe yet, so give general styling advice: "
            "what kinds of pieces pair well with it, what vibe/occasions it suits, and "
            "one concrete styling tip. Keep it to 2-3 short sentences, friendly and practical."
        )
    else:
        # Populated wardrobe: suggest outfits using named pieces they own.
        wardrobe_lines = "\n".join(
            f"- {it['name']} ({it['category']}; {', '.join(it.get('colors', []))})"
            for it in items
        )
        prompt = (
            "You are a personal stylist. The user just found this secondhand item:\n"
            f"{item_desc}\n\n"
            "Here is the user's current wardrobe:\n"
            f"{wardrobe_lines}\n\n"
            "Suggest 1-2 complete outfit combinations that pair the new item with "
            "SPECIFIC pieces named above. Reference the wardrobe pieces by name, and "
            "include one concrete styling tip (e.g. tuck, roll, layer). Keep it to "
            "2-4 short sentences, written to the user ('Pair this with your...')."
        )

    try:
        return _chat(prompt, temperature=0.7)
    except Exception:
        # Network/LLM failure: degrade gracefully so the planning loop continues.
        return (
            f"Couldn't generate a styling suggestion right now, but {new_item['title']} "
            "would pair well with neutral basics and your go-to shoes."
        )


# ── Tool 3: create_fit_card ───────────────────────────────────────────────────

def create_fit_card(outfit: str, new_item: dict) -> str:
    """
    Generate a short, shareable outfit caption for the thrifted find.

    Args:
        outfit:   The outfit suggestion string from suggest_outfit().
        new_item: The listing dict for the thrifted item.

    Returns:
        A 2–4 sentence string usable as an Instagram/TikTok caption.
        If outfit is empty or missing, return a descriptive error message
        string — do NOT raise an exception.

    The caption should:
    - Feel casual and authentic (like a real OOTD post, not a product description)
    - Mention the item name, price, and platform naturally (once each)
    - Capture the outfit vibe in specific terms
    - Sound different each time for different inputs (use higher LLM temperature)

    TODO:
        1. Guard against an empty or whitespace-only outfit string.
        2. Build a prompt that gives the LLM the item details and the outfit,
           and asks for a caption matching the style guidelines above.
        3. Call the LLM and return the response.

    Before writing code, fill in the Tool 3 section of planning.md.
    """
    # 1. Guard against an empty / whitespace-only outfit — no LLM call.
    if not outfit or not outfit.strip():
        return (
            "Can't make a fit card without an outfit suggestion — "
            "generate an outfit first, then try again."
        )

    # 2. Build the caption prompt from the item details + outfit.
    prompt = (
        "Write a short, casual social-media caption (2-4 sentences) for an outfit post. "
        "It should sound like a real person's OOTD/thrift-haul caption — NOT a product "
        "description. Be specific about the vibe. Mention the item name, its price, and the "
        "platform it was found on exactly once each, woven in naturally. A little lowercase "
        "energy and an emoji or two is welcome.\n\n"
        f"Item: {new_item['title']}\n"
        f"Price: ${new_item['price']:.0f}\n"
        f"Platform: {new_item['platform']}\n"
        f"How I'm styling it: {outfit}\n\n"
        "Caption:"
    )

    # 3. High temperature so repeated calls vary; degrade gracefully on error.
    try:
        return _chat(prompt, temperature=1.0)
    except Exception:
        return (
            f"thrifted this {new_item['title']} off {new_item['platform']} "
            f"for ${new_item['price']:.0f} and i'm obsessed ✨"
        )
