"""Load equipment, parts and used goods for sale, plus what agencies paid for parts.

Reads ~/Desktop/the-google-of-obsolete-infrastructure-parts in place (Legacy Requests):
  data/supply/*.jsonl   197,600 listings: Craigslist for-sale (all categories, ~50 metros), GovDeals + PublicSurplus
                        auctions, Eltra + Bid-on-Equipment dealers -> price basis=ask (dealer/owner) or bid (auction)
  data/worth_items.json 28,141 items grouping listings by maker + part number -> thing 'part:<id>';
                        its agency points (paid / contract, from council filings) -> basis=paid / negotiated
Craigslist 'wan' (wanted) rows are demand, not supply: skipped (they belong in demand-signals).
"""
import glob, json, os
import pandas as pd
from db import connect, replace_pull, insert, add_pull, counts

L = os.path.expanduser(os.environ.get("LEGACY_DIR", "~/Desktop/the-google-of-obsolete-infrastructure-parts"))
PULL_ID = os.environ.get("PULL_ID", "legacy-supply-2026-10-01")
AUCTION = {"govdeals", "publicsurplus"}
DEALER = {"eltra", "bidonequipment"}
# craigslist category -> domain (anything else is goods)
CL_DOMAIN = {"cto": "vehicle", "ctd": "vehicle", "boo": "vehicle", "boa": "vehicle", "bod": "vehicle", "mcy": "vehicle",
             "mcd": "vehicle", "rvs": "vehicle", "rvd": "vehicle", "pts": "part", "ptd": "part", "hvo": "goods", "hvd": "goods"}

items = json.load(open(os.path.join(L, "data/worth_items.json")))
url_item, things, extra = {}, [], []
for x in items:
    tid = "part:" + x["id"]
    things.append({"thing_id": tid, "domain": "part", "code_system": "part_number", "code": x.get("pn"),
                   "label": x.get("part") or x.get("name"), "category": x.get("equipment_class"),
                   "maker": x.get("manufacturer"), "model": x.get("model")})
    for p in x["points"]:
        url_item.setdefault(p["u"], tid)
        if p["s"] == "agency":
            extra.append((tid, p))

rows = []
for path in sorted(glob.glob(os.path.join(L, "data/supply/*.jsonl"))):
    for line in open(path):
        r = json.loads(line)
        src, cat = r.get("source"), r.get("category")
        if cat == "wan":
            continue
        loc = r.get("location")
        city = loc[1] if isinstance(loc, list) else loc
        if src == "craigslist":
            kind = "dealer" if cat and cat.endswith("d") else "person" if cat and cat.endswith("o") else "unknown"
        else:
            kind = "dealer" if src in DEALER else "agency"
        tid = url_item.get(r["url"]) or (f"cl:{cat}" if src == "craigslist" and cat else None)
        rows.append({"price_id": "sup:" + r["url"], "source": src, "thing_id": tid, "title": r.get("title"),
                     "seller_id": f"anon:{kind}", "basis": "bid" if src in AUCTION else "ask",
                     "amount": r.get("price"), "unit": "usd", "per": "each",
                     "observed_on": r.get("posted") or r.get("seen_at"), "city": city, "url": r["url"]})
price = pd.DataFrame(rows).drop_duplicates("price_id")
# One ad cross-posted to ~100 metros (same title, same price) is one price, not 100: keep the first.
n0 = len(price)
key = price["title"].str.lower().str.strip() + "|" + price["amount"].astype(str)
price = price[~(price["source"].eq("craigslist") & key.duplicated())]
print(f"craigslist cross-posts dropped: {n0 - len(price):,}")
price["observed_on"] = pd.to_datetime(price["observed_on"], errors="coerce").dt.date
price["amount"] = pd.to_numeric(price["amount"], errors="coerce")
price["pull_id"] = PULL_ID

cats = sorted({t for t in price["thing_id"].dropna() if t.startswith("cl:")})
things += [{"thing_id": c, "domain": CL_DOMAIN.get(c[3:], "goods"), "code_system": "craigslist_category", "code": c[3:],
            "label": f"Craigslist category '{c[3:]}' (uncoded listing: see price.title)"} for c in cats]

agency_rows, parties = [], {f"anon:{k}": {"party_id": f"anon:{k}", "kind": k, "name": f"unnamed {k}"} for k in ["dealer", "person", "unknown", "agency"]}
for i, (tid, p) in enumerate(extra):
    aid = "agency:" + (p.get("t") or "unknown")
    parties[aid] = {"party_id": aid, "kind": "agency", "name": p.get("t")}
    agency_rows.append({"price_id": f"agencypaid:{tid}:{i}", "pull_id": PULL_ID, "source": "council filings", "thing_id": tid,
                        "title": None, "buyer_id": aid, "basis": "paid" if p["k"] == "paid" else "negotiated",
                        "amount": p.get("p"), "unit": "usd", "per": "each", "qty": p.get("q"),
                        "observed_on": pd.to_datetime(p.get("d"), errors="coerce").date() if p.get("d") else None, "url": p.get("u")})

con = connect()
replace_pull(con, PULL_ID)
add_pull(con, PULL_ID, "Legacy Requests repo: data/supply + data/worth_items.json", "2026-10-01",
         "Craigslist for-sale sweep 2026-10-01 (asks), GovDeals/PublicSurplus auctions 2026-09-24 (current bids), dealers 2026-09-25, agency paid prices from filings")
insert(con, "thing", pd.DataFrame(things), upsert=True)
insert(con, "party", pd.DataFrame(parties.values()), upsert=True)
insert(con, "price", price)
insert(con, "price", pd.DataFrame(agency_rows))
con.execute("CHECKPOINT")
counts(con)
