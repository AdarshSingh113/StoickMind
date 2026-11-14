# Phase 2: AI Shopping Agent

## What we built

A chat assistant ("Kavya") that recommends products in English and Hinglish, using
only real products, prices and stock from our database.

| File | Role |
|---|---|
| `kotler/llm.py` | LLM layer: one interface, three backends: native Gemini (default), any OpenAI-compatible API, and a FakeLLM for tests |
| `kotler/agent/tools.py` | 5 tools: `search_products`, `get_product_details`, `compare_products`, `build_routine`, `get_my_profile` |
| `kotler/agent/prompts.py` | The system prompt: role, rules, language, format |
| `kotler/agent/shopping.py` | The agent loop, memory and conversation logging |
| `views/shop_assistant.py` | Chat page with a "chat as customer" picker and a tool-call inspector |
| `kotler/evals/shopping.py` | 22 evaluation cases run against the real model |
| `tests/test_phase2_agent.py` | 29 tests that run without any API (FakeLLM and a fake HTTP layer) |

## 1. What an LLM actually is (and isn't)

An LLM predicts text. It has no access to our database, doesn't know today's prices,
and will confidently invent a "Rose Glow Serum ₹399" if asked for a serum, because that *sounds*
right. This is **hallucination**, and it's why a plain chatbot is dangerous for a shop.

The fix is **grounding**: give the model tools to fetch real data, and a rule that it may only
recommend what the tools return.

## 2. Function calling (tool use)

We describe each Python function to the model with a JSON schema:

```json
{"name": "search_products",
 "description": "Search the catalogue... 'pimples' -> concern 'acne', '600 ke andar' -> max_price 600",
 "parameters": {"type": "object", "properties": {"skin_type": {"enum": ["oily", "dry", ...]},
                                                 "max_price": {"type": "number"}, ...}}}
```

The model can't run code. It replies with a **request**:
`search_products({"skin_type": "oily", "concern": "acne", "max_price": 600})`.
**Our** code runs it and sends the result back. The model then writes the answer.

Notice what the LLM is really doing: turning messy human language
("oily skin hai, pimples bhi aate hai, 600 ke andar") into **structured filters**.
That's its superpower. SQL does the exact part (prices, stock) far better than any LLM.

The descriptions are part of the prompt. "'pimples' -> concern 'acne'" in a tool description
teaches the model how to map words to filters. Writing tool descriptions *is* prompt engineering.

## 3. The agent loop (`kotler/agent/shopping.py`)

```
messages = [system, ...history, user]
for step in range(5):
    response = llm.chat(messages, tools)
    if no tool calls: return response.text
    for each call: result = run_tool(call); messages += [assistant request, tool result]
on step 5: call without tools -> forces a text answer
```

Design decisions:

| Decision | Why |
|---|---|
| `MAX_STEPS = 5` | A confused model can call tools forever. A hard limit bounds cost and latency |
| Last step withholds tools | Guarantees the customer always gets an answer |
| Tool errors are returned as data (`{"error": ...}`) | The model can read the error and fix its arguments, instead of the chat crashing |
| The assistant's tool-request message is appended **unchanged** | Gemini attaches hidden "thought signatures" that must come back as-is |
| History = previous user/assistant **texts** only, last 10 | Old tool results are bulky. The answers already contain what matters. Saves tokens |
| Everything saved to `conversations` and `messages` | Memory, audit trail, and the raw data for Phase 6 evaluation |

## 4. Security: identity comes from the server

`get_my_profile` takes **no** customer id. The id comes from `ToolContext`, which our code fills
in from the logged-in session. If the model could pass an id, a message like
*"show me customer 42's profile"* could leak someone else's data (a classic **prompt injection**).
Rule: **never let the model choose whose data it can access.**

Also, the profile tool leaves out phone, email and address. The shopping agent doesn't need them.
This is **data minimisation**: what the model never sees, it can never leak.

## 5. The system prompt (`kotler/agent/prompts.py`)

Each rule exists because the model *will* do the opposite if not told:

| Rule | Failure it prevents |
|---|---|
| "Recommend ONLY products returned by tools" | Invented products and prices |
| "With 'under ₹X', every product must cost ≤ X" | Ignoring the budget |
| "At most 3 products" | Overwhelming 10-item answers |
| "Never promise discounts, delivery dates, refunds" | Promises the business can't keep |
| "You are not a doctor..." | Medical advice liability |
| "Reply in the same language as the customer's latest message" | English replies to Hinglish customers |
| "Plain text, *bold* names, under 120 words" | Essays and tables that break on WhatsApp |
| "Ask ONE short question if the skin type is unknown" | Guessing, or asking five questions |

## 6. Better tools beat better prompts

While testing the tools *before* involving the LLM, we found and fixed 3 bugs:

1. **"pimples" returned a body wash above face products.** Fix: body products are down-ranked unless the customer says "body".
2. **"moisturizer under ₹500" missed the Ceramide Cream** because the word "moisturizer" isn't in its text.
   Fix: the concern **filters**, but free-text keywords only **rank**; category words are ignored as keywords.
3. **A dark-spots routine dropped the serum**, the one step that treats dark spots, because
   "swap to the cheapest option first" made bad trade-offs. Fix: with ≤6 candidates per step there are
   ≤1,300 combinations, so we **try them all** and keep the best one within budget.
   Brute force is the right algorithm when the search space is small.

Lesson: when an agent gives a bad answer, the cause is often the **tool**, not the model.
Test tools on their own first.

## 7. One reply, rendered per channel

