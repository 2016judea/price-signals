"""Shared helpers for loaders writing prices.duckdb (same shape as demand-signals/db.py)."""
import hashlib, os
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
