# Phase 3: Agent Studio

## What we built

| File | Role |
|---|---|
| `kotler/agent/studio.py` | Agents as **configuration**: create, validate, version, restore, copy. Built-in agents Kavya and Ira |
| `kotler/agent/prompts.py` | Builds each agent's system prompt from its config **plus global rules** |
| `kotler/agent/runtime.py` | One generic runtime that runs **any** configured agent, with tool permissions enforced in code |
| `kotler/agent/judge.py` | **LLM-as-judge**: scores a conversation against the agent's own success criteria |
| `kotler/agent/tools.py` | New write tool `save_skin_profile`; smarter `build_routine` for tight budgets |
| `views/agent_studio.py` | The Studio: Design, Playground (with Evaluate), Versions, Performance |
| `views/shop_assistant.py` | Customers chat with any **live** agent; the Studio config is used immediately |
| `tests/test_phase3_studio.py` | 26 tests: config store, versions, permissions, write-tool safety, judge |

## 1. The big idea: agents are configuration, not code

Look at an AI-commerce platform's modules (acquisition quiz, retention nudges, order management,
helpdesk). Underneath, each one is the same machine with different settings:

```
instructions + goal + success criteria + allowed tools + settings (temperature, max steps)
```

So we store those settings in the database and write **one** runtime that runs any of them.
Consequences:

- A new agent (e.g. a win-back agent) is a form, not a code change or deploy.
- Non-engineers (marketing, support leads) can improve agents.
- Every module from the roadmap (Helpdesk, Order Management, Retention) is now "a new agent plus new tools".

## 2. Versioning: prompts are code too

Every save writes a **new version** with a full snapshot, a note ("what did you change?") and the list
of changed fields. **Restore** saves an old snapshot as a *new* version, so history is never rewritten
(the same idea as `git revert`). Conversations and judge scores record the agent version, so you can
ask "did v3 actually beat v2?"

**Bug we hit:** SQLite's `INSERT OR REPLACE` doesn't update a row. It **deletes** it and inserts a new one.
The delete fired `ON DELETE CASCADE` and silently wiped every agent's version history. A test caught it.
The fix is a true upsert: `INSERT … ON CONFLICT(slug) DO UPDATE`. Know your database's semantics.

## 3. Global rules: what can't be edited

The editable instructions go in the middle of the prompt. **Global rules** come after them and live in code:
never invent products or prices, respect the budget, never promise refunds or discounts, no medical advice,
never reveal internals, reply in the customer's language. Someone typing "give everyone 50% off" into the
Studio can't switch these off. Test: `test_prompt_contains_config_and_global_rules`.

## 4. Tool permissions are enforced in code, not in the prompt

Each agent lists its allowed tools. The runtime:
1. sends the model **only** the schemas of allowed tools, and
2. **refuses** any other tool call, because models can hallucinate tool names they've seen elsewhere.

Rule of thumb: the prompt *guides* behaviour; **code enforces** permissions.

## 5. The first WRITE tool: `save_skin_profile`

Tools that change data deserve stricter rules than read tools:
- identity from the session (`ToolContext`), **never** from the model (no `customer_id` argument),
- one field only, validated against a fixed list,
- guests can't write anything,
- marked ✎ in the Studio so reviewers notice.

## 6. LLM-as-judge: making "success criteria" measurable

"Customer received a routine within budget and showed buying intent" can't be checked with code.
So a second LLM call reads the transcript, **including tool calls and results**, and returns
`{"achieved": true, "score": 4, "reason": "..."}`.

Design choices:
- The judge sees tool results, so it can check grounding (were the prices real?).
- Strict rubric, temperature 0, small JSON output, parsed defensively (code fences, extra words, scores clamped to 1–5).
- Every verdict is stored with the agent version, which gives the **Performance** tab's success rate per version.
- Judges are models too. They can be lenient or confused, so verdicts must be reviewable (Phase 8 measures the judge itself).

