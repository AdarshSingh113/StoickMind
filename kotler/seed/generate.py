"""Generate a realistic, reproducible dataset for a D2C skincare brand.

Run:  python -m kotler.seed.generate            (1500 customers, 12 months)
      python -m kotler.seed.generate --customers 2000 --months 18

Why simulate instead of downloading a dataset?
Public e-commerce datasets don't have Indian pincodes, COD, RTO, Hinglish
support tickets or skin types. By simulating, we *plant* real-world patterns
(listed below) and later check whether our ML models can rediscover them.
That is exactly how you validate a model: if it can't find a pattern you know
is there, it won't find unknown ones either.

Planted patterns
----------------
1. Customer personas (hidden, not stored): loyal, regular, one_time, churned.
   -> Phase 4 RFM / churn models should separate them.
2. COD RTO risk rises with: tier-3 city, first order, poor address,
   high order value, late-night ordering. Falls with past successful deliveries.
   -> Phase 4 RTO predictor should learn these.
3. Seasonality: Diwali (Oct-Nov) and January sale spikes.
4. Customers mostly buy products matching their skin type, and re-buy
   (replenish) favourites.
5. Language: smaller cities write more Hinglish / Hindi.
"""

from __future__ import annotations

import argparse
import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker

from kotler import config, db
from kotler.seed import catalog

DATE_FMT = "%Y-%m-%d %H:%M:%S"

PERSONAS = {  # persona -> (share, orders per month after first purchase)
    "loyal": (0.12, 1.0),
    "regular": (0.28, 0.35),
    "one_time": (0.45, 0.0),
    "churned": (0.15, 0.6),  # buys actively, then stops
}

SEASONALITY = {1: 1.25, 2: 0.9, 3: 0.95, 4: 1.0, 5: 1.05, 6: 0.95,
               7: 0.9, 8: 1.0, 9: 1.05, 10: 1.35, 11: 1.5, 12: 1.15}


@dataclass
class Customer:
    id: int
    name: str
    phone: str
    email: str
    city: str
    state: str
    tier: int
    pincode: str
    skin_type: str
    language: str
    channel: str
    created_at: datetime
    persona: str
    churn_at: datetime | None = None
    favourites: list[int] = field(default_factory=list)


def _weighted(rng: random.Random, weights: dict):
    return rng.choices(list(weights), weights=list(weights.values()), k=1)[0]


def _fmt(dt: datetime | None) -> str | None:
    return dt.strftime(DATE_FMT) if dt else None


