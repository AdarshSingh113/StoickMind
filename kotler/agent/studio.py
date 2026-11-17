"""Agent Studio: agents as configuration.

Look at any AI-commerce platform and every "module" (acquisition quiz, retention
nudges, order management, helpdesk) is the same machine with different settings:

    instructions + goal + success criteria + allowed tools + settings

So instead of writing a new Python class per agent, we store those settings in the
database. One generic runtime (kotler/agent/runtime.py) runs any of them. A
marketer can create or improve an agent without a code change or deploy.

Every save creates a new VERSION with a full snapshot. Prompts are code too:
you want history, comparison and one-click rollback when a change makes things worse.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime

from kotler import db
from kotler.agent.handoff import DEFAULT_RULES, RULES
from kotler.agent.tools import TOOLS


@dataclass
class AgentConfig:
    slug: str
    name: str
    role: str
    instructions: str
    goal: str
    success_criteria: str
    tools: list[str] = field(default_factory=list)
    handoff_rules: list[str] = field(default_factory=lambda: list(DEFAULT_RULES))   # see kotler/agent/handoff.py
    description: str = ""
    temperature: float = 0.3
    max_steps: int = 5
    status: str = "draft"
    version: int = 0
    is_builtin: bool = False
    updated_at: str = ""


# What each tool lets an agent see or change. Agent Studio derives an agent's data access from its tools, so the
# panel can never drift from what the agent can really do. Limits are enforced inside the tools (kotler/policy.py).
def data_access() -> dict[str, dict]:
    from kotler import policy
    rows = {
        "search_products": ("Product catalogue, prices and stock", "reads"),
        "get_product_details": ("Product catalogue, prices and stock", "reads"),
        "compare_products": ("Product catalogue, prices and stock", "reads"),
        "build_routine": ("Product catalogue, prices and stock", "reads"),
        "get_my_profile": ("The signed-in customer's profile (skin type, past purchases)", "reads"),
        "save_skin_profile": ("The signed-in customer's skin profile", "changes"),
        "search_policies": ("Store policies (returns, refunds, shipping)", "reads"),
        "verify_order": ("Guest check: order number + last 4 phone digits, "
                         f"locked after {policy.MAX_VERIFY_ATTEMPTS} failed tries", "reads"),
        "list_my_orders": ("The verified customer's own orders only", "reads"),
        "get_order_status": ("The verified customer's own orders only", "reads"),
        "cancel_order": ("Cancel the customer's order, only before it ships", "changes"),
        "offer_discount": (f"One coupon for the next order, at most {policy.MAX_DISCOUNT_PCT}%", "changes"),
        "report_damaged_item": (f"Replacements; orders above ₹{policy.REPLACEMENT_AUTO_LIMIT:,.0f} need a person's "
                                "approval", "changes"),
        "request_refund": (f"Refunds up to ₹{policy.AUTO_REFUND_LIMIT:,.0f}; above that, or COD, a person approves",
                           "changes"),
        "escalate_to_human": ("Helpdesk tickets: hands the chat to the care team", "changes"),
    }
    return {tool: {"data": data, "access": access} for tool, (data, access) in rows.items()}


class AgentValidationError(ValueError):
    pass


EDITABLE = ["name", "role", "description", "instructions", "goal", "success_criteria", "tools", "handoff_rules",
            "temperature", "max_steps"]
JSON_FIELDS = ("tools", "handoff_rules")


def validate(cfg: AgentConfig) -> None:
    errors = []
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,39}", cfg.slug or ""):
        errors.append("ID must be 2-40 lowercase letters, numbers or dashes.")
    for name in ("name", "role", "instructions", "goal", "success_criteria"):
        if not str(getattr(cfg, name) or "").strip():
            errors.append(f"{name.replace('_', ' ').capitalize()} can't be empty.")
    if len(cfg.instructions or "") > 6000:
        errors.append("Instructions are too long (max 6,000 characters).")
    unknown = [t for t in cfg.tools if t not in TOOLS]
    if unknown:
        errors.append(f"Unknown tools: {', '.join(unknown)}.")
    bad_rules = [r for r in cfg.handoff_rules if r not in RULES]
    if bad_rules:
        errors.append(f"Unknown handoff rules: {', '.join(bad_rules)}.")
    if not 0 <= cfg.temperature <= 1:
        errors.append("Temperature must be between 0 and 1.")
    if not 1 <= cfg.max_steps <= 8:
        errors.append("Max steps must be between 1 and 8.")
    if cfg.status not in ("draft", "live"):
        errors.append("Status must be draft or live.")
    if errors:
        raise AgentValidationError(" ".join(errors))


# ------------------------------------------------------------------- storage
def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _from_row(row: dict) -> AgentConfig:
    row = dict(row)
    row["tools"] = json.loads(row["tools"])
    # NULL = saved before handoff rules existed: use the defaults (built-ins get their own). Via pandas an
    # all-NULL column arrives as float NaN, not None, hence the isinstance check.
    rules = row.get("handoff_rules")
    rules = rules if isinstance(rules, str) else None
    builtin = next((b for b in BUILTINS if b.slug == row["slug"]), None)
    row["handoff_rules"] = json.loads(rules) if rules else list(builtin.handoff_rules if builtin else DEFAULT_RULES)
    row["is_builtin"] = bool(row["is_builtin"])
    return AgentConfig(**row)


def list_agents() -> list[AgentConfig]:
    ensure_builtin_agents()
    rows = db.query_df("SELECT * FROM agents ORDER BY is_builtin DESC, name").to_dict("records")
    return [_from_row(r) for r in rows]


def get_agent(slug: str) -> AgentConfig | None:
    ensure_builtin_agents()
    row = db.query_one("SELECT * FROM agents WHERE slug = ?", (slug,))
    return _from_row(row) if row else None


def save_agent(cfg: AgentConfig, note: str = "") -> AgentConfig:
    """Create or update an agent. Always writes a new version snapshot."""
    validate(cfg)
    current = db.query_one("SELECT version FROM agents WHERE slug = ?", (cfg.slug,))
    cfg = replace(cfg, version=(current["version"] + 1) if current else 1, updated_at=_now(),
                  tools=list(dict.fromkeys(cfg.tools)), handoff_rules=list(dict.fromkeys(cfg.handoff_rules)))
    data = asdict(cfg)
    cols = list(data)
    vals = [json.dumps(v) if k in JSON_FIELDS else (int(v) if k == "is_builtin" else v) for k, v in data.items()]
    # A real UPSERT. Not "INSERT OR REPLACE": that DELETES the old row first, which fires
    # ON DELETE CASCADE and silently wipes the agent's whole version history.
    updates = ", ".join(f"{c} = excluded.{c}" for c in cols if c != "slug")
    with db.get_conn() as conn:
        conn.execute(f"INSERT INTO agents ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))}) "
                     f"ON CONFLICT(slug) DO UPDATE SET {updates}", vals)
        conn.execute("INSERT INTO agent_versions (slug, version, snapshot, note, created_at) VALUES (?,?,?,?,?)",
                     (cfg.slug, cfg.version, json.dumps(data), note or None, cfg.updated_at))
    return cfg


def set_status(slug: str, status: str) -> AgentConfig:
    cfg = get_agent(slug)
    if not cfg:
        raise AgentValidationError(f"No agent '{slug}'.")
    return save_agent(replace(cfg, status=status), note=f"Status → {status}")


def versions(slug: str) -> list[dict]:
    rows = db.query_df("SELECT version, note, created_at, snapshot FROM agent_versions WHERE slug = ? "
                       "ORDER BY version DESC", (slug,)).to_dict("records")
    for r in rows:
        r["snapshot"] = json.loads(r["snapshot"])
    return rows


def restore(slug: str, version: int) -> AgentConfig:
    """Roll back by saving an old snapshot as a NEW version (history is never rewritten)."""
    row = db.query_one("SELECT snapshot FROM agent_versions WHERE slug = ? AND version = ?", (slug, version))
    if not row:
        raise AgentValidationError(f"Version {version} of '{slug}' not found.")
    snap = json.loads(row["snapshot"])
    current = get_agent(slug)
    restored = replace(current, **{k: snap[k] for k in EDITABLE if k in snap})
    return save_agent(restored, note=f"Restored version {version}")


def duplicate(slug: str, new_slug: str, new_name: str) -> AgentConfig:
    src = get_agent(slug)
    if not src:
        raise AgentValidationError(f"No agent '{slug}'.")
    if get_agent(new_slug):
        raise AgentValidationError(f"An agent with ID '{new_slug}' already exists.")
    return save_agent(replace(src, slug=new_slug, name=new_name, status="draft", is_builtin=False),
                      note=f"Copied from {slug} v{src.version}")


def delete_agent(slug: str) -> None:
    cfg = get_agent(slug)
    if cfg and cfg.is_builtin:
        raise AgentValidationError("Built-in agents can't be deleted (you can edit or restore them).")
    with db.get_conn() as conn:
        conn.execute("DELETE FROM agent_versions WHERE slug = ?", (slug,))
        conn.execute("DELETE FROM agents WHERE slug = ?", (slug,))


def diff(old: dict, new: dict) -> list[str]:
    """Names of fields that changed between two snapshots."""
    return [k for k in EDITABLE if k in old and k in new and old[k] != new[k]]


# ------------------------------------------------------------ built-in agents
KAVYA = AgentConfig(
    slug="kavya", name="Kavya", role="shopping assistant", status="live", is_builtin=True,
    description="Website & WhatsApp shopping assistant. Recommends products from the catalogue.",
    goal="Help shoppers find the right products for their skin and budget, and guide them towards a purchase.",
    success_criteria="The customer receives suitable, in-stock recommendations that respect their budget and skin type, "
                     "and shows buying intent (asks how to order, picks a product, or asks a follow-up about it).",
    tools=["search_products", "get_product_details", "compare_products", "build_routine", "get_my_profile"],
    handoff_rules=["skin_reaction", "asks_for_person", "legal_threat"],
    instructions="""- For ANY product recommendation, availability or price question, call a tool first. Never answer from memory.
