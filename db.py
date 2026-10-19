"""Shared helpers for loaders writing prices.duckdb (same shape as demand-signals/db.py)."""
import hashlib, os, re
import duckdb

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.environ.get("PRICES_DB", os.path.join(HERE, "prices.duckdb"))
DETAIL = ["rate", "property", "vehicle", "service", "stat"]
TABLES = ["pull", "thing", "party", "price"] + DETAIL


def h(*parts):
    return hashlib.md5("|".join(map(str, parts)).encode()).hexdigest()[:16]


def connect():
    con = duckdb.connect(DB)
    con.execute(open(os.path.join(HERE, "schema.sql")).read())
    return con


def replace_pull(con, pull_id):
    """Drop everything a previous load of this pull wrote, so re-running is idempotent."""
    ids = f"(SELECT price_id FROM price WHERE pull_id = '{pull_id}')"
    for t in DETAIL:
        con.execute(f"DELETE FROM {t} WHERE price_id IN {ids}")
    con.execute("DELETE FROM price WHERE pull_id = ?", [pull_id])
    con.execute("DELETE FROM pull WHERE pull_id = ?", [pull_id])


INT64_MAX = 2 ** 63 - 1


def price_or_none(v):
    """A price as a float, or None. A value at the int64 ceiling is a scraper's overflow sentinel
    (a Craigslist '1997 VOLVO' loaded at $9,223,372,036,854,775,807 and became market_rate's max),
    never a price."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f >= INT64_MAX * 0.999:
        return None
    return f


FB_STATUS = {"just listed", "partner listing", "free", "pending", "sold"}


def parse_fb_title(t):
    """Facebook Marketplace card text -> (amount, title). The card reads '$150 | Table | City' or,
    for a fresh or partner listing, 'Just listed | $150 | Table | City'; a free item reads
    'Free | Scrap metal | City'. The price is wherever the '$' is, not only at the start."""
    parts = [s.strip() for s in (t or "").split("|")]
    amount = None
    for s in parts:
        m = re.match(r"^\$([\d,]+(?:\.\d{1,2})?)$", s)
        if m:
            amount = float(m.group(1).replace(",", ""))
            break
    if amount is None and any(s.lower() == "free" for s in parts):
        amount = 0.0
    rest = [s for s in parts if s and not re.match(r"^\$[\d,.]+$", s) and s.lower() not in FB_STATUS]
    return amount, (" | ".join(rest) if rest else (t or "").strip() or None)


def insert(con, table, df, upsert=False):
    """Insert a DataFrame by column name. upsert=True for shared dimension rows (thing, party)."""
    if df is None or len(df) == 0:
        return
    con.register("_df", df)
    cols = ", ".join(df.columns)
    con.execute(f"INSERT {'OR REPLACE ' if upsert else ''}INTO {table} ({cols}) SELECT {cols} FROM _df")
    con.unregister("_df")


def add_pull(con, pull_id, source, pulled_on, note):
    con.execute("INSERT INTO pull VALUES (?, ?, ?, ?)", [pull_id, source, pulled_on, note])


def counts(con):
    for t in TABLES:
        print(f"{t:9s}", con.execute(f"SELECT count(*) FROM {t}").fetchone()[0])
    for row in con.execute("SELECT source, basis, count(*) AS n FROM price GROUP BY ALL ORDER BY source, n DESC").fetchall():
        print(f"  {row[0]:24s} {row[1]:11s} {row[2]:>9,}")
