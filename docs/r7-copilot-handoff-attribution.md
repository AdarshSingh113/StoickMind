# Round 7: product images, team copilot, topics, handoff rules, sales from AI chats

This round turned a working product into one you can show: real product photos everywhere, an AI copilot for the
people in the inbox, analytics on what customers ask about, handoff rules that guarantee a person joins when it
matters, and sales that can be traced back to the AI conversation that made them.

Each section: **what** it does, **why** it's built this way, **how** it works, and what to learn from it.

---

## 1. Product images and product cards in every channel

**What.** All 36 products have a packshot. When an agent recommends products, the reply carries *product cards*
(photo, price, rating, Buy button) in the website chat, the inbox, Agent Studio's playground, Telegram (as photos)
and WhatsApp (as image messages).

**Why this way.**
- *Images:* the free Gemini tier allows 0 image generations, so the packshots are drawn in HTML/CSS (tube, dropper,
  jar, pump...) with colours matched to the product name, then rendered to JPEG by Playwright
  (`scripts/product_images.mjs`). They are labelled "illustrations" in the store.
- *Cards are decided in code, not by the model:* a card is shown only for a product that a tool returned **this
  turn** and that the reply actually names. The price on the card comes from the database. The model can't invent a
  product or a price into a card.

**How.** `kotler/agent/cards.py` (`product_cards`), `AgentTurn.products`, `channel_events.meta` stores cards so the
inbox can show them later. Telegram uploads the files (`sendPhoto` / `sendMediaGroup`); WhatsApp needs a public URL
(`PUBLIC_BASE_URL`) because Meta downloads the image itself.

---

## 2. "Converted with AI": from chat to checkout, every sale counted

**What.** The Buy button opens a demo checkout. An order placed from a card is recorded as `source = 'ai_chat'` with
the conversation it came from. Overview, Customers ("Bought via AI chat" filter), Customer 360 and Business impact
show these sales.

**Why this way.**
- *Signed links:* the Buy URL carries `ref` (which chat) and `sig` (an HMAC of the ref with the server's secret).
  A forged or edited link still works as a normal order, it just isn't attributed. So nobody can inflate "AI sales"
  by editing a URL.
- *No data leaks through checkout:* placing an order never links the chat to a customer account, and the
  confirmation page never shows anything about an existing customer with that phone number.
- *Revenue isn't profit:* Business impact shows AI sales as its own evidence type ("revenue") and never adds it to
  the "measured savings" total.
- *Privacy in Ask your data:* `orders.source` can be queried; `orders.ai_ref` is blocked column by column, because for
  WhatsApp it contains a phone number.

**How.** `kotler/store.py` (`sign`, `valid_ref`, `place_order`, `ai_sales`), `/store/checkout` in `kotler/server.py`
(10 orders per hour per IP).

---

## 3. AI copilot for the team in the inbox

**What.** When a person takes over a chat: **Suggest reply**, **Friendlier**, **Shorter**, **Hinglish**, **English**,
and **Summarize** (3 bullets: issue, what was done, next step). Plus **private notes** and, on WhatsApp, the time
left in the 24-hour reply window.

**Why this way.**
- *Copilot, not autopilot:* nothing is ever sent automatically; the draft lands in the composer.
- *Grounding:* a suggestion may only use the conversation, the customer's real orders (none at all for a guest)
  and the store policies (the same BM25 policy search Asha uses).
- *Fact check in code:* any order number or rupee amount in the draft that isn't in that context is flagged:
  "Check before sending: KTL-999999, ₹99,999 aren't in this chat or the customer's orders."
- *Notes in their own table:* a private note can never be sent to a customer by mistake, because it isn't a message.

**How.** `kotler/agent/assist.py`, `POST /api/v1/inbox/{channel}/{id}/assist` and `/notes`. Every call is traced
(`inbox_assist`), so it shows up in AI performance like everything else.

---

## 4. Topics and automation rate

**What.** Every conversation is tagged with what the customer is asking about (skin reaction, damaged item,
refund, cancel, order status, payment, offers, product advice, asked for a person). AI performance gets a
**Conversations** tab: conversations, share **handled fully by AI**, messages per conversation, sales from AI chats,
and a per-topic table. The inbox list shows each chat's topic.

**Why this way.**
- *Rules, not an LLM:* free, instant, the same answer every time, and anyone can read why a message got its label.
  Negations are handled ("sunscreen that **won't** irritate" is a product question, not a reaction). If the rules miss
  something it lands in "Other", visible, not hidden.
- *A conversation gets its most serious topic:* "the cream gave me a rash... I want a refund" is a skin-reaction case
  first, because that decides how it must be handled.
- *An honest definition of "automated":* the AI replied, no person replied, nothing is waiting for a person, **and it
  was never escalated**. A high automation rate on "Skin reaction" would be a red flag, so the page says so.

**How.** `kotler/agent/intent.py`, `kotler/obs/conversations.py`, `channel_users.escalated_at` (set when a person
was first needed, never cleared).

---

## 5. Handoff rules in Agent Studio

**What.** Per agent, switch on: *skin reaction or allergy*, *customer asks for a person*, *legal threat or fraud
claim*, *very angry customer*. Plus a panel **"What this agent can see and change"**, worked out from its tools,
with the real limits.

**Why this way.**
- *A prompt is a request; a rule is a guarantee.* After the agent answers, code checks the customer's message. If a
  rule matches and the agent didn't escalate by itself, the runtime escalates anyway (agents without the escalation
  tool get the chat flagged "Needs you") and appends "A person from our team will also reply here", in the
  customer's language.
- *Rules only ever add a person.* They never block or rewrite the answer, so a false alarm costs a few minutes of a
  team member's time. That asymmetry is why simple keyword rules are fine here.
- *The data-access panel can't drift:* it's derived from the ticked tools, and the limits shown (₹1,000 auto-refund,
  10% coupon cap, 3 verification attempts) come from `kotler/policy.py`, the same constants the tools enforce.

**How.** `kotler/agent/handoff.py`, `Agent._apply_handoff_rules` in `kotler/agent/runtime.py`, stored per version on
the agent (older rows and snapshots fall back to defaults). Re-checked on real Gemini: the affected shopping and
helpdesk eval cases all pass.

---

## 6. Bugs that only real use found

Preparing the launch screenshots with real traffic (real Gemini chats, real checkouts) found five bugs that the
unit tests didn't, each now covered by a regression test:

| Bug | Cause | Lesson |
|---|---|---|
| Overview crashed after a demo checkout | checkout stored `expected_delivery` as a bare date; the RTO model parses full timestamps | one format per column, everywhere |
| Agent Studio list crashed on an older database | a new all-NULL column arrives from pandas as `NaN`, which is truthy | `isinstance(x, str)`, not `if x` |
| Cross-sell journey crashed for the whole store | checkout customers have no skin type; `NaN in "oily,dry"` raises | the same NaN trap, in a different file |
| A campaign where everyone was excluded could be "sent" | nothing checked for an empty audience; the results page then crashed | refuse clearly instead of doing nothing silently |
| Failed actions were sometimes silent | some buttons had no error handler | one global error toast, opt-out for screens that show errors inline |

Also fixed: the inbox header collapsed the customer's name to "S.." at 1280px, and an escalated chat counted as
"handled by AI" again once it was handed back.

**The lesson:** tests check what you thought of. Running the product end to end, with real data and a real model,
finds what you didn't.
