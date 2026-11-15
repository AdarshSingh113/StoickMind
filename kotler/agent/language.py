"""Detect the language of a customer message: English, Hinglish or Hindi (Devanagari).

Why in code? We first asked the model to "reply in the customer's language". It usually did,
but our helpdesk agent kept answering a Hinglish complaint ("…leak ho raha tha, refund chahiye")
in English: its instructions, every tool result and the customer's profile were all English,
and that context outweighed one rule. Detecting the language is easy for code, so we do it
here and give the model an explicit, fresh instruction every turn.

Approach: Devanagari characters -> Hindi. Otherwise count common Hindi words written in Latin
letters. Words that are also English ("me", "do", "to", "so") are deliberately excluded.
"""

from __future__ import annotations

import re

HINGLISH_WORDS = {
    "hai", "hain", "tha", "thi", "the", "ho", "hoga", "hogi", "raha", "rahi", "rahe", "gaya", "gayi", "kar", "karo",
    "karna", "karein", "kariye", "karu", "karun", "kya", "kab", "kaise", "kyun", "kyon", "kitna", "kitne", "kaun",
    "mera", "meri", "mere", "mujhe", "hum", "humein", "aap", "aapka", "aapki", "aapke", "aapko", "tum", "tumhara",
    "ke", "ki", "ka", "ko", "se", "mein", "liye", "bhi", "aur", "toh", "nahi", "nahin", "na", "haan", "ji", "bhai",
    "chahiye", "batao", "bataye", "bataiye", "dijiye", "do", "abhi", "tak", "kuch", "koi", "wala", "wali", "acha",
    "accha", "achha", "theek", "thik", "bahut", "zyada", "kam", "sab", "phir", "dobara", "wapas", "paisa", "paise",
    "jaldi", "aaj", "kal", "skin", "lagta", "lagti", "lagana", "lu", "lun", "loon", "de", "dena", "diya",
}
# Ambiguous with English, so they never count on their own.
ENGLISH_TOO = {"the", "do", "de", "na", "skin", "kal", "ho"}


def detect_language(text: str) -> str | None:
    """'hi' | 'hinglish' | 'en', or None if the message is too short to tell (e.g. 'ok', '1234')."""
    if re.search(r"[ऀ-ॿ]", text or ""):
        return "hi"
    words = re.findall(r"[a-z]+", (text or "").lower())
    if len(words) < 2:
        return None
    hits = sum(1 for w in words if w in HINGLISH_WORDS and w not in ENGLISH_TOO)
    if hits >= 2 or (hits == 1 and len(words) <= 4):
        return "hinglish"
    return "en"


INSTRUCTION = {
    "en": "The customer's latest message is in English. Reply in English.",
    "hinglish": "The customer's latest message is in Hinglish (Hindi in English letters). Reply in Hinglish, "
                "even though your instructions and tool results are in English. Keep product names in English.",
    "hi": "The customer's latest message is in Hindi (Devanagari). Reply in Hindi (Devanagari). "
          "Keep product names in English.",
}
