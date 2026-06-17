# FitFindr — planning.md

> Complete this document before writing any implementation code.
> Your spec and agent diagram are what you'll use to direct AI tools (Claude, Copilot, etc.) to generate your implementation — the more specific they are, the more useful the generated code will be.
> Your planning.md will be reviewed as part of your submission.
> Update it before starting any stretch features.

---

## Tools

List every tool your agent will use. For each tool, fill in all four fields.
You must have at least 3 tools. The three required tools are listed — add any additional tools below them.

### Tool 1: search_listings

**What it does:**
Searches the mock listings dataset (40 items loaded via `load_listings()`) for pieces matching the user's keywords, optionally filtered by size and a price ceiling. It scores each surviving listing by keyword overlap and returns them best-match-first. This is the only non-LLM tool — it's pure Python filtering/scoring.

**Input parameters:**
- `description` (str): Free-text keywords describing the wanted item, e.g. `"vintage graphic tee"`. Used for keyword scoring against each listing's `title` + `description` + `style_tags`.
- `size` (str | None): Size string to filter by, e.g. `"M"`. Matching is case-insensitive substring (`"m" in "s/m"` → match). `None` skips size filtering. (Note: the dataset's `size` field is inconsistent — `"M"`, `"S/M"`, `"W30 L30"`, `"US 8"`, `"One Size"` — so a loose substring match is intentional; numeric/letter sizes simply won't cross-match.)
- `max_price` (float | None): Inclusive price ceiling. `None` skips price filtering.

**What it returns:**
A `list[dict]` of matching listings, sorted by relevance score (highest first). Each dict is a full listing with: `id` (str), `title` (str), `description` (str), `category` (str), `style_tags` (list[str]), `size` (str), `condition` (str), `price` (float), `colors` (list[str]), `brand` (str | None), `platform` (str). Listings with a keyword score of 0 are dropped (no spurious matches). Returns `[]` when nothing matches.

**What happens if it fails or returns nothing:**
Returns an empty list `[]` — never raises. The agent (in `run_agent`) detects the empty list, sets `session["error"]` to a specific, actionable message (e.g. *"No listings matched 'designer ballgown' in size XXS under $5. Try removing the size filter, raising your max price, or using broader keywords."*), and returns the session early **without** calling `suggest_outfit`.

---

### Tool 2: suggest_outfit

**What it does:**
Given the selected thrift item and the user's wardrobe, calls the LLM (Groq `llama-3.3-70b-versatile`) to describe 1–2 complete outfit combinations that pair the new item with named pieces the user already owns, including a small styling tip (e.g. tuck/roll/layer).

**Input parameters:**
- `new_item` (dict): A listing dict from `search_listings` (the item being considered). The prompt uses its `title`, `category`, `colors`, and `style_tags`.
- `wardrobe` (dict): A wardrobe dict shaped `{"items": [ {id, name, category, colors, style_tags, notes}, ... ]}`. May be empty (`{"items": []}`) — must be handled.

**What it returns:**
A non-empty `str` of outfit suggestions written in second person ("Pair this with your…"). When the wardrobe has items, it names specific wardrobe pieces (e.g. "your baggy straight-leg jeans + chunky white sneakers"). When the wardrobe is empty, it returns general styling advice for the item (what kinds of pieces pair well, what vibe it suits) — still a useful non-empty string.

**What happens if it fails or returns nothing:**
- **Empty wardrobe** (`wardrobe["items"]` is empty): branch to a general-advice prompt instead of crashing or returning `""`. The agent still proceeds to `create_fit_card`.
- **LLM/network error**: catch the exception and return a graceful fallback string (e.g. *"Couldn't generate a styling suggestion right now, but this <item> would pair well with neutral basics."*) so the planning loop can continue rather than crash.

---

### Tool 3: create_fit_card

**What it does:**
Calls the LLM (with a **higher temperature**, ~0.9–1.0) to turn the outfit suggestion + item details into a short, casual, caption-style blurb — the kind of thing someone captions an OOTD post with. Output must vary run-to-run for the same input.

