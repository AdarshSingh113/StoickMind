-- Kotler AI — Phase 1 schema
-- Every later module reads from these tables:
--   Shopping agent  -> products
--   Support agent   -> orders, order_items, support_tickets
--   CRM / RFM / CLV -> customers, orders
--   RTO predictor   -> orders (payment_method, pincode tier, address quality, outcome)

PRAGMA foreign_keys = ON;

-- Reference table: what we know about each delivery location.
-- Tier matters a lot for COD return-to-origin (RTO) risk in India.
CREATE TABLE IF NOT EXISTS pincodes (
    pincode      TEXT PRIMARY KEY,
    city         TEXT NOT NULL,
    state        TEXT NOT NULL,
    tier         INTEGER NOT NULL CHECK (tier IN (1, 2, 3))
);

CREATE TABLE IF NOT EXISTS products (
    id           INTEGER PRIMARY KEY,
    sku          TEXT NOT NULL UNIQUE,
    name         TEXT NOT NULL,
    category     TEXT NOT NULL,              -- face_wash, moisturizer, serum, ...
    skin_types   TEXT NOT NULL,              -- comma list: oily,dry,combination,sensitive,normal,all
    concerns     TEXT NOT NULL DEFAULT '',   -- comma list: acne,pigmentation,dullness,...
    key_ingredients TEXT NOT NULL DEFAULT '',
    description  TEXT NOT NULL,
    price        REAL NOT NULL CHECK (price > 0),   -- selling price (INR)
    mrp          REAL NOT NULL CHECK (mrp >= price),-- maximum retail price (INR)
    size         TEXT NOT NULL,
    stock        INTEGER NOT NULL DEFAULT 0 CHECK (stock >= 0),
    rating       REAL NOT NULL DEFAULT 0,
    is_active    INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS customers (
    id                  INTEGER PRIMARY KEY,
    name                TEXT NOT NULL,
    phone               TEXT NOT NULL UNIQUE,
    email               TEXT,
    city                TEXT NOT NULL,
    state               TEXT NOT NULL,
    pincode             TEXT NOT NULL REFERENCES pincodes(pincode),
    skin_type           TEXT,                -- learned from quiz / conversations
    preferred_language  TEXT NOT NULL DEFAULT 'en' CHECK (preferred_language IN ('en', 'hinglish', 'hi')),
    acquisition_channel TEXT NOT NULL,       -- instagram, google, whatsapp, referral, ...
    created_at          TEXT NOT NULL        -- ISO-8601
);

CREATE TABLE IF NOT EXISTS orders (
    id                INTEGER PRIMARY KEY,
    order_number      TEXT NOT NULL UNIQUE,  -- what the customer sees, e.g. KTL-100245
    customer_id       INTEGER NOT NULL REFERENCES customers(id),
    created_at        TEXT NOT NULL,
    status            TEXT NOT NULL CHECK (status IN
                        ('placed', 'shipped', 'out_for_delivery', 'delivered',
                         'cancelled', 'rto', 'returned')),
    payment_method    TEXT NOT NULL CHECK (payment_method IN ('cod', 'prepaid')),
    subtotal          REAL NOT NULL,
    discount          REAL NOT NULL DEFAULT 0,
    shipping_fee      REAL NOT NULL DEFAULT 0,
    total             REAL NOT NULL,
    coupon_code       TEXT,
    shipping_address  TEXT NOT NULL,
    shipping_pincode  TEXT NOT NULL REFERENCES pincodes(pincode),
    address_quality   REAL NOT NULL,         -- 0..1, how complete/valid the address looks
    tracking_number   TEXT,
    courier           TEXT,
    shipped_at        TEXT,
    delivered_at      TEXT,
    expected_delivery TEXT
);

CREATE TABLE IF NOT EXISTS order_items (
    id          INTEGER PRIMARY KEY,
    order_id    INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
    product_id  INTEGER NOT NULL REFERENCES products(id),
    quantity    INTEGER NOT NULL CHECK (quantity > 0),
    unit_price  REAL NOT NULL               -- price at time of purchase (prices change!)
);

CREATE TABLE IF NOT EXISTS support_tickets (
    id           INTEGER PRIMARY KEY,
    customer_id  INTEGER NOT NULL REFERENCES customers(id),
    order_id     INTEGER REFERENCES orders(id),
    created_at   TEXT NOT NULL,
    channel      TEXT NOT NULL,             -- whatsapp, email, website_chat
    category     TEXT NOT NULL,             -- order_status, damaged_product, refund, product_query, ...
    priority     TEXT NOT NULL CHECK (priority IN ('low', 'medium', 'high')),
    status       TEXT NOT NULL CHECK (status IN ('open', 'resolved', 'escalated')),
    message      TEXT NOT NULL,
    resolved_at  TEXT,
    resolved_by  TEXT CHECK (resolved_by IN ('ai', 'human') OR resolved_by IS NULL)
);

-- Indexes on the columns we filter/join by most often.
CREATE INDEX IF NOT EXISTS idx_orders_customer   ON orders(customer_id);
CREATE INDEX IF NOT EXISTS idx_orders_created    ON orders(created_at);
CREATE INDEX IF NOT EXISTS idx_items_order       ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_items_product     ON order_items(product_id);
CREATE INDEX IF NOT EXISTS idx_tickets_customer  ON support_tickets(customer_id);
CREATE INDEX IF NOT EXISTS idx_customers_phone   ON customers(phone);

-- ---------------------------------------------------------------- Phase 2
-- Every chat is stored: it's the customer's history (memory), the data for
-- evaluation (Phase 6), and the audit trail of what the AI said and did.
CREATE TABLE IF NOT EXISTS conversations (
    id           INTEGER PRIMARY KEY,
    customer_id  INTEGER REFERENCES customers(id),   -- NULL = guest
    agent        TEXT NOT NULL,                      -- 'shopping', later 'support'
    channel      TEXT NOT NULL DEFAULT 'web',        -- web, whatsapp, telegram
    model        TEXT,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id                 INTEGER PRIMARY KEY,
    conversation_id    INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    role               TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'tool')),
    content            TEXT,
    tool_name          TEXT,
    tool_args          TEXT,        -- JSON
    created_at         TEXT NOT NULL,
    latency_ms         INTEGER,
    prompt_tokens      INTEGER,
    completion_tokens  INTEGER,
    error              TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id);
