"""Load private-party asks from two small marketplace sweeps.

Reads in place:
  ~/Desktop/presale-detail/data/listings.json   450 Minneapolis car + boat asks (Craigslist 300, Facebook 150), 2026-10-10
                                                -> basis=ask + vehicle detail; thing 'veh:<make model>' when stated
  ~/Desktop/on-the-house/drafts/fb-marketplace/listings_2026-10-10.json
                                                212 Facebook Marketplace asks (restaurant + demolition gear, Twin Cities)
                                                -> basis=ask, thing 'fb:<segment>' (uncoded; see title), seller = profile name
11 presale Craigslist URLs also appear in the Legacy supply sweep (load_parts.py); dedupe on url when counting.
"""
import json, os, re
import pandas as pd
from db import connect, replace_pull, insert, add_pull, counts

PRESALE = os.path.expanduser("~/Desktop/presale-detail/data/listings.json")
FB = os.path.expanduser("~/Desktop/on-the-house/drafts/fb-marketplace/listings_2026-10-10.json")
PULL_ID = os.environ.get("PULL_ID", "marketplace-2026-10-10")
num = lambda s: float(re.sub(r"[^\d.]", "", s)) if s and re.search(r"\d", str(s)) else None
norm = lambda s: re.sub(r"\s+", " ", s.strip().lower()) if s else None

price, vehicle, things, parties = [], [], {}, {}
for r in json.load(open(PRESALE))["listings"]:
    a = r.get("attrs") or {}
    if r["kind"] == "boat":
        make, model, year = a.get("make / manufacturer"), a.get("model name / number"), a.get("year manufactured")
    else:
        mm = (r.get("make_model") or "").split(" ", 1)
        make, model, year = (mm[0] or None), (mm[1] if len(mm) > 1 else None), r.get("year")
    tid = None
    if make:
        tid = "veh:" + norm(f"{make} {model or ''}")
        things[tid] = {"thing_id": tid, "domain": "vehicle", "code_system": "make_model", "code": norm(f"{make} {model or ''}"),
                       "label": f"{make} {model or ''}".strip(), "category": r["kind"], "maker": make, "model": model}
    pid = "mkt:" + r["url"]
    price.append({"price_id": pid, "source": r["source"], "thing_id": tid, "title": r.get("title"), "seller_id": "anon:person",
                  "basis": "ask", "amount": r.get("price"), "unit": "usd", "per": "each", "qty": 1,
                  "condition": a.get("condition"), "observed_on": (r.get("posted_at") or "")[:10] or None,
                  "city": r.get("location"), "state": "MN", "lat": r.get("lat"), "lon": r.get("lon"), "url": r["url"]})
    vehicle.append({"price_id": pid, "kind": r["kind"], "year": int(year) if year and str(year).isdigit() else None,
                    "make": make, "model": model, "mileage": num(a.get("odometer")), "engine_hours": num(a.get("engine hours (total)"))})

for r in json.load(open(FB)).values():
    m = re.match(r"\s*\$([\d,]+)", r.get("t") or "")
    lines = [l.strip("﻿ ").strip() for l in (r.get("seller") or "").split("\n")]
    name = lines[1] if len(lines) > 1 and lines[0] == "Seller details" else None
    sid = f"fb:{r['prof']['h']}" if (r.get("prof") or {}).get("h") else "anon:person"
    if sid != "anon:person":
        parties[sid] = {"party_id": sid, "kind": "person", "name": name, "url": f"https://www.facebook.com/marketplace/profile/{r['prof']['h']}/"}
    tid = f"fb:{r.get('seg')}"
    things[tid] = {"thing_id": tid, "domain": "goods", "code_system": "marketplace_segment", "code": r.get("seg"),
                   "label": f"Facebook Marketplace '{r.get('seg')}' search ({r.get('q')}); uncoded, see price.title"}
    desc = r.get("desc") or ""
    cond = re.search(r"Condition\n([^\n]+)", desc)
    price.append({"price_id": f"fbm:{r['id']}", "source": "facebook", "thing_id": tid,
                  "title": (r.get("t") or "").split("|", 1)[-1].strip() if m else r.get("t"), "seller_id": sid, "basis": "ask",
                  "amount": float(m.group(1).replace(",", "")) if m else None, "unit": "usd", "per": "each",
                  "condition": cond.group(1).strip().lower() if cond else None, "observed_on": "2026-10-10", "state": "MN",
                  "url": f"https://www.facebook.com/marketplace/item/{r['id']}/"})

price = pd.DataFrame(price).drop_duplicates("price_id")
price["observed_on"] = pd.to_datetime(price["observed_on"], errors="coerce").dt.date
price["pull_id"] = PULL_ID
con = connect()
replace_pull(con, PULL_ID)
add_pull(con, PULL_ID, "presale-detail + on-the-house fb-marketplace sweeps", "2026-10-10",
         "Minneapolis private car/boat asks (Craigslist + Facebook) and Twin Cities restaurant/demolition gear on Facebook Marketplace")
insert(con, "thing", pd.DataFrame(things.values()), upsert=True)
insert(con, "party", pd.DataFrame(parties.values()), upsert=True)
insert(con, "price", price)
insert(con, "vehicle", pd.DataFrame(vehicle).drop_duplicates("price_id"))
con.execute("CHECKPOINT")
counts(con)