**Input parameters:**
- `outfit` (str): The styling text returned by `suggest_outfit`. Must be non-empty.
- `new_item` (dict): The listing dict — the prompt pulls `title`, `price`, and `platform` to mention naturally (once each).

**What it returns:**
A 2–4 sentence `str` usable as an Instagram/TikTok caption — casual, authentic, not a product description. Mentions the item name, price, and platform once each and captures the outfit vibe. Because of the high temperature, repeated calls on the same input produce different captions (verified in Milestone 3 by running it several times).

**What happens if it fails or returns nothing:**
- **Empty / whitespace-only `outfit`**: guard at the top and immediately return a descriptive error string (e.g. *"Can't make a fit card without an outfit suggestion — generate an outfit first."*) — no LLM call, no exception.
- **LLM/network error**: catch and return a fallback caption string rather than crashing.

---

### Additional Tools (if any)

<!-- Copy the block above for any tools beyond the required three -->

---

## Planning Loop

**How does your agent decide which tool to call next?**

The loop lives in `run_agent(query, wardrobe)` and is driven by what each step returns — it is **not** a fixed "always call all three" sequence. The decision points:

1. **Parse the query** (no tool call). Extract `description`, `size`, `max_price` from the raw query using simple regex/string parsing (chosen over an LLM call so parsing stays deterministic, fast, and free):
   - `max_price`: regex for a number after `$` or the word `under`, e.g. `r"(?:under|<|\$)\s*\$?(\d+(?:\.\d+)?)"` → `float`, else `None`.
   - `size`: regex for `size\s+(\S+)` or a standalone size token (`XS/S/M/L/XL` or `W\d+`/`US \d+`), else `None`.
   - `description`: the query with the price/size phrases stripped out (fallback: the whole query).
   - Store all three in `session["parsed"]`.

2. **Call `search_listings(description, size, max_price)`.** Store the list in `session["search_results"]`.
   - **BRANCH (the key conditional):** `if not session["search_results"]:` → set `session["error"]` to a specific message naming what was searched and what to loosen, then **`return session` immediately**. `suggest_outfit` and `create_fit_card` are NOT called. `session["fit_card"]` stays `None`.
   - `else:` continue.

3. **Select the item:** `session["selected_item"] = session["search_results"][0]` (top-ranked result).

4. **Call `suggest_outfit(selected_item, wardrobe)`.** Store in `session["outfit_suggestion"]`. This tool internally branches on empty vs. populated wardrobe, but the loop proceeds either way (a non-empty string always comes back).

5. **Call `create_fit_card(outfit_suggestion, selected_item)`.** Store in `session["fit_card"]`.

6. **Return `session`.**

**How it knows it's done:** the loop is a single linear pass with one early-exit branch. It terminates either early at step 2 (no results → error set) or after step 5 (full success → `fit_card` populated, `error` is `None`). Different inputs therefore produce visibly different paths: an impossible query stops after one tool call with an error; a matchable query runs all three.

---

---

## State Management

**How does information from one tool get passed to the next?**

A single `session` dict (created by `_new_session()` in `agent.py`) is the one source of truth for the whole interaction. Each tool's output is written into the session, and the next tool reads its input from the session — the user never re-enters anything between steps.

| Key | Type | Written by | Read by |
|---|---|---|---|
| `query` | str | `_new_session` (the raw user input) | parse step |
| `parsed` | dict | parse step (`description`, `size`, `max_price`) | `search_listings` call |
| `search_results` | list[dict] | `search_listings` | branch check + item selection |
| `selected_item` | dict | item-selection step (`search_results[0]`) | `suggest_outfit`, `create_fit_card` |
| `wardrobe` | dict | `_new_session` (passed in) | `suggest_outfit` |
| `outfit_suggestion` | str | `suggest_outfit` | `create_fit_card` |
| `fit_card` | str | `create_fit_card` | final output |
| `error` | str \| None | branch check (only on no-results) | UI / caller (`None` = success) |

