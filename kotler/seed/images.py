"""Product images: how each product looks (container + colours) and where its picture lives.

The pictures themselves are illustrated packshots drawn with HTML/CSS and rendered once by
`scripts/product_images.mjs` (a headless browser takes a screenshot of each). They are committed to the repo in
kotler/web/media/products/, so nobody needs to render them again. Why illustrations and not photos? Photos of real
brands would be copyright problems and misleading; AI image generation isn't on the free tier.

    python -m kotler.seed.images > /tmp/catalog.json      # what the renderer needs
    NODE_PATH=$(npm root -g) node scripts/product_images.mjs /tmp/catalog.json kotler/web/media/products
"""

from __future__ import annotations

import json
import re

from kotler.seed.catalog import PRODUCTS

MEDIA_URL = "/media/products"


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def image_url(name: str) -> str:
    return f"{MEDIA_URL}/{slug(name)}.jpg"


def container(name: str, category: str) -> str:
    n = name.lower()
    if category == "kit":
        return "box"
    if category == "serum":
        return "dropper"
    if category == "toner":
        return "bottle"
    if category == "lip_care":
        return "balm" if "balm" in n else "minijar"
    if category == "eye_care":
        return "slimtube"
    if category in ("face_wash", "sunscreen"):
        return "tube"
    if "lotion" in n or "wash" in n:
        return "pump"
    return "jar"   # creams, gels, masks, butters, scrubs


# Ingredient keyword -> (main colour, light colour). First match wins, so specific words come first.
PALETTE = [
    ("mineral", ("#a8a29e", "#f2f0ee")), ("tinted", ("#c08a68", "#f6e7dc")), ("oily skin", ("#0f8b8d", "#d9f3f2")),
    ("dry skin", ("#5b7fa6", "#e3ecf6")), ("charcoal", ("#2b2b2e", "#e7e5e4")), ("kumkumadi", ("#c2410c", "#fde3c8")), ("saffron", ("#c2410c", "#fde3c8")),
    ("vitamin c", ("#f28c18", "#ffe8cc")), ("ethyl ascorbic", ("#f28c18", "#ffe8cc")), ("retinol", ("#6d28d9", "#ede4ff")),
    ("arbutin", ("#d9778f", "#fde7ec")), ("beetroot", ("#b5175d", "#fce1ec")), ("berry", ("#9d174d", "#fbe0ea")),
    ("rose", ("#e0607e", "#fde4ea")), ("coffee", ("#7a4a2a", "#f1e3d6")), ("caffeine", ("#7a4a2a", "#f1e3d6")),
    ("cocoa", ("#8a5a3b", "#f3e4d6")), ("shea", ("#b8875a", "#f6ead9")), ("glycolic", ("#ef8f6b", "#fde6dc")),
    ("salicylic", ("#0f8b8d", "#d9f3f2")), ("neem", ("#3f8f3a", "#e0f2dc")), ("tea tree", ("#3f8f3a", "#e0f2dc")),
    ("green tea", ("#4d8b31", "#e4f1d9")), ("centella", ("#2f855a", "#dcf1e5")), ("aloe", ("#57a05a", "#e3f4e1")),
    ("oat", ("#b89a6a", "#f5eddd")), ("rice", ("#9aa5b1", "#eef1f5")), ("hyaluronic", ("#2b8ac6", "#dcefff")),
    ("ceramide", ("#5b7fa6", "#e3ecf6")), ("niacinamide", ("#5662c7", "#e6e8ff")), ("peptide", ("#3b3f8f", "#e3e4f6")),
    ("zinc oxide", ("#a8a29e", "#f2f0ee")), ("iron oxides", ("#c08a68", "#f6e7dc")), ("uv filters", ("#f2a516", "#fff1cf")),
]
CATEGORY_FALLBACK = {"sunscreen": ("#f2a516", "#fff1cf"), "kit": ("#f2780c", "#fff1e3")}


def colours(name: str, ingredients: str, category: str) -> tuple[str, str]:
    # The name says what the product is "about". Sunscreens and kits are recognised by their category colour
    # unless the name says otherwise (mineral, tinted, vitamin C), not by a minor ingredient.
    sources = (name.lower(),) if category in CATEGORY_FALLBACK else (name.lower(), ingredients.lower())
    for text in sources:
        for word, pair in PALETTE:
            if word in text:
                return pair
    return CATEGORY_FALLBACK.get(category, ("#f2780c", "#fff1e3"))


def catalog_for_renderer() -> list[dict]:
    out = []
    for name, category, _skin, _concerns, ingredients, _price, _mrp, size, _desc in PRODUCTS:
        main, light = colours(name, ingredients, category)
        out.append({"name": name, "slug": slug(name), "category": category, "size": size,
                    "container": container(name, category), "main": main, "light": light})
    return out


if __name__ == "__main__":
    print(json.dumps(catalog_for_renderer(), indent=1))
