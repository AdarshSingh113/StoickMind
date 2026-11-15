"""Retrieval over the store policies: the "R" in RAG (retrieval-augmented generation).

The support agent must never answer "what's your return window?" from memory, because
models confidently invent policies. Instead it searches our policy documents and quotes them.

Why BM25 and not embeddings + a vector database (ChromaDB) yet?
- 9 short documents: keyword search is fast, free, transparent and needs no model download.
- BM25 is the classic ranking function behind search engines; it's worth understanding
  before moving to embeddings. Phase 8 compares the two on the same questions.

BM25 in one paragraph: a document scores higher when it contains the query's words
(term frequency, with diminishing returns: parameter k1), when those words are rare across
documents (inverse document frequency: "refund" beats "the"), and it's normalised so long
documents don't win just by being long (parameter b).
"""

from __future__ import annotations

import math
import re
from collections import Counter

from kotler.policy import POLICIES

# Customers say "paisa wapas", the policy says "refund". Map common English/Hinglish words.
QUERY_SYNONYMS = {
    "money": "refund", "paisa": "refund", "paise": "refund", "wapas": "refund", "refunded": "refund",
    "toota": "damaged", "tuta": "damaged", "broken": "damaged", "leaking": "damaged", "leak": "damaged",
    "kharab": "damaged", "wrong": "damaged", "galat": "damaged",
    "cancel": "cancelled", "cancellation": "cancelled", "band": "cancelled",
    "return": "returns", "returned": "returns", "exchange": "replacement", "replace": "replacement",
    "delivery": "delivery", "deliver": "delivery", "delivered": "delivery", "arrive": "delivery", "pahunchega": "delivery", "aayega": "delivery", "kab": "delivery", "late": "delivery",
    "shipping": "ship", "shipped": "ship", "courier": "ship", "tracking": "ship", "track": "ship",
    "rash": "rashes", "rashes": "rashes", "burning": "burning", "jalan": "burning", "allergy": "allergic",
    "allergic": "allergic", "itching": "irritation",
    "coupon": "discount", "code": "discount", "offer": "discount", "off": "discount", "discounts": "discount",
    "cod": "cod", "cash": "cod",
}
STOP = {"the", "a", "an", "is", "are", "to", "of", "and", "or", "in", "on", "for", "my", "i", "me", "you", "your",
        "we", "our", "it", "can", "do", "be", "with", "what", "how", "if", "hai", "ka", "ki", "ke", "ko", "mera",
        "meri", "mujhe", "kya", "please",
        # Domain stopwords: in a corpus of order policies these words appear everywhere or say nothing,
        # so a single stray "policy" or "when" must not decide the ranking.
        "policy", "policies", "when", "will", "order", "orders", "product", "products", "item", "items", "get", "got"}


# Multi-word phrases that mean one thing. "cash on delivery" must not count as the word "delivery".
PHRASES = {"cash on delivery": "cod", "money back": "refund", "patch test": "patchtest", "kab aayega": "delivery"}


def _tokens(text: str) -> list[str]:
    out = []
    text = text.lower()
    for phrase, token in PHRASES.items():
        text = text.replace(phrase, f" {token} ")
    for w in re.findall(r"[a-z0-9₹]+", text):
        if w in STOP:
            continue
        w = QUERY_SYNONYMS.get(w, w)
        out.append(w[:-1] if len(w) > 4 and w.endswith("s") else w)  # crude singular: "refunds" -> "refund"
    return out


class BM25:
    def __init__(self, docs: dict[str, str], k1: float = 1.5, b: float = 0.75):
        self.ids = list(docs)
        self.texts = docs
        # The title (first line) is strong evidence of what a document is about, so it counts 3x.
        self.toks = {i: _tokens(t.split("\n", 1)[0]) * 3 + _tokens(t) for i, t in docs.items()}
        self.k1, self.b = k1, b
        self.avg_len = sum(len(t) for t in self.toks.values()) / max(len(docs), 1)
        df = Counter(w for t in self.toks.values() for w in set(t))
        n = len(docs)
        self.idf = {w: math.log(1 + (n - c + 0.5) / (c + 0.5)) for w, c in df.items()}

    def score(self, query: str, doc_id: str) -> float:
        tf = Counter(self.toks[doc_id])
        length = len(self.toks[doc_id])
        s = 0.0
        for w in set(_tokens(query)):
            if w not in tf:
                continue
            f = tf[w]
            s += self.idf[w] * f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * length / self.avg_len))
        return s

    def search(self, query: str, top_k: int = 2) -> list[tuple[str, float]]:
        ranked = sorted(((i, self.score(query, i)) for i in self.ids), key=lambda x: -x[1])
        return [(i, round(s, 2)) for i, s in ranked[:top_k] if s > 0]


INDEX = BM25(POLICIES)


def search_policies(query: str, top_k: int = 2) -> list[dict]:
    return [{"policy": i, "score": s, "text": POLICIES[i]} for i, s in INDEX.search(query, top_k)]
