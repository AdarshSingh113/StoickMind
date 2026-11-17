"""Handoff rules: situations where a PERSON must take over, enforced in code.

The agent's instructions already say "escalate when the customer is angry / mentions a lawyer / has a skin
reaction". But instructions are requests, and a model can miss one. A handoff rule is a guarantee: after the
agent answers, code checks the customer's message; if a rule matches and the agent didn't escalate, the
runtime escalates anyway (or, for agents without the escalation tool, flags the chat for a person in the
inbox) and tells the customer a person will reply. Rules are switched on per agent in Agent Studio.

The rules only ever ADD a person to the conversation. They never block or rewrite what the agent said, so a
false alarm costs a few minutes of a team member's time, and a miss is still caught by the agent's own
instructions. That asymmetry is why it's fine for them to be simple keyword rules.
"""

from __future__ import annotations

import re

from kotler.agent.intent import classify

LEGAL = re.compile(r"\b(consumer (court|forum)|police|lawyer|legal (action|notice)|fir|sue|fraud\w*|scam\w*|"
                   r"cheat\w*|dhokha)\b", re.I)
PERSON = re.compile(r"\b(human|real person|actual person|(talk|speak) (to|with) (someone|a person|an agent|a manager|"
                    r"your team)|call me|manager|insaan|kisi (insaan )?se baat)\b", re.I)
ANGRY = re.compile(r"\b(worst|pathetic|ridiculous|useless|horrible|disgusting|terrible|bakwas|bekaar|ghatiya|"
                   r"never (again|buying)|fed up|shame on)\b", re.I)

RULES: dict[str, dict] = {
    "skin_reaction": {"label": "Skin reaction or allergy", "examples": "rash, burning, itching, swelling, jalan, khujli",
                      "priority": "high", "check": lambda t: classify(t) == "skin_reaction"},
    "asks_for_person": {"label": "Customer asks for a person", "examples": "\"talk to a human\", \"real person\", manager",
                        "priority": "medium", "check": lambda t: bool(PERSON.search(t))},
    "legal_threat": {"label": "Legal threat or fraud claim", "examples": "consumer court, police, lawyer, FIR, fraud",
                     "priority": "high", "check": lambda t: bool(LEGAL.search(t))},
    "angry": {"label": "Very angry customer", "examples": "\"worst service\", \"pathetic\", bakwas, WRITING IN CAPITALS",
              "priority": "medium", "check": lambda t: bool(ANGRY.search(t)) or _shouting(t)},
}
DEFAULT_RULES = ["skin_reaction", "asks_for_person", "legal_threat"]

NOTICE = {
    "en": "A person from our team will also reply here{when}.",
    "hinglish": "Hamari team ka ek member bhi yahin reply karega{when}.",
    "hi": "हमारी टीम का एक सदस्य भी यहीं जवाब देगा{when}।",
}


def _shouting(text: str) -> bool:
    letters = [c for c in text if c.isalpha() and c.isascii()]
    return len(letters) >= 15 and sum(c.isupper() for c in letters) / len(letters) > 0.7


def triggered(rules: list[str], text: str) -> list[str]:
    """Which of these rules match the customer's message."""
    return [r for r in rules if r in RULES and RULES[r]["check"](text or "")]


def priority(fired: list[str]) -> str:
    return "high" if any(RULES[r]["priority"] == "high" for r in fired) else "medium"


def notice(lang: str | None, when: str = "") -> str:
    return NOTICE.get(lang or "en", NOTICE["en"]).format(when=f" {when}" if when else "")


def catalog() -> list[dict]:
    return [{"key": k, "label": v["label"], "examples": v["examples"]} for k, v in RULES.items()]
