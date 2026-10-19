"""Loader helper tests. The schema runs against an in-memory DuckDB; prices.duckdb is never opened.
Run: .venv/bin/python -m pytest tests"""
import os, sys
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
os.environ["PRICES_DB"] = ":memory:"
import pandas as pd
import pytest
import db


@pytest.mark.parametrize("text,amount,title", [
    ("$150 | Stainless prep table | Minneapolis, MN", 150.0, "Stainless prep table | Minneapolis, MN"),
    ("$1,200 | Hobart mixer | St Paul, MN", 1200.0, "Hobart mixer | St Paul, MN"),
    # a fresh or partner listing puts a status word first; the old regex was anchored at the start and lost the ask
    ("Just listed | $150 | STABLEINK Stainless Steel Table | Minneapolis, MN", 150.0, "STABLEINK Stainless Steel Table | Minneapolis, MN"),
    ("Partner listing | $147.90 | Compustar Cs8910-a, 2-way Security/alarm", 147.90, "Compustar Cs8910-a, 2-way Security/alarm"),
    ("Just listed | $40 | Architectural porch posts | Houlton, WI", 40.0, "Architectural porch posts | Houlton, WI"),
    ("Free | Free restaurant supplies | St Paul, MN", 0.0, "Free restaurant supplies | St Paul, MN"),
    ("Just listed | Free | Free Scrap Metal Furnace - Anoka | Anoka, MN", 0.0, "Free Scrap Metal Furnace - Anoka | Anoka, MN"),
    ("Restaurant Equipment | Minneapolis, MN", None, "Restaurant Equipment | Minneapolis, MN"),
    ("", None, None), (None, None, None),
])
def test_parse_fb_title(text, amount, title):
    assert db.parse_fb_title(text) == (amount, title)


@pytest.mark.parametrize("raw,expect", [
    (1200.0, 1200.0), ("1200", 1200.0), (0, 0.0), (None, None), ("", None), ("$1,200", None), (float("nan"), None),
    (9223372036854775807, None), (9.223372036854776e+18, None),   # the int64 overflow sentinel in the Craigslist sweep
])
def test_price_or_none(raw, expect):
    assert db.price_or_none(raw) == expect


def test_market_rate_never_shows_the_overflow_sentinel_as_a_max():
    con = db.connect()
    db.add_pull(con, "p", "x", "2026-10-01", "")
    db.insert(con, "thing", pd.DataFrame([{"thing_id": "cl:hvo", "domain": "goods", "code_system": "part_number", "label": "x"}]), upsert=True)
    rows = [{"price_id": f"sup:{i}", "pull_id": "p", "source": "craigslist", "thing_id": "cl:hvo", "basis": "ask",
             "amount": db.price_or_none(v), "unit": "usd", "per": "each"} for i, v in enumerate([100, 120, 9223372036854775807])]
    db.insert(con, "price", pd.DataFrame(rows))
    assert con.execute("SELECT n, max FROM market_rate").fetchone() == (2, 120.0)


def test_replace_pull_removes_detail_rows_with_their_prices():
    con = db.connect()
    db.add_pull(con, "p", "x", "2026-10-01", "")
    db.insert(con, "price", pd.DataFrame([{"price_id": "a", "pull_id": "p", "source": "s", "basis": "ask", "amount": 1.0, "unit": "usd"}]))
    db.insert(con, "vehicle", pd.DataFrame([{"price_id": "a", "kind": "car"}]))
    db.replace_pull(con, "p")
    assert con.execute("SELECT count(*) FROM price").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM vehicle").fetchone()[0] == 0
    assert con.execute("SELECT count(*) FROM pull").fetchone()[0] == 0