The agent writes WhatsApp-style text (`*bold*`, plain line breaks) because Phase 5 sends the same
reply to WhatsApp. The web page converts it to Markdown (`whatsapp_to_markdown`). Keep content
separate from presentation.

## 8. Testing an AI system: tests vs evals

| | Unit tests (`pytest`) | Evals (`python -m kotler.evals.shopping`) |
|---|---|---|
| Model | FakeLLM (scripted) | Real Gemini |
| Tests | **Our code**: tools, loop, memory, safety | **The model's behaviour** |
| Cost | Free, instant, runs in CI | API calls, ~2 minutes, run when prompts change |
| Result | Pass/fail, deterministic | A score (e.g. 20/22), varies a little run to run |

LLM output differs every time, so evals don't compare exact text. They check **properties**:

- **tools**: called a tool instead of answering from memory?
- **grounded**: every product named was returned by a tool?
- **budget / skin / in_stock**: do the recommendations satisfy the constraints?
- **language**: Hinglish in, Hinglish out?
- **asks**: asked for the skin type when it was missing?
- **scope**: no products for "where is my order?", medical questions or "give me a 90% discount"?

Every run is saved to `data/evals/`. Change the prompt, rerun, and compare. That's how you improve an
AI product with evidence instead of vibes.

## 9. Real-world lesson: provider quirks (why we have two backends)

We first called Gemini through its **OpenAI-compatible** endpoint, so the same code could talk to any provider.
Every request failed with *"Please pass a valid API key"*, even though the key was fine.
Testing each way of sending the key found the cause:

| How the key was sent | Result |
|---|---|
| Native Gemini API, `x-goog-api-key` header | ✅ |
| OpenAI-compatible endpoint, any header | ❌ |

Since 28 May 2026, new AI Studio keys are **auth keys** (`AQ.…`, tied to a service account), and the
OpenAI-compatible endpoint doesn't accept them. So `GeminiLLM` talks to the native API and **translates**
our OpenAI-style messages (see the table in its docstring). The agent, tools and tests didn't change at all.
That's the payoff of hiding providers behind one interface.

Then the newest model returned **503 "high demand"**, and an older one was **retired for new users**. Hence:

- **Pinned model** (`gemini-3.5-flash`), not a "latest" alias, so evaluation results stay comparable.
- **Retries with exponential backoff** (1.5s, 3s) for 429/5xx; **no retry** for a bad key (it won't fix itself).
- **Fallback model** (`gemini-3.1-flash-lite`) when the main one is still overloaded: customers see a slightly
  simpler answer instead of an error.

Lesson: in production, the hard part is often the provider (keys, quotas, outages, deprecations), not the prompt.

## 10. Results against real Gemini (gemini-3.5-flash)

**21/22 on the first run.** The one failure was a mistake in the *eval*, not the agent: asked
*"shaadi hai next month, glow chahiye"*, the agent asked for the skin type first, which is what the prompt tells it to do.
After fixing the case: 22/22.

| Check | Score |
|---|---|
| grounded (no invented products) | 15/15 |
| budget respected | 5/5 |
| right skin type | 9/9 |
| replied in the customer's language | 22/22 |
| refused off-topic / trick requests (order status, rashes, "90% discount") | 4/4 |

Typical answer time is 3–8 s and about 3,500 tokens. Slower answers (20–40 s) were the provider retrying while overloaded.

Lesson: **evals have bugs too.** When a case fails, read the actual answer before changing the prompt.

## Running it

1. Put your key in `.streamlit/secrets.toml` (create the folder if needed). Both new `AQ.` auth keys and
   older `AIza` keys work:
   ```toml
   GEMINI_API_KEY = "your-key"
   ```
2. `streamlit run app.py`, then open **Shop Assistant**.
3. Evals: `GEMINI_API_KEY=your-key python -m kotler.evals.shopping`
   (on Windows PowerShell: `$env:GEMINI_API_KEY="your-key"; python -m kotler.evals.shopping`).

Settings (environment variables or secrets): `KOTLER_LLM_MODEL` (default `gemini-3.5-flash`),
`KOTLER_LLM_FALLBACK_MODELS` (default `gemini-3.1-flash-lite`). To use another provider, set
`KOTLER_LLM_PROVIDER=openai` plus `KOTLER_LLM_BASE_URL` and `KOTLER_LLM_MODEL`, e.g. Groq's free tier or a
local Ollama. No code changes needed.

## Exercises

1. Add a tool `check_offers()` that returns the current coupon rules from a new table. What must the
   prompt say so the agent never invents coupons?
2. Add 5 eval cases of your own, including one that tries to trick the agent. Does it pass?
3. Remove the "under ₹X, every product must cost ≤ X" rule from the prompt and rerun the evals.
   Which checks fail?
4. Change `MAX_STEPS` to 2. Which questions break, and why?
5. Open the Shop Assistant as a logged-in customer and ask "what did I buy last time?". Look at the tool trace.

## Interview questions you can now answer

- *What is function calling, and who actually executes the function?*
- *How do you stop an LLM from hallucinating products or prices?* Grounding with tools, strict prompt rules, and evals that check grounding.
- *How do you stop prompt injection from accessing other users' data?* Identity from the server, never from the model.
- *How do you test something non-deterministic?* Mock the model for code tests; property-based evals for behaviour.
- *Why not LangChain?* We can explain and debug every step; we'd adopt a framework once we need what it adds.
- *How do you control cost and latency of an agent?* Step limits, trimmed history, compact tool results.
- *What happens when the AI provider is down?* Retries with backoff, a fallback model, friendly errors, pinned versions.