**Flow of the key handoffs:** `search_listings` → `selected_item` → flows *unchanged* into `suggest_outfit`; `suggest_outfit`'s string → `outfit_suggestion` → flows into `create_fit_card`. Because everything routes through one dict, I can prove state passed correctly by printing `session["selected_item"]` and confirming it's the exact dict given to `suggest_outfit`, and `session["outfit_suggestion"]` is exactly what went into `create_fit_card` (the Milestone 4 verification step).

---

---

## Error Handling

For each tool, describe the specific failure mode you're handling and what the agent does in response.

| Tool | Failure mode | Agent response |
|------|-------------|----------------|
| search_listings | No results match the query | Returns `[]` (never raises). The loop sets `session["error"]` to a specific, actionable message naming the search and what to loosen — e.g. *"No listings matched 'designer ballgown' in size XXS under $5. Try removing the size filter, raising your max price, or using broader keywords."* — then returns early **without** calling the other tools. The UI shows this in the listing panel; outfit/fit-card panels stay empty. |
| suggest_outfit | Wardrobe is empty (`items == []`) | Detects the empty wardrobe and switches to a general-styling-advice prompt, returning a useful non-empty string (e.g. how to pair the piece, what vibe it suits) instead of crashing or returning `""`. The loop still proceeds to `create_fit_card`. (Also: any LLM/network exception is caught and returns a graceful fallback string.) |
| create_fit_card | Outfit input is missing or incomplete | Guards against an empty/whitespace-only `outfit` string at the top and returns a descriptive error string — e.g. *"Can't make a fit card without an outfit suggestion — generate an outfit first."* — with no LLM call and no exception. (Also: any LLM/network exception is caught and returns a fallback caption.) |

---

## Architecture

```
User query  +  wardrobe choice  (app.py → handle_query)
    │
    ▼
run_agent(query, wardrobe)  ── creates ──►  SESSION DICT  (single source of truth)
    │                                       { query, parsed, search_results,
    │                                         selected_item, wardrobe,
    │  Planning Loop                          outfit_suggestion, fit_card, error }
    │                                                  ▲
    ├─ 1. parse query (regex) ──────────────► session["parsed"] = {description, size, max_price}
    │
    ├─ 2. search_listings(description, size, max_price)
    │        │                                ► session["search_results"]
    │        │
    │        ├── results == []  ──►  [ERROR BRANCH]
    │        │                       session["error"] = "No listings matched… try loosening…"
    │        │                       return session   ✗ (suggest_outfit / create_fit_card NOT called)
    │        │
    │        └── results == [item, …]
    │                 │
    │                 ▼
    │           session["selected_item"] = results[0]
    │                 │  (flows unchanged ▼)
    ├─ 3. suggest_outfit(selected_item, wardrobe)
    │        │   └─ wardrobe empty? → general-advice prompt (still returns a string)
    │        │                                ► session["outfit_suggestion"]
    │                 │  (flows ▼)
    ├─ 4. create_fit_card(outfit_suggestion, selected_item)
    │        │   └─ outfit empty? → return error string (no LLM call)
    │        │                                ► session["fit_card"]
    │
    └─ 5. return session  ──────────────────► handle_query maps fields → 3 UI panels
                                              (listing | outfit idea | fit card)
```

Every arrow that writes `session[...]` is a state handoff; the only control branch is the empty-results early return at step 2.

---

## AI Tool Plan

**AI tool used:** Claude (via Claude Code in the editor). My working method is **one tool/section at a time** — I never ask it to generate the whole project at once, because a single broken tool inside a big generation is far harder to isolate than a tool I implemented and tested on its own (this mirrors the Milestone 3 "test in isolation" discipline). For every step below I follow the same three-part contract: **(1) what I give it**, **(2) what I expect back**, **(3) how I verify before trusting it** — and I read the generated code against my spec *before* running it, not after.

### Milestone 3 — Individual tool implementations