## 7. Multi-turn evaluation

A quiz can't be tested with one message, so eval cases can now be conversations. For example,
`quiz_full_hinglish` sends 6 messages: *"mujhe apni skin ke liye routine chahiye" → "dopahar tak pura face oily ho
jata hai" → "pimples" → "nahi" → "800 ke andar" → "subah"*. Then it checks the final routine.

## 8. What the real-model evaluation taught us

First run of the new quiz cases: **2/4**. Reading the actual answers showed two different problems:

| Failure | Real cause | Fix |
|---|---|---|
| Quiz "over budget" (₹1,496 routine + ₹1,199 kit) | **Eval bug**: the kit was offered as an *alternative*, but the check added it to the total | Kits are checked on their own, not summed |
| ₹897 routine for an ₹800 budget | **Tool weakness**: no complete routine fits ₹800, so the tool returned the cheapest one over budget | `build_routine` now drops optional steps by priority (never the cleanser; sunscreen first in the morning) and reports the complete routine as an upgrade: cleanser + sunscreen for **₹748**, "complete routine ₹1,396" |

Full run: **25/26**. The last failure was a **language** mix-up. Shivani asked in English but got Hinglish, because
her profile says she usually writes Hinglish. Making the prompt clearer wasn't enough: the `get_my_profile`
**tool result** contained `"preferred_language": "hinglish"`, which arrives right before the answer and
outweighs the system prompt. Fix: the tool no longer returns the language. The prompt keeps it, labelled
"fallback only".

The next full run surfaced one more: an English answer about hyaluronic acid ended with a stray
**"Aapki skin type kya hai?"**. The source was Kavya's own instructions, whose example question was in Hinglish
(*"Aapki skin oily hai, dry ya combination?"*). Models sometimes copy examples word for word. The example is now
language-neutral ("in the customer's language, e.g. 'Is your skin oily, dry or combination?'"). The affected cases
then passed **9/9 over three repeated runs**. One pass can be luck, so re-test flaky cases several times.

Each fix was saved as a new agent version (Kavya v2 → v3), so the history shows what changed and why.

Lessons:
1. **Evals have bugs.** Read the answer before changing anything.
2. **Better tools beat better prompts**, again.
3. **Tool results are part of the prompt**, and often the most persuasive part.
4. **Examples in prompts leak.** Write them in neutral form, or in every language you support.
5. **Re-run flaky cases several times** before believing a fix.

## Try it

1. Open **Agent Studio**, pick Ira, go to **Playground**, and take the quiz in Hinglish. Press **Evaluate**.
2. In **Design**, change something (e.g. ask for the budget first), write a note and save. Check **Versions**, then restore v1.
3. **New agent → Blank agent**: create a "Sunscreen expert" that may only use `search_products` and
   `get_product_details`. Ask it about moisturizers. Does it stay in its lane?
4. Pause Ira and open the Shop Assistant: only live agents are offered to customers.

## Exercises

1. Add a tool `get_offers()` that returns the active coupons from a new table. Which agents should get it,
   and what global rule must change?
2. Write 3 eval cases for your Sunscreen expert. Run them with `--only`.
3. Make two versions of Kavya that differ in one instruction, chat 5 times with each, judge them, and compare in
   **Performance**. Is 5 conversations enough to conclude anything? (Hint: no. Why?)

## Interview questions you can now answer

- *How would you let non-engineers build AI agents safely?* Config + global rules in code + tool permissions in code + versioning + evals.
- *How do you roll back a bad prompt change?* Versioned snapshots; restore as a new version.
- *How do you measure fuzzy success like "showed purchase intent"?* LLM-as-judge with a rubric, tool-aware transcripts and stored verdicts. And you validate the judge.
- *Why enforce tool permissions outside the prompt?* Models can be manipulated or can hallucinate tool names; code can't be talked out of a rule.
- *What's dangerous about write tools?* Who they act on and what they change. Bind identity to the session, validate values, and minimise scope.
