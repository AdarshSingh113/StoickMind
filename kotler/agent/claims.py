"""Claim verification: did the agent really do what its reply says it did?

Found by the helpdesk evals: Asha told an angry customer "I am escalating this… your reference
number is #8800001875" (that was the TRACKING number) and an allergic customer "escalated, Ref:
#HUM-9921", without ever calling escalate_to_human. Nobody would have followed up.
An agent that claims actions it didn't take is the most dangerous failure an action agent can have.

So after every reply we check, in code:
1. ACTION CLAIMS ("I have escalated / cancelled / refunded / raised / issued…", also Hinglish
   "escalate kar diya") must match a SUCCESSFUL call of the matching tool in this turn.
2. REFERENCE CODES (REF-12, ESC-4, RPL-7, CARE10-AB12CD, #HUM-9921…) must appear in a tool
   result from this turn. Anything else was invented.
"""

from __future__ import annotations

import json
import re

# claim pattern -> tools that can make it true
CLAIMS = {
    "escalation": (r"\b(escalat(ed|ing)|handed (it |this )?(over|to)|passed (it |this )?(on|to)|connected you|"
                   r"forwarded (it |this |your )?\w* ?to)\b|escalate kar (diya|di|raha|rahi)|team ko (bhej|forward)",
                   {"escalate_to_human"}),
    "cancellation": (r"\b(have|has been|i've|i have|successfully|is now|been)\s+(\w+\s+)?cancel+ed\b|cancel kar (diya|di)",
                     {"cancel_order"}),
    "refund": (r"\brefund (has been|is|was) (approved|processed|initiated|raised)|\b(processed|initiated|raised|approved)"
               r" (your |a |the )?refund|refund (request )?(raise|process) kar (diya|di)", {"request_refund"}),
    "replacement": (r"\b(raised|arranged|initiated|processed|approved) (a |the |your )?(free )?(replacement|damage report|report)"
                    r"|replacement (has been|is) (raised|arranged|approved)|report raise kar (diya|di)",
                    {"report_damaged_item", "request_refund"}),
    "coupon": (r"\b(here is|here's|i've (created|issued|generated)|i have (created|issued|generated)) (your |a )?"
               r"(\d+% )?(coupon|discount code|code)\b", {"offer_discount"}),
}
CODE = re.compile(r"(?:#\s?[A-Z0-9][A-Z0-9-]{2,}|\b(?:REF|RPL|ESC|CARE\d{1,2})-[A-Z0-9]+\b)")
SUCCESS_KEYS = ("escalated", "cancelled", "accepted", "issued")


def _succeeded(result: dict) -> bool:
    return "error" not in result and any(result.get(k) is True for k in SUCCESS_KEYS)


def find_unbacked_claims(reply: str, traces: list, allowed_tools: set[str]) -> list[str]:
    """Problems with the reply, e.g. ['claims escalation without escalate_to_human']. Empty list = fine."""
    low = reply.lower()
    done = {t.name for t in traces if _succeeded(t.result)}
    problems = []
    for name, (pattern, tools) in CLAIMS.items():
        if tools & allowed_tools and re.search(pattern, low) and not (tools & done):
            problems.append(f"claims {name} without a successful {'/'.join(sorted(tools))} call")
    evidence = " ".join(json.dumps(t.result, ensure_ascii=False) for t in traces).upper()
    for code in {c.strip("# ").upper() for c in CODE.findall(reply)}:
        if code.startswith("KTL-") or code.startswith("AWB"):
            continue  # order and tracking numbers are checked elsewhere (they come from the customer or tools)
        if code not in evidence:
            problems.append(f"reference '{code}' does not come from any tool result")
    return problems


# ------------------------------------------------------------ price grounding
# Found by the shopping evals: in one Hinglish quiz the agent skipped build_routine entirely and
# invented "Glow & Co. Neem Face Wash (₹250)". Rule, checked in code: every ₹ amount in a reply
# must come from THIS turn's tool results, be a total of up to 4 of them, or be a number the
# customer said (their budget).
PRICE = re.compile(r"₹\s?(\d[\d,]*(?:\.\d+)?)")
NUMBER = re.compile(r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)")


def _num(s: str) -> float:
    return round(float(s.replace(",", "")), 2)


def find_ungrounded_prices(reply: str, traces: list, context_texts: list[str]) -> list[str]:
    from itertools import combinations

    amounts = {_num(m) for m in PRICE.findall(reply)}
    if not amounts:
        return []
    evidence = " ".join(json.dumps(t.result, ensure_ascii=False) for t in traces if "error" not in t.result)
    known = {_num(m) for m in NUMBER.findall(evidence) if _num(m) >= 10}
    known |= {_num(m) for t in context_texts for m in NUMBER.findall(t)}
    allowed = set(known)
    pool = sorted(n for n in known if n >= 49)[:40]
    for k in (2, 3, 4):
        allowed |= {round(sum(c), 2) for c in combinations(pool, k)}
    bad = sorted(a for a in amounts if a not in allowed and round(a) not in {round(x) for x in allowed})
    if not bad:
        return []
    if not traces:
        return [f"mentions prices (₹{', ₹'.join(f'{b:,.0f}' for b in bad)}) without looking anything up this turn"]
    return [f"price ₹{b:,.0f} does not come from any tool result" for b in bad]