**`search_listings` (pure Python, no LLM)**
- **Input I give Claude:** the Tool 1 spec block from this doc (the three parameters with types, the case-insensitive substring rule for `size`, the keyword-overlap scoring description, the full return-field list, and the "returns `[]`, never raises" failure mode) + the `load_listings()` docstring from `utils/data_loader.py` + the existing `search_listings` stub signature from `tools.py`. Explicit instruction: *"implement this stub using `load_listings()`; do not re-read the JSON file; do not change the signature."*
- **What I expect back:** a function that (a) loads listings via the helper, (b) applies the `max_price` filter (inclusive) and the `size` substring filter only when those args are non-`None`, (c) tokenizes `description` and scores each remaining listing by overlap against `title` + `description` + `style_tags`, (d) drops score-0 listings, (e) returns the surviving dicts sorted by score descending.
- **How I verify before trusting:** read the code and check each item — uses `load_listings()` (✓ no `open()`/`json.load` in the tool), filters by **all three** params, comparison is case-insensitive, returns `[]` not `None`/exception on no match, signature unchanged. Then run the three Milestone-3 pytest cases (`test_search_returns_results`, `test_search_empty_results`, `test_search_price_filter`) plus a manual spot-check that the top result for `"vintage graphic tee"` is actually a tee. **If it diverges** (e.g. it re-reads the file, or returns `None`, or only filters on price), I correct that specific point and re-run.

**`suggest_outfit` (Groq LLM)**
- **Input I give Claude:** the Tool 2 spec block + the wardrobe schema shape (`{"items": [{id, name, category, colors, style_tags, notes}]}`) + the empty-wardrobe row from the Error Handling table + the `_get_groq_client()` helper and model id (`llama-3.3-70b-versatile`). Instruction: *"two prompt branches — populated wardrobe vs. empty wardrobe — and the empty check must come before any indexing into `items`."*
- **What I expect back:** a function that checks `wardrobe["items"]` first; if non-empty, formats the item names into the prompt and asks for 1–2 outfits naming specific owned pieces; if empty, asks for general styling advice for the item; wraps the LLM call in try/except and returns a fallback string on error. Always returns a non-empty `str`.
- **How I verify before trusting:** read the code to confirm the empty-wardrobe branch is reached *before* any `items[0]`-style access, and that the call is wrapped in try/except. Then run it twice — once with `get_example_wardrobe()` (expect it to name real wardrobe pieces like "baggy jeans"/"chunky sneakers") and once with `get_empty_wardrobe()` (expect general advice, no crash, non-empty). **If it diverges** (e.g. it indexes `items` before the empty check, or returns `""`), I rewrite that branch and re-test both wardrobes.