- search_products for "suggest / which / do you have" questions. build_routine for full routines.
  get_product_details before answering detailed questions about one product (usage, warnings).
  compare_products for "X vs Y". get_my_profile to personalise for a logged-in customer.
- Convert the customer's words into tool filters: "pimples/daane" -> concern "acne", "daag" -> "dark spots",
  "500 ke andar / under 500 / below ₹500" -> max_price 500.
- If the skin type matters and you don't know it (not in the message, not in the profile), ask ONE short
  question first, in the customer's language, e.g. "Is your skin oily, dry or combination?".
  Don't ask if you can already help. Either ask OR recommend in one message, not both.
- Recommend at most 3 products, one short line each on WHY it suits them.
- If build_routine skipped steps to fit the budget, present that routine first and mention the complete one as an upgrade.
- End with one helpful follow-up question when natural.""",
)

SKIN_QUIZ = AgentConfig(
    slug="skin-quiz", name="Ira", role="skin quiz guide", status="live", is_builtin=True,
    description="Acquisition agent: a 5-question skin quiz for new visitors that ends in a personalised routine.",
    goal="Understand a new visitor's skin in at most 5 short questions and recommend a personalised routine they want to buy.",
    success_criteria="The customer answers the quiz, receives a short personalised analysis and a complete routine within "
                     "their budget, and shows interest in buying it.",
    tools=["build_routine", "search_products", "get_product_details", "get_my_profile", "save_skin_profile"],
    instructions="""Run a short skin quiz. Ask ONE question per message, with the options in brackets:
1. Skin type: "How does your skin feel by afternoon?" (oily all over / oily T-zone only / tight or flaky / red or easily irritated / comfortable)
   Map: oily all over -> oily, T-zone -> combination, tight/flaky -> dry, red/irritated -> sensitive, comfortable -> normal.
2. Main concern (acne / dark spots / dullness / dryness / tan / fine lines / none)
3. Do products sometimes sting or cause redness? (yes / no)  If yes, prefer sensitive-friendly products.
4. Budget for the whole routine (under ₹800 / ₹800-1500 / above ₹1500)
5. Morning or night routine? (morning / night)

Rules:
- Skip any question already answered in the conversation or in the customer's profile.
- Start with a one-line friendly intro, then question 1. Never ask more than one question at a time.
- After the last answer: write a 2-line personalised analysis ("Your skin is combination with acne-prone T-zone...").
  Then call build_routine with skin_type, concern, budget (use the upper limit, e.g. 1500) and time_of_day.
  Present each step: product name, price, one line on why. Then the total. Mention the cheaper kit if one is returned.
  If the routine skipped steps to fit the budget, say which ones and offer the complete routine as an optional upgrade.
- If the customer is logged in and confirmed their skin type, call save_skin_profile so future chats remember it.
- If the customer wants to skip the quiz, ask only for skin type and budget, then recommend.
- Finish by asking if they'd like to order the routine.""",
)

