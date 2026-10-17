-- prices.duckdb: what things cost and what is offered for sale. See DATA_MODEL.md.
-- Mirror of ~/Desktop/demand-signals (demand.duckdb).

-- provenance
CREATE TABLE IF NOT EXISTS pull (pull_id TEXT PRIMARY KEY, source TEXT, pulled_on DATE, note TEXT);

-- what is priced. thing_id is readable: cpt:97110, salon:balayage, pn:ABB:ACS850, pin:hennepin:2702924..., rdc:7257377895
CREATE TABLE IF NOT EXISTS thing (thing_id TEXT PRIMARY KEY,
  domain TEXT,        -- health_service | salon_service | part | goods | property | vehicle | commodity | cap_rate
  code_system TEXT,   -- CPT | HCPCS | salon_code | part_number | mn_pin | ks_pin | rdc_property | material | property_class
  code TEXT, label TEXT, category TEXT, maker TEXT, model TEXT);

-- who is on either side of a price
CREATE TABLE IF NOT EXISTS party (party_id TEXT PRIMARY KEY,
  kind TEXT,          -- provider | clinic | payer | business | dealer | person | agent | agency | county
  name TEXT, npi TEXT, tin TEXT, city TEXT, state TEXT, zip TEXT, lat DOUBLE, lon DOUBLE, url TEXT, note TEXT);

-- one dollar figure attached to one thing by someone on a date
CREATE TABLE IF NOT EXISTS price (price_id TEXT PRIMARY KEY, pull_id TEXT, source TEXT,
  thing_id TEXT,      -- NULL when the source gives no code (a Craigslist title, an unmapped salon service): see title
  title TEXT,         -- the source's own words for the thing
  seller_id TEXT, buyer_id TEXT,
  basis TEXT,         -- ask | bid | sold | paid | negotiated | list | benchmark | estimate
  amount DOUBLE, amount_high DOUBLE,   -- amount_high only when the source states a range
  unit TEXT,          -- usd | pct_of_billed | cap_rate_pct
  per TEXT,           -- service | unit | each | total | lb | gal | ton | year | visit
  qty DOUBLE, condition TEXT,          -- new | used | unknown
  observed_on DATE, valid_until DATE,
  city TEXT, state TEXT, zip TEXT, lat DOUBLE, lon DOUBLE, url TEXT);

-- basis = negotiated, payer Transparency-in-Coverage files
CREATE TABLE IF NOT EXISTS rate (price_id TEXT PRIMARY KEY, payer TEXT, network TEXT, billing_class TEXT,
  negotiated_type TEXT, modifiers TEXT[], place_of_service TEXT, tin TEXT, n_files INT);

-- domain = property
CREATE TABLE IF NOT EXISTS property (price_id TEXT PRIMARY KEY, property_type TEXT, beds DOUBLE, baths DOUBLE,
  sqft DOUBLE, lot_sqft DOUBLE, year_built INT, county TEXT, pin TEXT, list_price DOUBLE, est_value DOUBLE,
  days_on_market INT, sale_code TEXT, note TEXT);

-- domain = vehicle (cars and boats)
CREATE TABLE IF NOT EXISTS vehicle (price_id TEXT PRIMARY KEY, kind TEXT, year INT, make TEXT, model TEXT,
  mileage DOUBLE, engine_hours DOUBLE);

-- a priced service with a duration (salon menus)
CREATE TABLE IF NOT EXISTS service (price_id TEXT PRIMARY KEY, price_type TEXT, duration_min INT, duration_max INT,
  provider_tier TEXT);

-- basis = benchmark | paid when the figure summarises many observations
CREATE TABLE IF NOT EXISTS stat (price_id TEXT PRIMARY KEY, statistic TEXT, n DOUBLE, geography TEXT,
  p25 DOUBLE, p75 DOUBLE, note TEXT);

-- views ---------------------------------------------------------------------
-- every price with its thing and seller attached. Start here.
CREATE OR REPLACE VIEW price_full AS
SELECT p.*, t.domain, t.code_system, t.code, t.label, t.category, t.maker, t.model,
  s.name AS seller, s.kind AS seller_kind, b.name AS buyer
FROM price p LEFT JOIN thing t USING (thing_id)
LEFT JOIN party s ON s.party_id = p.seller_id LEFT JOIN party b ON b.party_id = p.buyer_id;

-- market rate per thing x basis, dollars only. Payer rates: base rate (no modifier) only,
-- one value per (payer, network, NPI, TIN) — modifiers 52/53/CO/CQ are reduced rates, not competitors.
CREATE OR REPLACE VIEW market_rate AS
SELECT t.domain, p.thing_id, t.label, p.basis, p.per, count(*) AS n,
  quantile_cont(p.amount, 0.25) AS p25, median(p.amount) AS median, quantile_cont(p.amount, 0.75) AS p75,
  min(p.amount) AS min, max(p.amount) AS max
FROM price p JOIN thing t USING (thing_id) LEFT JOIN rate r USING (price_id)
WHERE p.unit = 'usd' AND p.amount > 0
  AND t.code_system NOT IN ('craigslist_category', 'marketplace_segment')   -- buckets of unlike things, not a thing
  AND (r.price_id IS NULL OR (len(r.modifiers) = 0 AND r.negotiated_type = 'negotiated'))
GROUP BY ALL;

-- does the price of a thing vary enough to matter? (p75/p25)
CREATE OR REPLACE VIEW price_spread AS
SELECT *, round(p75 / nullif(p25, 0), 2) AS iqr_ratio FROM market_rate WHERE n >= 5;

-- the same thing priced both as an ask and as a sale (houses: realtor sold rows carry list_price)
CREATE OR REPLACE VIEW ask_vs_sold AS
SELECT p.price_id, p.thing_id, p.title, p.city, p.observed_on AS sold_on, x.list_price AS last_ask, p.amount AS sold,
  round(p.amount / nullif(x.list_price, 0), 3) AS sold_over_ask, x.property_type, x.beds, x.sqft
FROM price p JOIN property x USING (price_id)
WHERE p.basis = 'sold' AND x.list_price > 0;
