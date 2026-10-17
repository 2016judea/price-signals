"""Load the priced files in bricks/data that are not already a bricks platform slice.

Reads ~/Desktop/bricks/data in place:
  wichita_sales_benchmark_2026.json        742 validated commercial sales, Sedgwick County KS (KORA) -> basis=sold + property
  johnson_county_cap_rates_2012_2022.json  3,555 assessor cap rates by property class x eclass x year, Johnson County KS
                                           -> basis=benchmark, unit=cap_rate_pct (the price of income, not dollars)
  arbitrage.duckdb market_price            declared rows only (9 of 19; the other 10 are 'illustrative' placeholders)
Both Kansas files are NOT cleared for republication (their own provenance blocks say so). Local use only.
Not loaded: sector_benchmarks.json (hand-typed cost-structure ratios as strings like "32–36%", not price points);
arbitrage counterparty (2 of 6,801 rows carry a price).
"""
import json, os
import pandas as pd
from db import connect, replace_pull, insert, add_pull, counts

B = os.path.expanduser(os.environ.get("BRICKS_DATA", "~/Desktop/bricks/data"))
PULL_ID = os.environ.get("PULL_ID", "bricks-data-2026-10-17")

w = json.load(open(os.path.join(B, "wichita_sales_benchmark_2026.json")))
wr = pd.DataFrame(w["records"])
wr["price_id"] = "ks-sedgwick:" + wr["cov_no"].astype(str) + ":" + wr["pin"].astype(str)
wr = wr.drop_duplicates("price_id")
things = [{"thing_id": "ks-pin:sedgwick:" + p, "domain": "property", "code_system": "ks_pin", "code": p,
           "label": (n + ", " if n else "") + (a or ""), "category": m}
          for p, n, a, m in zip(wr["pin"], wr["building_name"].fillna(""), wr["address"].fillna(""), wr["market_model_desc"])]
price = [pd.DataFrame({"price_id": wr["price_id"], "pull_id": PULL_ID, "source": "sedgwick county appraiser",
                       "thing_id": "ks-pin:sedgwick:" + wr["pin"], "title": wr["building_name"], "basis": "sold",
                       "amount": wr["sale_price"], "unit": "usd", "per": "total", "qty": 1,
                       "observed_on": pd.to_datetime(wr["sale_date"], format="%m/%d/%Y", errors="coerce").dt.date,
                       "city": "Wichita", "state": "KS"})]
prop = pd.DataFrame({"price_id": wr["price_id"], "property_type": wr["market_model_desc"], "sqft": wr["gba"],
                     "year_built": wr["year_built"], "county": "sedgwick", "pin": wr["pin"], "sale_code": wr["validity"],
                     "note": "eclass " + wr["e_cls"].fillna("?") + "; trended 2026 price $" + wr["trended_sale_price"].astype(str)
                             + "; used_in_analysis=" + wr["used_in_analysis"].astype(str) + "; pins=" + wr["no_of_pins"].astype(str)})

c = pd.DataFrame(json.load(open(os.path.join(B, "johnson_county_cap_rates_2012_2022.json")))["records"])
c["thing_id"] = "caprate:johnson-ks:" + c["canonical_type"] + ":" + c["eclass"]
things += [{"thing_id": t, "domain": "cap_rate", "code_system": "property_class", "code": t.split(":", 2)[2],
            "label": f"{s} cap rate, class {e}", "category": m} for t, s, e, m in
           zip(c["thing_id"], c["source_label"], c["eclass"], c["market_model"])]
c["price_id"] = "caprate:" + c["year"].astype(str) + ":" + c["canonical_type"] + ":" + c["eclass"] + ":" + c["source_label"]
c = c.drop_duplicates("price_id")
price.append(pd.DataFrame({"price_id": c["price_id"], "pull_id": PULL_ID, "source": "johnson county appraiser", "thing_id": c["thing_id"],
                           "title": c["source_label"], "basis": "benchmark", "amount": c["cap_rate_pct"], "unit": "cap_rate_pct",
                           "per": "year", "observed_on": pd.to_datetime(c["year"].astype(str) + "-01-01").dt.date, "state": "KS"}))
stat = pd.DataFrame({"price_id": c["price_id"], "statistic": "assessor_cap_rate", "geography": "county:johnson-ks",
                     "note": "rate source: " + c["rate_source"].fillna("?") + "; sheet " + c["source_sheet"].fillna("?")})

con = connect()
replace_pull(con, PULL_ID)
add_pull(con, PULL_ID, "bricks/data priced files", "2026-10-17",
         "Sedgwick KS sales benchmark (KORA 2026-08-31), Johnson KS cap rates 2012-2022 (KORA 2026-09-11), arbitrage.duckdb declared market prices")
con.execute(f"ATTACH '{B}/arbitrage.duckdb' AS a (READ_ONLY)")
mp = con.execute("""SELECT m.*, t.label AS mlabel, t.kind FROM a.market_price m LEFT JOIN a.material t ON t.id = m.material_id
                    WHERE m.basis <> 'illustrative'""").df()
things += [{"thing_id": "material:" + r.material_id, "domain": "commodity", "code_system": "material", "code": r.material_id,
            "label": r.mlabel, "category": r.kind} for r in mp.itertuples()]
price.append(pd.DataFrame({"price_id": "arb:" + mp["id"], "pull_id": PULL_ID, "source": "arbitrage.duckdb", "thing_id": "material:" + mp["material_id"],
                           "title": mp["note"], "basis": "benchmark", "amount": mp["price_usd"], "amount_high": mp["price_high_usd"],
                           "unit": "usd", "per": mp["unit"], "observed_on": pd.to_datetime(mp["observed"]).dt.date,
                           "state": mp["geography"].map(lambda g: "MN" if g == "Minnesota" else None)}))
stat = pd.concat([stat, pd.DataFrame({"price_id": "arb:" + mp["id"], "statistic": mp["side"] + " price", "geography": mp["geography"],
                                      "p25": mp["price_low_usd"], "p75": mp["price_high_usd"], "note": "low/high stored in p25/p75; source " + mp["source_id"]})])

insert(con, "thing", pd.DataFrame(things).drop_duplicates("thing_id"), upsert=True)
insert(con, "price", pd.concat(price))
insert(con, "property", prop)
insert(con, "stat", stat)
con.execute("CHECKPOINT")
counts(con)
