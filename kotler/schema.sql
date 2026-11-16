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
    is_active    INTEGER NOT NULL DEFAULT 1,
    image_url    TEXT                       -- packshot served by the API, e.g. /media/products/<slug>.jpg
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
    expected_delivery TEXT,
    source            TEXT NOT NULL DEFAULT 'store',  -- 'ai_chat' = placed from a product an AI agent recommended
    ai_ref            TEXT                             -- which chat it came from, e.g. 'telegram:12345'
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

-- ---------------------------------------------------------------- Phase 3
-- Agent Studio: an agent is CONFIGURATION, not code. The runtime reads these
-- rows, so a new agent (or a better prompt) needs no deploy.
CREATE TABLE IF NOT EXISTS agents (
    slug              TEXT PRIMARY KEY,            -- stable id, e.g. 'kavya'
    name              TEXT NOT NULL,               -- persona name shown to customers
    role              TEXT NOT NULL,               -- e.g. 'shopping assistant'
    description       TEXT NOT NULL DEFAULT '',    -- internal note for the team
    instructions      TEXT NOT NULL,               -- "Context & instructions"
    goal              TEXT NOT NULL,               -- "Agent's goal"
    success_criteria  TEXT NOT NULL,               -- "Success criteria" (also used by the judge)
    tools             TEXT NOT NULL,               -- JSON list of allowed tool names
    temperature       REAL NOT NULL DEFAULT 0.3,
    max_steps         INTEGER NOT NULL DEFAULT 5,
    status            TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'live')),
    version           INTEGER NOT NULL DEFAULT 1,
    is_builtin        INTEGER NOT NULL DEFAULT 0,
    updated_at        TEXT NOT NULL
);

-- Every save keeps a full snapshot, so any version can be compared or restored.
CREATE TABLE IF NOT EXISTS agent_versions (
    id          INTEGER PRIMARY KEY,
    slug        TEXT NOT NULL REFERENCES agents(slug) ON DELETE CASCADE,
    version     INTEGER NOT NULL,
    snapshot    TEXT NOT NULL,                     -- JSON of the whole config
    note        TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE (slug, version)
);

-- Results of the LLM judge scoring a conversation against the agent's success criteria.
CREATE TABLE IF NOT EXISTS conversation_scores (
    id               INTEGER PRIMARY KEY,
    conversation_id  INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    agent_slug       TEXT NOT NULL,
    agent_version    INTEGER,
    achieved         INTEGER NOT NULL,             -- 0/1: success criteria met?
    score            INTEGER NOT NULL,             -- 1-5 overall quality
    reason           TEXT,
    created_at       TEXT NOT NULL
);

-- ---------------------------------------------------------------- Phase 4
-- Every action an AI agent takes on an order is recorded: what, why, how much, and
-- whether it went through automatically or is waiting for a human.
CREATE TABLE IF NOT EXISTS order_actions (
    id               INTEGER PRIMARY KEY,
    action           TEXT NOT NULL CHECK (action IN ('cancel', 'refund', 'replacement', 'coupon', 'escalation')),
    status           TEXT NOT NULL CHECK (status IN ('done', 'pending_approval', 'approved', 'rejected')),
    order_id         INTEGER REFERENCES orders(id),
    customer_id      INTEGER REFERENCES customers(id),
    conversation_id  INTEGER REFERENCES conversations(id),
    agent_slug       TEXT,
    amount           REAL,
    reason           TEXT,
    details          TEXT,              -- JSON
    created_at       TEXT NOT NULL,
    decided_at       TEXT,
    decided_by       TEXT               -- 'auto' or the human reviewer
);
CREATE INDEX IF NOT EXISTS idx_actions_status ON order_actions(status);
CREATE INDEX IF NOT EXISTS idx_actions_order ON order_actions(order_id);

CREATE TABLE IF NOT EXISTS coupons_issued (
    code             TEXT PRIMARY KEY,
    customer_id      INTEGER NOT NULL REFERENCES customers(id),
    pct              INTEGER NOT NULL CHECK (pct BETWEEN 1 AND 50),
    reason           TEXT,
    conversation_id  INTEGER,
    created_at       TEXT NOT NULL,
    expires_at       TEXT NOT NULL
);

-- AI copilot runs on real support tickets: did the AI resolve it or hand it to a human?
CREATE TABLE IF NOT EXISTS ai_ticket_runs (
    id               INTEGER PRIMARY KEY,
    ticket_id        INTEGER NOT NULL REFERENCES support_tickets(id),
    conversation_id  INTEGER REFERENCES conversations(id),
    agent_slug       TEXT NOT NULL,
    outcome          TEXT NOT NULL CHECK (outcome IN ('resolved', 'escalated', 'error')),
    actions          INTEGER NOT NULL DEFAULT 0,
    latency_ms       INTEGER,
    created_at       TEXT NOT NULL
);