**`create_fit_card` (Groq LLM, high temperature)**
- **Input I give Claude:** the Tool 3 spec block (empty/whitespace-`outfit` guard returning an error string with no LLM call; temperature ~0.9–1.0; mention item name, price, and platform once each; casual caption voice, not a product description) + the stub signature `create_fit_card(outfit, new_item)`.
- **What I expect back:** a guard at the top that returns a descriptive error string when `outfit` is empty/whitespace, then a high-temperature LLM call that returns a 2–4 sentence caption, wrapped in try/except.
- **How I verify before trusting:** read the code to confirm the empty-`outfit` guard runs before the LLM call and that temperature is set high. Then (a) call it 3× on the **same** input and confirm the three captions differ (if identical, bump temperature); (b) call it with `outfit=""` and confirm a descriptive error string, not an exception; (c) eyeball one caption to confirm it reads like a post, not a product blurb. **If it diverges** (identical outputs → raise temperature; reads like a product description → tighten the prompt's voice instructions), I adjust and re-run.

### Milestone 4 — Planning loop and state management

- **Input I give Claude:** the full **Planning Loop** section (all numbered branches, especially the empty-results early return), the **State Management** table (which key each tool writes/reads), the **Architecture** ASCII diagram, and the `run_agent` TODO steps + `_new_session` dict from `agent.py`. Instruction: *"follow the session-dict handoffs exactly; the only control branch is the empty-search early return; do not call all three tools unconditionally."*
- **What I expect back:** a `run_agent` that parses the query into `session["parsed"]`, calls `search_listings`, **and if results are empty sets `session["error"]` and returns immediately** (no `suggest_outfit`/`create_fit_card` call), otherwise selects `search_results[0]` → `suggest_outfit` → `create_fit_card`, writing each result into the session, then returns the session.
- **How I verify before trusting:** read the generated code and confirm — (a) it branches on the search result rather than running a fixed 3-call sequence, (b) every handoff goes through the session dict (no re-parsing, no hardcoded values between steps), (c) `suggest_outfit` is never reachable with an empty list. Then run `python agent.py`: the happy-path query must populate `session["fit_card"]` with `error is None`, and the built-in no-results query (`"designer ballgown size XXS under $5"`) must leave `fit_card = None` with a specific `error` set. I'll also print `session["selected_item"]` and `session["outfit_suggestion"]` mid-run to prove state passed unchanged between tools. **If it diverges** (e.g. it calls all three tools regardless, or re-parses the query inside a later step instead of reading the session), I restructure that section to match the diagram and re-run both paths.

---

## A Complete Interaction (Step by Step)

**What FitFindr needs to do?:**
FitFindr takes a natural-language thrifting request and orchestrates three tools to go from "what am I looking for" to a shareable post. A user query first triggers `search_listings`, which filters the mock listings by description, size, and max price. If it's find matches the agent picks the top one and passes that item into `suggest_outfit`, which uses the user's wardrobe to describe how to style the piece, and that styling text then flows into `create_fit_card`, which writes a short caption-style blurb. If `search_listings` returns nothing the agent stops and tells the user what to adjust (it never calls `suggest_outfit` with empty input). If the wardrobe is empty `suggest_outfit` falls back to general styling advice; and if the outfit text is missing `create_fit_card` returns an error message instead of crashing.

Write out what a full user interaction looks like from start to finish — tool call by tool call. Use a specific example query.

**Example user query:** "I'm looking for a vintage graphic tee under $30. I mostly wear baggy jeans and chunky sneakers. What's out there and how would I style it?"

**Step 0 — Parse:** `run_agent` parses the query → `parsed = {description: "vintage graphic tee", size: None, max_price: 30.0}` (no size mentioned). Stored in `session["parsed"]`.

**Step 1 — Search:** Calls `search_listings("vintage graphic tee", size=None, max_price=30.0)`. Scoring favors listings whose title/description/style_tags overlap "vintage", "graphic", "tee" and whose price ≤ $30 — e.g. `lst_006` ("Graphic Tee — 2003 Tour Bootleg Style", $24, style_tags include `graphic tee`/`vintage`) and `lst_033` ("Vintage Band Tee — Faded Grey", $19). Returns a non-empty list sorted best-first → stored in `session["search_results"]`. Not empty → no error branch.

**Step 2 — Select + suggest:** `session["selected_item"] = search_results[0]` (the top tee, say `lst_006`). Calls `suggest_outfit(selected_item, wardrobe)` with the example wardrobe (baggy jeans, chunky white sneakers, etc.). Returns something like *"Pair this faded graphic tee with your baggy dark-wash jeans and chunky white sneakers for an easy 90s streetwear look — tuck the front hem slightly and add your brown leather belt."* → stored in `session["outfit_suggestion"]`.

**Step 3 — Fit card:** Calls `create_fit_card(outfit_suggestion, selected_item)`. Returns a caption like *"finally thrifted the perfect bootleg graphic tee off depop for $24 🤎 styled it w/ my baggy jeans + chunky sneaks and it's so me. full fit in stories ✨"* → stored in `session["fit_card"]`. `error` stays `None`. Returns the session.

**Final output to user:** The Gradio UI's three panels populate — **Top listing found:** the tee's title, price, platform, condition; **Outfit idea:** the styling suggestion from Step 2; **Your fit card:** the shareable caption from Step 3.
