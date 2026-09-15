"""
usecases/retail/topics.py — shared constants for the Retail use case.
"""

TOPIC_ORDERS   = "retail-orders"     # purchase events
TOPIC_RETURNS  = "retail-returns"    # return / refund events
TOPIC_BROWSE   = "retail-browse"     # page-view / add-to-cart events

ALL_TOPICS = [TOPIC_ORDERS, TOPIC_RETURNS, TOPIC_BROWSE]

# ── Flink SQL-safe names (backtick-quoted for use in SQL strings) ─────────────
# Hyphenated topic names are treated as subtraction by Flink's SQL parser.
# Use these constants when building any Flink SQL query string.
#   e.g.  f"SELECT * FROM {FLINK_ORDERS} LIMIT 10"
FLINK_ORDERS   = f"`{TOPIC_ORDERS}`"    # `retail-orders`
FLINK_RETURNS  = f"`{TOPIC_RETURNS}`"   # `retail-returns`
FLINK_BROWSE   = f"`{TOPIC_BROWSE}`"    # `retail-browse`

# ── Customer catalogue (20 simulated shoppers) ────────────────────────────────
CUSTOMERS = [
    {"customer_id": "C001", "name": "Alice Johnson",   "email": "alice@example.com",   "segment": "premium"},
    {"customer_id": "C002", "name": "Bob Smith",       "email": "bob@example.com",     "segment": "regular"},
    {"customer_id": "C003", "name": "Carol Davis",     "email": "carol@example.com",   "segment": "premium"},
    {"customer_id": "C004", "name": "Dan Martinez",    "email": "dan@example.com",     "segment": "regular"},
    {"customer_id": "C005", "name": "Eva Wilson",      "email": "eva@example.com",     "segment": "vip"},
    {"customer_id": "C006", "name": "Frank Lee",       "email": "frank@example.com",   "segment": "regular"},
    {"customer_id": "C007", "name": "Grace Kim",       "email": "grace@example.com",   "segment": "premium"},
    {"customer_id": "C008", "name": "Hank Brown",      "email": "hank@example.com",    "segment": "regular"},
    {"customer_id": "C009", "name": "Iris Chen",       "email": "iris@example.com",    "segment": "vip"},
    {"customer_id": "C010", "name": "Jack Taylor",     "email": "jack@example.com",    "segment": "regular"},
    {"customer_id": "C011", "name": "Karen White",     "email": "karen@example.com",   "segment": "premium"},
    {"customer_id": "C012", "name": "Leo Garcia",      "email": "leo@example.com",     "segment": "regular"},
    {"customer_id": "C013", "name": "Mia Robinson",    "email": "mia@example.com",     "segment": "vip"},
    {"customer_id": "C014", "name": "Noah Clark",      "email": "noah@example.com",    "segment": "regular"},
    {"customer_id": "C015", "name": "Olivia Hall",     "email": "olivia@example.com",  "segment": "premium"},
    {"customer_id": "C016", "name": "Paul Allen",      "email": "paul@example.com",    "segment": "regular"},
    {"customer_id": "C017", "name": "Quinn Young",     "email": "quinn@example.com",   "segment": "regular"},
    {"customer_id": "C018", "name": "Rachel Scott",    "email": "rachel@example.com",  "segment": "premium"},
    {"customer_id": "C019", "name": "Sam Harris",      "email": "sam@example.com",     "segment": "regular"},
    {"customer_id": "C020", "name": "Tina Lewis",      "email": "tina@example.com",    "segment": "vip"},
]

CUSTOMER_MAP = {c["customer_id"]: c for c in CUSTOMERS}

# ── Product catalogue ─────────────────────────────────────────────────────────
PRODUCTS = [
    {"product_id": "P001", "name": "Wireless Headphones",  "category": "Electronics",  "price": 89.99,  "return_rate": 0.08},
    {"product_id": "P002", "name": "Running Shoes",        "category": "Footwear",     "price": 129.99, "return_rate": 0.15},
    {"product_id": "P003", "name": "Coffee Maker",         "category": "Appliances",   "price": 59.99,  "return_rate": 0.05},
    {"product_id": "P004", "name": "Yoga Mat",             "category": "Sports",       "price": 34.99,  "return_rate": 0.04},
    {"product_id": "P005", "name": "Winter Jacket",        "category": "Clothing",     "price": 199.99, "return_rate": 0.20},
    {"product_id": "P006", "name": "Smart Watch",          "category": "Electronics",  "price": 249.99, "return_rate": 0.10},
    {"product_id": "P007", "name": "Blender",              "category": "Appliances",   "price": 49.99,  "return_rate": 0.06},
    {"product_id": "P008", "name": "Denim Jeans",          "category": "Clothing",     "price": 79.99,  "return_rate": 0.18},
    {"product_id": "P009", "name": "Gaming Mouse",         "category": "Electronics",  "price": 59.99,  "return_rate": 0.07},
    {"product_id": "P010", "name": "Backpack",             "category": "Accessories",  "price": 69.99,  "return_rate": 0.09},
    {"product_id": "P011", "name": "Desk Lamp",            "category": "Home",         "price": 44.99,  "return_rate": 0.03},
    {"product_id": "P012", "name": "Protein Powder",       "category": "Health",       "price": 39.99,  "return_rate": 0.02},
    {"product_id": "P013", "name": "Sunglasses",           "category": "Accessories",  "price": 99.99,  "return_rate": 0.12},
    {"product_id": "P014", "name": "Air Fryer",            "category": "Appliances",   "price": 89.99,  "return_rate": 0.07},
    {"product_id": "P015", "name": "Sneakers",             "category": "Footwear",     "price": 109.99, "return_rate": 0.14},
]

PRODUCT_MAP = {p["product_id"]: p for p in PRODUCTS}

# ── Segment colour palette ────────────────────────────────────────────────────
SEGMENT_COLOUR = {"vip": "#7c3aed", "premium": "#2563eb", "regular": "#64748b"}

# ── Behaviour sets (used by producer and MCP server) ─────────────────────────
# Customers who are deliberately inactive (for demo)
INACTIVE_CUSTOMERS = {"C006", "C012", "C016", "C019"}

# Customers with high return tendency
HIGH_RETURNERS = {"C004", "C008", "C014", "C017"}

# ── Status colours ────────────────────────────────────────────────────────────
STATUS_COLOUR = {
    "completed":  "#16a34a",
    "pending":    "#ca8a04",
    "cancelled":  "#dc2626",
    "returned":   "#9333ea",
    "browsing":   "#0891b2",
}