ASHA = AgentConfig(
    slug="asha", name="Asha", role="customer care agent", status="live", is_builtin=True, temperature=0.2,
    max_steps=6,
    description="AI Helpdesk + Order Management: tracking, cancellations (with a save attempt), damaged items, "
                "refunds within limits, and handoff to humans.",
    goal="Resolve the customer's order or support issue in this conversation, safely and within policy, "
         "and hand over to a human when that is the right thing to do.",
    success_criteria="The issue is resolved with the correct action (status explained, order cancelled or kept, "
                     "replacement or refund raised) within policy, OR correctly handed to a human when required, "
                     "and the customer is told clearly what happens next and by when.",
    tools=["search_policies", "verify_order", "list_my_orders", "get_order_status", "cancel_order", "offer_discount",
           "report_damaged_item", "request_refund", "escalate_to_human", "get_my_profile"],
    handoff_rules=["skin_reaction", "asks_for_person", "legal_threat", "angry"],
    instructions="""Start by understanding the issue. Be warm and brief; apologise once when something went wrong.

Identity
- Logged-in customers: use list_my_orders / get_order_status directly.
- Guests: ask for the order number AND the last 4 digits of the phone number, then call verify_order.
  If verification fails, don't share any order details. After 3 failures, offer to escalate.

Order status ("where is my order?")
- Call get_order_status. Explain the status in one line, with courier, tracking number and expected date.
- If it's more than 2 days late: apologise and offer to escalate to the courier team.

Cancellation (save the order, but only once)
- If can_cancel is false: explain it has shipped and the return option after delivery (search_policies).
- If it can be cancelled: first ask the reason, unless they gave it. Then make ONE save attempt that fits:
  late delivery worry -> share the expected date; changed mind / price -> offer a 10% coupon on the NEXT order if
  they keep this one (offer_discount ONLY if they agree to keep it); wrong product -> explain we replace wrong items.
- If they still want to cancel, cancel immediately with cancel_order and explain the refund. Never push twice.

Damaged, leaking or wrong item
- Ask which product and what happened (if not said), then report_damaged_item. Share the reference and what happens next.

Refunds
- Check the policy with search_policies, then request_refund (a single product if only one was a problem).
  Explain the outcome exactly as the tool says: approved now, or with the team for review within 24 hours.

Skin reaction (burning, rashes, swelling)
- Safety first: stop using the product, rinse with cool water, see a doctor if severe. Then escalate_to_human
  with priority high, and tell them a refund for that product can be arranged by the care team.

Hand over to a human (escalate_to_human) when
- the customer asks for a human, is very angry, or mentions consumer court, police, a lawyer or fraud;
- the request is outside what your tools allow (e.g. a discount above 10%, a refund outside the window);
- you've tried twice and still can't resolve it.
Tell them the reference number and when a human will reply.

Never invent order details, timelines or policies. Every fact comes from a tool result.""",
)

BUILTINS = [KAVYA, SKIN_QUIZ, ASHA]

TEMPLATES = {
    "Blank agent": AgentConfig(
        slug="", name="", role="assistant", tools=["search_products", "get_product_details"],
        instructions="- Describe step by step what the agent should do.\n- Say which tool to use when.\n"
                     "- Say what to do when information is missing.",
        goal="One sentence: what this agent is for.",
        success_criteria="What must happen in the conversation for it to count as a success?"),
    "Shopping assistant": replace(KAVYA, slug="", name="", status="draft", is_builtin=False),
    "Skin quiz": replace(SKIN_QUIZ, slug="", name="", status="draft", is_builtin=False),
    "Customer care": replace(ASHA, slug="", name="", status="draft", is_builtin=False),
}

def ensure_builtin_agents() -> None:
    """Create the built-in agents if missing. Never overwrites edits made in the Studio."""
    import sqlite3

    try:
        present = set(db.query_df("SELECT slug FROM agents WHERE is_builtin = 1").slug)
    except (sqlite3.OperationalError, Exception):  # table doesn't exist yet (older database)
        db.ensure_schema()
        present = set()
    for cfg in BUILTINS:
        if cfg.slug not in present and not db.query_one("SELECT 1 AS x FROM agents WHERE slug = ?", (cfg.slug,)):
            save_agent(cfg, note="Built-in agent")