class DatasetGenerator:
    def __init__(self, n_customers: int = 1500, months: int = 12, seed: int = 42,
                 end_date: datetime | None = None):
        self.rng = random.Random(seed)
        self.fake = Faker("en_IN")
        self.fake.seed_instance(seed)
        self.n_customers = n_customers
        self.end = (end_date or datetime.now()).replace(microsecond=0)
        self.start = self.end - timedelta(days=int(months * 30.4))

        self.pincodes: list[tuple] = []          # (pincode, city, state, tier)
        self.products: list[dict] = []
        self.customers: list[Customer] = []
        self.orders: list[dict] = []
        self.items: list[dict] = []
        self.tickets: list[dict] = []

    # ------------------------------------------------------------------ build
    def build(self) -> "DatasetGenerator":
        self._make_pincodes()
        self._make_products()
        self._make_customers()
        self._make_orders()
        self._make_tickets()
        return self

    def _make_pincodes(self):
        for city, state, tier, base in catalog.CITIES:
            for offset in self.rng.sample(range(0, 60), k=6):
                self.pincodes.append((str(base + offset), city, state, tier))

    def _make_products(self):
        for i, (name, cat, skins, concerns, ingr, price, mrp, size, desc) in enumerate(catalog.PRODUCTS, 1):
            self.products.append(dict(
                id=i, sku=f"KTL-{cat[:3].upper()}-{i:03d}", name=name, category=cat,
                skin_types=skins, concerns=concerns, key_ingredients=ingr, description=desc,
                price=float(price), mrp=float(mrp), size=size,
                stock=self.rng.choice([0, 4, 8]) if self.rng.random() < 0.1 else self.rng.randint(20, 400),
                rating=round(self.rng.uniform(3.8, 4.8), 1), is_active=1,
            ))

    def _make_customers(self):
        by_tier = {t: [p for p in self.pincodes if p[3] == t] for t in (1, 2, 3)}
        span = (self.end - self.start).total_seconds()
        phones: set[str] = set()
        for cid in range(1, self.n_customers + 1):
            tier = _weighted(self.rng, {1: 0.5, 2: 0.3, 3: 0.2})
            pincode, city, state, _ = self.rng.choice(by_tier[tier])
            lang_w = {1: {"en": 0.7, "hinglish": 0.25, "hi": 0.05},
                      2: {"en": 0.5, "hinglish": 0.4, "hi": 0.1},
                      3: {"en": 0.3, "hinglish": 0.5, "hi": 0.2}}[tier]
            # Growing brand: more sign-ups recently (sqrt skews towards the end).
            created = self.start + timedelta(seconds=span * (self.rng.random() ** 0.7))
            persona = _weighted(self.rng, {k: v[0] for k, v in PERSONAS.items()})
            churn_at = None
            if persona == "churned":
                churn_at = created + timedelta(days=self.rng.randint(45, 150))
            while True:
                phone = f"{self.rng.choice('6789')}{self.rng.randint(0, 999_999_999):09d}"
                if phone not in phones:
                    phones.add(phone)
                    break
            name = self.fake.name()
            skin = _weighted(self.rng, catalog.SKIN_TYPES)
            self.customers.append(Customer(
                id=cid, name=name, phone=phone,
                email=f"{name.lower().replace(' ', '.').replace('..', '.')}{cid}@example.com",
                city=city, state=state, tier=tier, pincode=pincode, skin_type=skin,
                language=_weighted(self.rng, lang_w),
                channel=_weighted(self.rng, catalog.ACQUISITION_CHANNELS),
                created_at=created, persona=persona, churn_at=churn_at,
                favourites=self._pick_products(skin, k=2),
            ))

    def _pick_products(self, skin: str, k: int) -> list[int]:
        matching = [p["id"] for p in self.products
                    if skin in p["skin_types"].split(",") or "all" in p["skin_types"].split(",")]
        out = []
        for _ in range(k):
            pool = matching if self.rng.random() < 0.75 else [p["id"] for p in self.products]
            out.append(self.rng.choice(pool))
        return out

    # ----------------------------------------------------------------- orders
    def _order_times(self, c: Customer) -> list[datetime]:
        """First order at sign-up, then a seasonal Poisson process."""
        times = [c.created_at]
        rate = PERSONAS[c.persona][1]  # orders / month
        if rate == 0:
            return times
        stop = min(self.end, c.churn_at or self.end)
        t = c.created_at
        max_mult = max(SEASONALITY.values())
        while True:
            t += timedelta(days=self.rng.expovariate(rate * max_mult / 30.4))
            if t >= stop:
                return times
            # "Thinning": accept the event with prob seasonal/max -> seasonal rate.
            if self.rng.random() < SEASONALITY[t.month] / max_mult:
                times.append(t)

    def _hour(self) -> int:
        w = [1, 1, 1, 1, 0.5, 0.5, 1, 2, 3, 4, 5, 5, 6, 6, 5, 5, 5, 6, 7, 9, 10, 10, 8, 4]
        return self.rng.choices(range(24), weights=w)[0]

    def _address(self, c: Customer, poor: bool) -> str:
        if poor:
            return self.rng.choice([f"near bus stand, {c.city}", f"{c.name.split()[0]} house, {c.city}",
                                    f"opp temple, main road, {c.city}", f"{c.city}"])
        return f"{self.fake.building_number()}, {self.fake.street_name()}, {c.city}, {c.state} - {c.pincode}"

    def _make_orders(self):
        product_by_id = {p["id"]: p for p in self.products}
        drafts = []
        for c in self.customers:
            delivered_before = 0
            for n, ts in enumerate(self._order_times(c)):
                ts = ts.replace(hour=self._hour(), minute=self.rng.randint(0, 59), second=self.rng.randint(0, 59))
                if ts > self.end:
                    ts = self.end - timedelta(minutes=self.rng.randint(5, 600))
                first = n == 0

                # --- basket
                lines: dict[int, int] = {}
                for _ in range(self.rng.choices([1, 2, 3, 4], weights=[45, 33, 15, 7])[0]):
                    if not first and self.rng.random() < 0.45:
                        pid = self.rng.choice(c.favourites)            # replenishment
                    else:
                        pid = self._pick_products(c.skin_type, 1)[0]
                    lines[pid] = lines.get(pid, 0) + (2 if self.rng.random() < 0.08 else 1)
                subtotal = sum(product_by_id[p]["price"] * q for p, q in lines.items())

                # --- coupon
                coupon = None
                if first and self.rng.random() < 0.35:
                    coupon = "WELCOME10"
                elif ts.month in (10, 11) and self.rng.random() < 0.4:
                    coupon = "DIWALI20"
                elif self.rng.random() < 0.08:
                    coupon = self.rng.choice(["GLOW15", "COMEBACK15"])
                discount = round(subtotal * catalog.COUPONS[coupon], 2) if coupon else 0.0
                shipping = config.SHIPPING_FEE if subtotal - discount < config.FREE_SHIPPING_THRESHOLD else 0.0
                total = round(subtotal - discount + shipping, 2)

                # --- payment & address
                cod_p = (0.75 if c.tier == 3 else 0.62 if c.tier == 2 else 0.5) if first else 0.38
                payment = "cod" if self.rng.random() < cod_p else "prepaid"
                poor = self.rng.random() < (0.22 if c.tier == 3 else 0.12 if c.tier == 2 else 0.06)
                addr_q = round(self.rng.uniform(0.15, 0.5) if poor else self.rng.uniform(0.7, 1.0), 2)

                # --- outcome (the RTO model's "ground truth")
                status, shipped, delivered, expected = self._outcome(
                    c, ts, payment, first, addr_q, total, delivered_before)
                if status == "delivered":
                    delivered_before += 1
                drafts.append(dict(
                    customer_id=c.id, created_at=ts, status=status, payment_method=payment,
                    subtotal=round(subtotal, 2), discount=discount, shipping_fee=shipping, total=total,
                    coupon_code=coupon, shipping_address=self._address(c, poor), shipping_pincode=c.pincode,
                    address_quality=addr_q, courier=self.rng.choice(catalog.COURIERS) if shipped else None,
                    shipped_at=shipped, delivered_at=delivered, expected_delivery=expected, _lines=lines,
                ))

        # Assign ids / order numbers in chronological order, like a real store.
        drafts.sort(key=lambda d: d["created_at"])
        for oid, d in enumerate(drafts, 1):
            lines = d.pop("_lines")
            d["id"] = oid
            d["order_number"] = f"KTL-{100000 + oid}"
            d["tracking_number"] = f"AWB{self.rng.randint(10**9, 10**10 - 1)}" if d["courier"] else None
            for k in ("created_at", "shipped_at", "delivered_at", "expected_delivery"):
                d[k] = _fmt(d[k])
            self.orders.append(d)
            for pid, qty in lines.items():
                self.items.append(dict(order_id=oid, product_id=pid, quantity=qty,
                                       unit_price=product_by_id[pid]["price"]))

    def _outcome(self, c, ts, payment, first, addr_q, total, delivered_before):
        transit = self.rng.randint(*{1: (2, 4), 2: (3, 5), 3: (4, 8)}[c.tier])
        expected = ts + timedelta(days=transit)
        shipped = ts + timedelta(hours=self.rng.randint(12, 36))
        age_days = (self.end - ts).total_seconds() / 86400

        if self.rng.random() < (0.04 if payment == "cod" else 0.015) and age_days > 0.2:
            return "cancelled", None, None, None
        if age_days < 1:
            return "placed", None, None, expected
        if age_days < transit:
            status = "out_for_delivery" if transit - age_days < 1 else "shipped"
            return status, shipped, None, expected

        if payment == "cod":
            risk = (0.08 + {1: 0.0, 2: 0.05, 3: 0.12}[c.tier] + (0.10 if first else 0.0)
                    + (0.15 if addr_q < 0.5 else 0.0) + (0.06 if total > 1500 else 0.0)
                    + (0.07 if ts.hour < 5 else 0.0) - min(delivered_before, 3) * 0.04)
        else:
            risk = 0.02
        if self.rng.random() < max(0.01, min(risk, 0.75)):
            return "rto", shipped, None, expected

        delivered = ts + timedelta(days=transit + self.rng.choice([0, 0, 0, 1, 2]),
                                   hours=self.rng.randint(0, 8))
        if self.rng.random() < 0.025:
            return "returned", shipped, delivered, expected
        return "delivered", shipped, delivered, expected

    # ---------------------------------------------------------------- tickets
    def _make_tickets(self):
        cust = {c.id: c for c in self.customers}
        for o in self.orders:
            c = cust[o["customer_id"]]
            category = {
                "placed": "cancel_order" if self.rng.random() < 0.15 else None,
                "shipped": "order_status" if self.rng.random() < 0.25 else None,
                "out_for_delivery": "order_status" if self.rng.random() < 0.1 else None,
                "returned": "refund" if self.rng.random() < 0.7 else None,
                "rto": None, "cancelled": None,
            }.get(o["status"])
            if o["status"] == "delivered":
                r = self.rng.random()
                late = o["delivered_at"] > o["expected_delivery"]
                category = ("damaged_product" if r < 0.03 else "allergic_reaction" if r < 0.035
                            else "order_status" if late and r < 0.2 else None)
            if category:
                base = datetime.strptime(o["created_at"], DATE_FMT)
                offset = timedelta(hours=self.rng.randint(2, 30)) if category in ("cancel_order",) else \
                    timedelta(days=self.rng.randint(1, 5), hours=self.rng.randint(0, 12))
                self._add_ticket(c, category, base + offset, o)

        # Pre-purchase questions & discount requests, not tied to an order.
        for c in self.customers:
            if self.rng.random() < 0.12:
                cat = self.rng.choice(["product_query", "product_query", "discount_request"])
                self._add_ticket(c, cat, c.created_at - timedelta(hours=self.rng.randint(1, 72)), None)

        self.tickets.sort(key=lambda t: t["created_at"])
        for i, t in enumerate(self.tickets, 1):
            t["id"] = i

    def _add_ticket(self, c: Customer, category: str, ts: datetime, order: dict | None):
        if ts >= self.end:  # would be in the future -> hasn't happened yet
            return
        priority, en, hing = catalog.TICKET_TEMPLATES[category]
        template = self.rng.choice(en if c.language == "en" else hing)
        concern = self.rng.choice(["acne", "dark spots", "dry skin", "oily skin", "tanning", "dark circles"])
        message = template.format(order=order["order_number"] if order else "", days=self.rng.randint(4, 9),
                                  concern=concern, skin=c.skin_type)
        age_h = (self.end - ts).total_seconds() / 3600
        # Phase-1 baseline: no AI yet, humans resolve everything (slowly).
        resolve_h = self.rng.uniform(2, 48) * (0.5 if priority == "high" else 1.0)
        if age_h > resolve_h:
            status, resolved_at, by = "resolved", ts + timedelta(hours=resolve_h), "human"
        else:
            status, resolved_at, by = ("escalated" if priority == "high" and self.rng.random() < 0.3 else "open"), None, None
        self.tickets.append(dict(
            customer_id=c.id, order_id=order["id"] if order else None, created_at=_fmt(ts),
            channel=_weighted(self.rng, {"whatsapp": 0.6, "email": 0.15, "website_chat": 0.25}),
            category=category, priority=priority, status=status, message=message,
            resolved_at=_fmt(resolved_at), resolved_by=by,
        ))

    # ------------------------------------------------------------------- save
    def save(self, db_path: Path | str | None = None) -> Path:
        path = db.reset_db(db_path)
        with db.get_conn(path) as conn:
            conn.executemany("INSERT INTO pincodes VALUES (?,?,?,?)", self.pincodes)
            conn.executemany(
                "INSERT INTO products (id, sku, name, category, skin_types, concerns, key_ingredients,"
                " description, price, mrp, size, stock, rating, is_active) VALUES (:id, :sku, :name,"
                " :category, :skin_types, :concerns, :key_ingredients, :description, :price, :mrp,"
                " :size, :stock, :rating, :is_active)", self.products)
            conn.executemany(
                "INSERT INTO customers (id, name, phone, email, city, state, pincode, skin_type,"
                " preferred_language, acquisition_channel, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                [(c.id, c.name, c.phone, c.email, c.city, c.state, c.pincode, c.skin_type, c.language,
                  c.channel, _fmt(c.created_at)) for c in self.customers])
            conn.executemany(
                "INSERT INTO orders (id, order_number, customer_id, created_at, status, payment_method,"
                " subtotal, discount, shipping_fee, total, coupon_code, shipping_address, shipping_pincode,"
                " address_quality, tracking_number, courier, shipped_at, delivered_at, expected_delivery)"
                " VALUES (:id, :order_number, :customer_id, :created_at, :status, :payment_method,"
                " :subtotal, :discount, :shipping_fee, :total, :coupon_code, :shipping_address,"
                " :shipping_pincode, :address_quality, :tracking_number, :courier, :shipped_at,"
                " :delivered_at, :expected_delivery)", self.orders)
            conn.executemany(
                "INSERT INTO order_items (order_id, product_id, quantity, unit_price)"
                " VALUES (:order_id, :product_id, :quantity, :unit_price)", self.items)
            conn.executemany(
                "INSERT INTO support_tickets (id, customer_id, order_id, created_at, channel, category,"
                " priority, status, message, resolved_at, resolved_by) VALUES (:id, :customer_id,"
                " :order_id, :created_at, :channel, :category, :priority, :status, :message,"
                " :resolved_at, :resolved_by)", self.tickets)
        return path


def generate(n_customers=1500, months=12, seed=42, end_date=None, db_path=None) -> Path:
    return DatasetGenerator(n_customers, months, seed, end_date).build().save(db_path)


def main():
    ap = argparse.ArgumentParser(description="Generate the Kotler AI demo database.")
    ap.add_argument("--customers", type=int, default=1500)
    ap.add_argument("--months", type=int, default=12)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--db", type=str, default=None, help="output path (default: data/kotler.db)")
    args = ap.parse_args()
    path = generate(args.customers, args.months, args.seed, db_path=args.db)
    with db.get_conn(path) as conn:
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                  for t in ("products", "customers", "orders", "order_items", "support_tickets")}
    print(f"Database written to {path}")
    for t, n in counts.items():
        print(f"  {t:<16} {n:>6}")


if __name__ == "__main__":
    main()
