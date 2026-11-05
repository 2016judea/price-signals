"""Load salon menus: every listed service price, plus the repo's own benchmarks.

Reads ~/Desktop/workspace/salon-rates/pipeline/salon.db (sqlite) in place via DuckDB's sqlite scanner.
  service_listing (12,883)  -> price basis=list, one per listing; service detail (price_type, duration, tier)
  listing_map + canonical_service -> thing 'salon:<code>[:<size_mod>]' where the repo mapped it; else thing_id NULL
  benchmark (468)           -> price basis=benchmark + stat (n shops, p25/p75, geography)
  shop_price is NOT loaded: it is one listing per venue x code picked from service_listing (a derived duplicate).
"""
import os
from db import connect, replace_pull, add_pull, counts

SALON = os.path.expanduser(os.environ.get("SALON_DB", "~/Desktop/workspace/salon-rates/pipeline/salon.db"))
PULL_ID = os.environ.get("PULL_ID", "salon-2026-10-13")

con = connect()
replace_pull(con, PULL_ID)
con.execute("INSTALL sqlite; LOAD sqlite")
con.execute(f"ATTACH '{SALON}' AS s (TYPE sqlite, READ_ONLY)")
add_pull(con, PULL_ID, "salon-rates repo (Fresha, Booksy, Vagaro, GlossGenius menus)", "2026-10-13",
         "Twin Cities salons, barbers, nail and lash shops; snapshot 2026-10-13")

con.execute("""
INSERT OR REPLACE INTO party (party_id, kind, name, city, state, zip, lat, lon, url, note)
SELECT 'salon:' || business_id, 'business', name, city, 'MN', postal_code, lat, lng, url,
  concat_ws(' · ', business_type, CASE WHEN is_suite = 1 THEN 'suite' END, 'venue ' || venue_id)
FROM s.business""")

con.execute("""
CREATE TEMP TABLE sl AS
SELECT l.*, m.code, nullif(m.size_mod, '') AS size_mod, c.family, c.label AS code_label, p.tier
FROM s.service_listing l LEFT JOIN s.listing_map m USING (listing_id)
LEFT JOIN s.canonical_service c ON c.code = m.code LEFT JOIN s.provider p USING (provider_id)""")

con.execute("""
INSERT OR IGNORE INTO thing (thing_id, domain, code_system, code, label, category)
SELECT DISTINCT 'salon:' || code || coalesce(':' || size_mod, ''), 'salon_service', 'salon_code',
  code || coalesce(':' || size_mod, ''), code_label || coalesce(' (' || size_mod || ')', ''), family
FROM sl WHERE code IS NOT NULL AND code <> ''
UNION
SELECT DISTINCT 'salon:' || b.code || coalesce(':' || nullif(b.size_mod, ''), ''), 'salon_service', 'salon_code',
  b.code || coalesce(':' || nullif(b.size_mod, ''), ''), c.label || coalesce(' (' || nullif(b.size_mod, '') || ')', ''), c.family
FROM s.benchmark b LEFT JOIN s.canonical_service c USING (code)""")

con.execute(f"""
INSERT INTO price (price_id, pull_id, source, thing_id, title, seller_id, basis, amount, amount_high, unit, per,
  observed_on, city, state, zip, lat, lon, url)
SELECT 'salon:' || sl.listing_id || ':' || sl.snapshot_date, '{PULL_ID}', sl.source,
  CASE WHEN sl.code IS NOT NULL AND sl.code <> '' THEN 'salon:' || sl.code || coalesce(':' || sl.size_mod, '') END,
  concat_ws(' — ', sl.name_raw, nullif(sl.variant_raw, '')), 'salon:' || sl.business_id, 'list',
  sl.price_min, CASE WHEN sl.price_type = 'range' THEN sl.price_max END, 'usd', 'service',
  sl.snapshot_date::DATE, b.city, 'MN', b.postal_code, b.lat, b.lng, b.url
FROM sl LEFT JOIN s.business b USING (business_id)""")
con.execute(f"""
INSERT INTO service (price_id, price_type, duration_min, duration_max, provider_tier)
SELECT 'salon:' || listing_id || ':' || snapshot_date, price_type, duration_min, duration_max, tier FROM sl""")

con.execute(f"""
INSERT INTO price (price_id, pull_id, source, thing_id, title, basis, amount, unit, per, observed_on, state)
SELECT 'salonbm:' || md5(concat_ws('|', code, size_mod, geo_type, geo_key, tier, business_type, kind))[:16], '{PULL_ID}', 'salon-rates benchmark',
  'salon:' || code || coalesce(':' || nullif(size_mod, ''), ''), concat_ws(' · ', business_type, 'tier ' || tier, kind || ' prices'),
  'benchmark', median, 'usd', 'service', computed_at::DATE, 'MN'
FROM s.benchmark""")
con.execute("""
INSERT INTO stat (price_id, statistic, n, geography, p25, p75, note)
SELECT 'salonbm:' || md5(concat_ws('|', code, size_mod, geo_type, geo_key, tier, business_type, kind))[:16], 'median', n_shops,
  geo_type || ':' || geo_key, p25, p75, concat_ws('; ', kind || ' prices only', 'n_from=' || n_from, 'per_min_median=' || per_min_median)
FROM s.benchmark""")
con.execute("CHECKPOINT")
counts(con)
