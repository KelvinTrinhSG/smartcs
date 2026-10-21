-- Separate database for n8n
CREATE DATABASE n8n;

-- ---------- SmartCS business data (TechZone mock shop) ----------
CREATE TABLE products (
    sku             TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    category        TEXT NOT NULL,
    price_vnd       BIGINT NOT NULL,
    warranty_months INT NOT NULL,
    stock           INT NOT NULL DEFAULT 0
);

CREATE TABLE customers (
    id         SERIAL PRIMARY KEY,
    full_name  TEXT NOT NULL,
    phone      TEXT UNIQUE NOT NULL,
    email      TEXT
);

CREATE TABLE orders (
    order_id     TEXT PRIMARY KEY,
    customer_id  INT NOT NULL REFERENCES customers(id),
    status       TEXT NOT NULL CHECK (status IN ('pending','confirmed','shipping','delivered','cancelled','returned')),
    total_vnd    BIGINT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    delivered_at TIMESTAMPTZ
);

CREATE TABLE order_items (
    order_id TEXT NOT NULL REFERENCES orders(order_id),
    sku      TEXT NOT NULL REFERENCES products(sku),
    qty      INT NOT NULL,
    PRIMARY KEY (order_id, sku)
);

CREATE TABLE usage_logs (
    id          BIGSERIAL PRIMARY KEY,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    session_id  TEXT NOT NULL,
    channel     TEXT NOT NULL,
    model       TEXT NOT NULL,
    tokens_in   INT NOT NULL,
    tokens_out  INT NOT NULL,
    cost_usd    NUMERIC(12,6) NOT NULL,
    latency_ms  INT NOT NULL,
    cache_hit   BOOLEAN NOT NULL DEFAULT false
);

INSERT INTO products VALUES
 ('LT-ASUS-VB15', 'Laptop ASUS Vivobook 15',        'laptop',    15990000, 24, 12),
 ('LT-DELL-I14',  'Laptop Dell Inspiron 14',        'laptop',    18490000, 12, 8),
 ('LT-MAC-AIR13', 'MacBook Air 13 M3',              'laptop',    27990000, 12, 5),
 ('PH-IP16',      'iPhone 16 128GB',                'phone',     22990000, 12, 20),
 ('PH-SS-A55',    'Samsung Galaxy A55',             'phone',      9490000, 18, 30),
 ('AC-AIRPODS4',  'AirPods 4',                      'accessory',  3490000, 12, 40),
 ('AC-LOGI-MX3',  'Chuột Logitech MX Master 3S',    'accessory',  2290000, 12, 25),
 ('MN-LG-27UP',   'Màn hình LG 27UP850 4K',         'monitor',   10990000, 24, 6);

INSERT INTO customers (full_name, phone, email) VALUES
 ('Nguyễn Văn An',  '0901234567', 'an.nguyen@example.com'),
 ('Trần Thị Bình',  '0912345678', 'binh.tran@example.com'),
 ('Lê Hoàng Cường', '0987654321', 'cuong.le@example.com');

INSERT INTO orders VALUES
 ('TZ10001', 1, 'delivered', 15990000, now() - interval '95 days', now() - interval '92 days'),
 ('TZ10002', 1, 'shipping',   3490000, now() - interval '2 days',  NULL),
 ('TZ10003', 2, 'delivered', 22990000, now() - interval '10 days', now() - interval '8 days'),
 ('TZ10004', 3, 'pending',   10990000, now() - interval '1 hour',  NULL),
 ('TZ10005', 2, 'cancelled',  2290000, now() - interval '20 days', NULL);

INSERT INTO order_items VALUES
 ('TZ10001', 'LT-ASUS-VB15', 1),
 ('TZ10002', 'AC-AIRPODS4',  1),
 ('TZ10003', 'PH-IP16',      1),
 ('TZ10004', 'MN-LG-27UP',   1),
 ('TZ10005', 'AC-LOGI-MX3',  1);
