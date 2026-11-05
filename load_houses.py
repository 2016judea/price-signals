"""Load Twin Cities home prices: asks, MLS closes, county-recorded sales, and the index's own estimate.

Reads ~/Desktop/workspace/msp-house-index/data in place:
  listings_raw.jsonl (Realtor.com for-sale, 2026-10-11)  -> basis=ask; thing = county PIN when index.csv matched it, else rdc:<property_id>
  sold_raw.jsonl     (Realtor.com closed, 12 months)      -> basis=sold; property.list_price = the row's list_price (see trap)
  index.csv          (the index's valuation per listing) -> basis=estimate (column `worth`)
  county.duckdb      hn_sales (Hennepin, month grain, 2024-01..2026-07) + sales (other 6 counties, day grain)
                                                         -> basis=sold, thing pin:<county>:<pin>, address from parcels
"""
import os
from db import connect, replace_pull, add_pull, counts

D = os.path.expanduser(os.environ.get("HOUSE_DIR", "~/Desktop/workspace/msp-house-index/data"))
PULL_ID = os.environ.get("PULL_ID", "msp-house-2026-10-12")
COUNTY_PULL = os.environ.get("COUNTY_PULL_ID", "mn-county-sales-2026-10-11")
J = "maximum_object_size=20000000"

con = connect()
for p in (PULL_ID, COUNTY_PULL):
    replace_pull(con, p)
add_pull(con, PULL_ID, "msp-house-index repo (Realtor.com search, MetroGIS parcels)", "2026-10-12",
         "7-county metro: 14,561 for-sale asks 2026-10-11, 49,444 closes 2025-10..2026-10, index valuation per listing")
add_pull(con, COUNTY_PULL, "county.duckdb in msp-house-index (MetroGIS parcels + Hennepin sales)", "2026-10-11",
         "recorded sale prices: Hennepin 2024-01..2026-07 (month grain, with sale code), 6 other counties 2025-01..2026-06")

con.execute(f"CREATE TEMP TABLE idx AS SELECT * FROM read_csv('{D}/index.csv', all_varchar=true)")
con.execute(f"CREATE TEMP TABLE ls AS SELECT * FROM read_json('{D}/listings_raw.jsonl', {J})")
con.execute(f"CREATE TEMP TABLE sd AS SELECT * FROM read_json('{D}/sold_raw.jsonl', {J})")

# listing agents as parties (the homeowner is not named; the agent is who sets and publishes the ask)
con.execute("""
INSERT OR IGNORE INTO party (party_id, kind, name, note)
SELECT DISTINCT 'agent:' || md5(concat_ws('|', a.name, a.office.name))[:12], 'agent', a.name, a.office.name
FROM (SELECT unnest(advertisers) AS a FROM ls UNION ALL SELECT unnest(advertisers) AS a FROM sd) WHERE a.name IS NOT NULL""")

# property things
con.execute("""
CREATE TEMP TABLE pin_of AS SELECT property_id, county, pin FROM idx WHERE pin IS NOT NULL QUALIFY row_number() OVER (PARTITION BY property_id) = 1""")
con.execute("""
INSERT OR IGNORE INTO thing (thing_id, domain, code_system, code, label, category)
SELECT DISTINCT coalesce('pin:' || p.county || ':' || p.pin, 'rdc:' || x.property_id),
  'property', CASE WHEN p.pin IS NULL THEN 'rdc_property' ELSE 'mn_pin' END, coalesce(p.pin, x.property_id::TEXT),
  x.location.address.line || ', ' || x.location.address.city, x.description.type
FROM (SELECT property_id::TEXT AS property_id, location, description FROM ls
      UNION ALL SELECT property_id::TEXT, location, description FROM sd) x
LEFT JOIN pin_of p USING (property_id)""")

common = """x.location.address.city, 'MN', x.location.address.postal_code, x.location.address.coordinate.lat,
  x.location.address.coordinate.lon, x.href"""
seller = "'agent:' || md5(concat_ws('|', x.advertisers[1].name, x.advertisers[1].office.name))[:12]"
con.execute(f"""
INSERT INTO price (price_id, pull_id, source, thing_id, title, seller_id, basis, amount, unit, per, qty, observed_on,
  city, state, zip, lat, lon, url)
SELECT 'rdc:ask:' || x.listing_id, '{PULL_ID}', 'realtor.com', coalesce('pin:' || p.county || ':' || p.pin, 'rdc:' || x.property_id),
  x.location.address.line, CASE WHEN x.advertisers[1].name IS NOT NULL THEN {seller} END, 'ask', x.list_price, 'usd', 'total', 1,
  x.list_date::DATE, {common}
FROM ls x LEFT JOIN pin_of p ON p.property_id = x.property_id::TEXT
QUALIFY row_number() OVER (PARTITION BY x.listing_id ORDER BY x.list_date DESC) = 1""")
con.execute(f"""
INSERT INTO property (price_id, property_type, beds, baths, sqft, lot_sqft, year_built, county, pin, list_price, est_value, days_on_market)
SELECT 'rdc:ask:' || x.listing_id, x.description.type, x.description.beds, x.description.baths, x.description.sqft,
  x.description.lot_sqft, x.description.year_built, lower(x.location.county.name), p.pin, x.list_price,
  try_cast(i.worth AS DOUBLE), try_cast(i.dom AS INT)
FROM ls x LEFT JOIN pin_of p ON p.property_id = x.property_id::TEXT
LEFT JOIN (SELECT * FROM idx QUALIFY row_number() OVER (PARTITION BY listing_id) = 1) i ON i.listing_id = x.listing_id::TEXT
QUALIFY row_number() OVER (PARTITION BY x.listing_id ORDER BY x.list_date DESC) = 1""")

