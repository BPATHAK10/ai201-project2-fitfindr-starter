# FitFindr

FitFindr is a multi-tool AI agent that helps you find secondhand clothing and figure out how to wear it. You describe what you want in plain language; the agent searches a mock listings dataset, suggests an outfit using your existing wardrobe, and writes a shareable, caption-style "fit card" — handling the messy cases (no matches, empty wardrobe, missing data) gracefully along the way.

The agent doesn't run a fixed script. It **branches on what each tool returns** — an impossible query stops after the search with a helpful message, while a matchable query flows through all three tools with state passing between them.

---

## Setup

**macOS / Linux:**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows:**
```bash
python -m venv .venv
source .venv/Scripts/activate
pip install -r requirements.txt
```

Set your Groq API key in a `.env` file (free key at [console.groq.com](https://console.groq.com)):
```
GROQ_API_KEY=your_key_here
```

## Run

**The web app (Gradio):**
```bash
python app.py
```
Open the URL printed in your terminal (usually <http://localhost:7860>). Type a query like `vintage graphic tee under $30`, pick a wardrobe, and click **Find it**.

**The planning loop from the CLI** (happy path + no-results path):
```bash
python agent.py
```

**The tests:**
```bash
pytest tests/                 # all tests (LLM tests call Groq)
pytest tests/ -m "not llm"    # offline only — fast, no API calls
```

---

## Tool Inventory

All signatures below match `tools.py` exactly.

### 1. `search_listings(description, size=None, max_price=None) -> list[dict]`
| Input | Type | Meaning |
|---|---|---|
| `description` | `str` | Free-text keywords for the desired item (e.g. `"vintage graphic tee"`). Scored against each listing's title + description + style_tags + category. |
| `size` | `str \| None` | Size filter, case-insensitive **substring** match (`"M"` matches `"S/M"`). `None` skips size filtering. |
| `max_price` | `float \| None` | Inclusive price ceiling. `None` skips price filtering. |

**Returns:** a `list[dict]` of full listing dicts (`id`, `title`, `description`, `category`, `style_tags`, `size`, `condition`, `price`, `colors`, `brand`, `platform`), sorted by keyword-overlap relevance (highest first), ties broken by lower price. Listings with zero keyword overlap are dropped. Returns `[]` when nothing matches.

**Purpose:** the only non-LLM tool — pure Python filtering + scoring over the 40-item mock dataset. It's the agent's entry point and the source of the item that flows through the rest of the pipeline.

### 2. `suggest_outfit(new_item, wardrobe) -> str`
| Input | Type | Meaning |
|---|---|---|
| `new_item` | `dict` | A listing dict (the item being considered) — the prompt uses its title, category, colors, and style_tags. |
| `wardrobe` | `dict` | `{"items": [ {id, name, category, colors, style_tags, notes}, ... ]}`. May be empty. |

**Returns:** a non-empty `str` of outfit suggestions. With a populated wardrobe it names specific owned pieces ("Pair this with your baggy jeans + chunky sneakers…"); with an empty wardrobe it returns general styling advice instead.

**Purpose:** calls the Groq LLM (`llama-3.3-70b-versatile`, temperature 0.7) to turn a found item + the user's closet into concrete, personalized styling ideas.

### 3. `create_fit_card(outfit, new_item) -> str`
| Input | Type | Meaning |
|---|---|---|
| `outfit` | `str` | The styling text from `suggest_outfit`. Must be non-empty. |
| `new_item` | `dict` | The listing dict — supplies title, price, and platform to mention once each. |

**Returns:** a 2–4 sentence `str` usable as an Instagram/TikTok caption — casual and authentic, not a product description. Uses **temperature 1.0**, so repeated calls on the same input produce different captions.

**Purpose:** calls the LLM to generate the shareable, social-media-style payoff of the interaction.

---

## How the Planning Loop Works

The loop lives in `run_agent(query, wardrobe)` in `agent.py`. It is **conditional**, not a fixed sequence:

1. **Parse the query** (no tool call). `_parse_query()` uses regex to extract `description`, `size`, and `max_price` from the raw text. This is deliberately deterministic (no LLM) so parsing is fast, free, and predictable. Result stored in `session["parsed"]`.
2. **Search.** Call `search_listings(description, size, max_price)`; store the list in `session["search_results"]`.
3. **Branch (the one real decision point):**
   - **If `search_results` is empty** → set `session["error"]` to a specific, actionable message naming what was searched and what to loosen, then **return the session immediately**. `suggest_outfit` and `create_fit_card` are *never* called; `fit_card` stays `None`.
   - **Otherwise** → continue.
4. **Select** `session["selected_item"] = search_results[0]` (top-ranked).
5. **Suggest outfit:** `suggest_outfit(selected_item, wardrobe)` → `session["outfit_suggestion"]`. (This tool internally branches on empty vs. populated wardrobe but always returns a string, so the loop proceeds either way.)
6. **Fit card:** `create_fit_card(outfit_suggestion, selected_item)` → `session["fit_card"]`.
7. **Return the session.** Success = `fit_card` populated and `error is None`.

Because of step 3, different inputs take visibly different paths: `"designer ballgown size XXS under $5"` stops after one tool call with an error, while `"vintage graphic tee under $30"` runs all three tools.

---

## State Management

A single `session` dict (built by `_new_session()`) is the one source of truth for the whole interaction. Each tool writes its output into the session, and the next tool reads its input from the session — the user never re-enters anything between steps.

| Key | Written by | Read by |
|---|---|---|
| `query` | session init (raw input) | parse step |
| `parsed` | parse step (`description`, `size`, `max_price`) | `search_listings` |
| `search_results` | `search_listings` | branch check + selection |
| `selected_item` | selection step (`search_results[0]`) | `suggest_outfit`, `create_fit_card` |
| `wardrobe` | session init (passed in) | `suggest_outfit` |
| `outfit_suggestion` | `suggest_outfit` | `create_fit_card` |
| `fit_card` | `create_fit_card` | final output |
| `error` | branch check (no-results only) | UI / caller (`None` = success) |

The key handoffs: `search_listings` → `selected_item` flows *unchanged* into `suggest_outfit`; `suggest_outfit`'s string flows into `create_fit_card`. This is verifiable — `session["selected_item"] is session["search_results"][0]` returns `True`, proving the same object (not a re-entered copy) flows downstream.

---

## Error Handling

Every tool handles its own failure mode; "fail silently" and "crash" are both avoided. Both LLM tools also wrap their network call in `try/except` and return a graceful fallback string on any API error.

| Tool | Failure mode | Agent response |
|---|---|---|
| `search_listings` | No results match | Returns `[]` (never raises). The loop sets `session["error"]` to a specific message and returns early **without** calling the other tools. |
| `suggest_outfit` | Wardrobe is empty (`items == []`) | Branches to a general-styling-advice prompt; returns a useful non-empty string instead of crashing or returning `""`. The loop still proceeds. |
| `create_fit_card` | `outfit` is empty / whitespace | Guard at the top returns a descriptive error string with **no LLM call** and no exception. |

**Concrete example from testing** (Milestone 5, no-results path):

```
$ python -c "from tools import search_listings; print(search_listings('designer ballgown', size='XXS', max_price=5))"
[]

# Full agent, same query:
error: No listings matched 'designer ballgown', size XXS, under $5. Try removing
       the size filter, raising your max price, or using broader keywords.
fit_card: None
```

The empty list never raises; the agent converts it into an actionable message and stops before `suggest_outfit` — `fit_card` is correctly `None`. (Similarly, `create_fit_card('', item)` returns *"Can't make a fit card without an outfit suggestion — generate an outfit first…"* rather than throwing.)

---

## Spec Reflection

**One way `planning.md` helped during implementation:** Writing the State Management table and the ASCII architecture diagram *before* coding forced me to decide that one `session` dict would be the single source of truth, with each tool writing to a named key and reading from another. When I implemented `run_agent()`, there was no ambiguity about where each value lived or how it passed between tools — I was essentially transcribing the diagram into code. It also made the empty-results branch an explicit, pre-designed decision rather than an afterthought, which is the part of the rubric most likely to be done wrong.

**One divergence from the spec, and why:** The spec described `search_listings`'s relevance scoring only as "keyword overlap." In implementation I added two things that weren't in the spec: a small stopword set (so filler words like "looking", "want", "size", "under" don't inflate scores) and a tie-breaker that sorts equal-score results by lower price. I discovered the need for both while testing in isolation — without stopwords, nearly every listing scored above zero on noisy queries, and without the tie-break the ordering of equally relevant items was arbitrary. The function's signature and return contract still match the spec; only the internal scoring got more precise.

---

## AI Usage

I used **Claude (via Claude Code)** as my coding assistant, working one tool/section at a time and reviewing the generated code against my `planning.md` spec before running it.

**Instance 1 — `search_listings` implementation.** *Input I gave:* the Tool 1 spec block from `planning.md` (the three parameters with types, the case-insensitive substring rule for `size`, the keyword-overlap scoring description, the full return-field list, and the "returns `[]`, never raises" failure mode) plus the `load_listings()` docstring. *What it produced:* a filter-then-score function using the data loader. *What I changed/overrode:* I had it add a **stopword filter** and a **tie-break by price** after I saw, during isolation testing, that noisy queries matched almost everything and that equal-score items had arbitrary order. I also confirmed it used `load_listings()` rather than re-opening the JSON file, and that it returned `[]` (not `None`) on no match — then locked the behavior in with three pytest cases.

**Instance 2 — the planning loop in `run_agent()`.** *Input I gave:* the Planning Loop section (the numbered branches), the State Management table, and the ASCII architecture diagram from `planning.md`, plus the `run_agent` TODO steps and `_new_session` dict from `agent.py`. *What it produced:* a `run_agent` that parsed the query, searched, branched on empty results, and chained the two LLM tools through the session. *What I changed/overrode:* I verified the critical requirement — that it **branches on the search result and returns early on `[]`** rather than calling all three tools unconditionally — and that every handoff routed through the session dict with no re-parsing or hardcoded values between steps. I also tightened the no-results error message to name the exact search terms and what to loosen, instead of a generic "no results found." I confirmed both paths with `python agent.py` and an identity check (`selected_item is search_results[0]`).

---

## Project Structure

```
ai201-project2-fitfindr-starter/
├── data/
│   ├── listings.json          # 40 mock secondhand listings
│   └── wardrobe_schema.json   # Wardrobe format + example/empty wardrobes
├── utils/
│   └── data_loader.py         # load_listings(), get_example_wardrobe(), get_empty_wardrobe()
├── tools.py                   # The 3 tools: search_listings, suggest_outfit, create_fit_card
├── agent.py                   # run_agent() planning loop + query parsing + session state
├── app.py                     # Gradio UI (handle_query maps session → 3 panels)
├── tests/test_tools.py        # pytest tests, one+ per failure mode
├── planning.md                # Spec written before implementation
└── requirements.txt
```