con.execute(f"""
CREATE TEMP TABLE sd1 AS SELECT * FROM sd WHERE description.sold_price > 0
QUALIFY row_number() OVER (PARTITION BY property_id, description.sold_date ORDER BY listing_id) = 1""")
con.execute(f"""
INSERT INTO price (price_id, pull_id, source, thing_id, title, seller_id, basis, amount, unit, per, qty, observed_on,
  city, state, zip, lat, lon, url)
SELECT 'rdc:sold:' || x.property_id || ':' || x.description.sold_date, '{PULL_ID}', 'realtor.com',
  coalesce('pin:' || p.county || ':' || p.pin, 'rdc:' || x.property_id), x.location.address.line,
  CASE WHEN x.advertisers[1].name IS NOT NULL THEN {seller} END, 'sold', x.description.sold_price, 'usd', 'total', 1,
  x.description.sold_date::DATE, {common}
FROM sd1 x LEFT JOIN pin_of p ON p.property_id = x.property_id::TEXT""")
con.execute(f"""
INSERT INTO property (price_id, property_type, beds, baths, sqft, lot_sqft, year_built, county, pin, list_price, note)
SELECT 'rdc:sold:' || x.property_id || ':' || x.description.sold_date, x.description.type, x.description.beds, x.description.baths,
  x.description.sqft, x.description.lot_sqft, x.description.year_built, lower(x.location.county.name), p.pin,
  CASE WHEN x.list_price <> x.description.sold_price THEN x.list_price END,
  CASE WHEN x.list_price = x.description.sold_price THEN 'list_price equals sold price on this row: last ask unknown' END
FROM sd1 x LEFT JOIN pin_of p ON p.property_id = x.property_id::TEXT""")

# the index's valuation (after-repair 'worth' from county x local ratio, comps, last sale brought forward)
con.execute(f"""
INSERT INTO price (price_id, pull_id, source, thing_id, title, basis, amount, unit, per, qty, observed_on, city, state, zip, lat, lon, url)
SELECT 'msp:est:' || i.listing_id, '{PULL_ID}', 'msp-house-index', coalesce('pin:' || i.county || ':' || i.pin, 'rdc:' || i.property_id),
  i.address, 'estimate', try_cast(i.worth AS DOUBLE), 'usd', 'total', 1, DATE '2026-10-12', i.city, 'MN', i.zip,
  try_cast(i.lat AS DOUBLE), try_cast(i.lon AS DOUBLE), i.url
FROM idx i WHERE try_cast(i.worth AS DOUBLE) > 0 QUALIFY row_number() OVER (PARTITION BY i.listing_id) = 1""")
con.execute(f"""
INSERT INTO stat (price_id, statistic, n, geography, note)
SELECT 'msp:est:' || listing_id, 'estimate', try_cast(n_estimates AS DOUBLE), 'property', 'tier=' || tier || '; agree=' || agree
FROM idx WHERE try_cast(worth AS DOUBLE) > 0 QUALIFY row_number() OVER (PARTITION BY listing_id) = 1""")

# county-recorded sales
con.execute(f"ATTACH '{D}/county.duckdb' AS k (READ_ONLY)")
con.execute("""
CREATE TEMP TABLE cs AS
SELECT 'hennepin' AS county, pin, sale_price AS price, sale_month AS sale_date, sale_code, emv, hn_type AS ptype, 'month' AS grain
FROM k.hn_sales WHERE sale_price > 0
UNION ALL
SELECT county, pin, price, sale_date, sale_code, emv, useclass, 'day' FROM k.sales WHERE county <> 'hennepin' AND price > 0""")
con.execute("""
CREATE TEMP TABLE cs2 AS
SELECT cs.*, p.anumber, p.street, p.unit, p.city, p.zip, p.lat, p.lon, p.year_built, p.fin_sq_ft, p.area_sqft
FROM cs LEFT JOIN (SELECT * FROM k.parcels QUALIFY row_number() OVER (PARTITION BY county, pin) = 1) p USING (county, pin)""")
con.execute("""
INSERT OR IGNORE INTO thing (thing_id, domain, code_system, code, label, category)
SELECT DISTINCT 'pin:' || county || ':' || pin, 'property', 'mn_pin', pin,
  concat_ws(' ', anumber, street, CASE WHEN unit IS NOT NULL THEN '#' || unit END) || coalesce(', ' || city, ''), ptype FROM cs2""")
con.execute(f"""
INSERT INTO price (price_id, pull_id, source, thing_id, title, buyer_id, basis, amount, unit, per, qty, observed_on, city, state, zip, lat, lon)
SELECT 'deed:' || county || ':' || pin || ':' || sale_date || ':' || price, '{COUNTY_PULL}', 'county:' || county, 'pin:' || county || ':' || pin,
  concat_ws(' ', anumber, street), NULL, 'sold', price, 'usd', 'total', 1, sale_date, city, 'MN', zip, lat, lon
FROM cs2 QUALIFY row_number() OVER (PARTITION BY county, pin, sale_date, price) = 1""")
con.execute(f"""
INSERT INTO property (price_id, property_type, sqft, lot_sqft, year_built, county, pin, est_value, sale_code, note)
SELECT 'deed:' || county || ':' || pin || ':' || sale_date || ':' || price, ptype, fin_sq_ft, area_sqft, year_built, county, pin, emv,
  sale_code, 'est_value = county EMV; sale date grain = ' || grain
FROM cs2 QUALIFY row_number() OVER (PARTITION BY county, pin, sale_date, price) = 1""")
con.execute("CHECKPOINT")
counts(con)
