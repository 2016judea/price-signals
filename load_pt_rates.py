"""Load physical-therapy prices: payer negotiated rates (TiC) and Medicare allowed/charged amounts.

Reads in place, writes nothing there:
  ~/Desktop/pt-rates-data/data/rates.duckdb       HealthPartners + UCare rates, nppes_providers (names for every NPI)
  ~/Desktop/pt-rates-data/data/rates_bcbs.duckdb  BCBS MN rates
  ~/Desktop/pt-rates/pipeline/cache/medicare_mn_pt_2024.json  CMS Physician & Other Practitioners, MN PTs, 2024

The source tables repeat one rate once per plan file (HealthPartners: 4.30M rows, 2.98M distinct
per network). A price row here is one distinct (payer, network, modifiers, code, negotiated_type,
billing_class, place_of_service, NPI, TIN, rate); rate.n_files keeps how many files repeated it.
Done in SQL via ATTACH: ~9.5M source rows never pass through pandas.
"""
import os
import pandas as pd
from db import connect, replace_pull, insert, add_pull, counts

PT = os.path.expanduser(os.environ.get("PT_RATES_DIR", "~/Desktop/pt-rates-data"))
MEDICARE = os.path.expanduser("~/Desktop/pt-rates/pipeline/cache/medicare_mn_pt_2024.json")
PULL_ID = os.environ.get("PULL_ID", "pt-rates-2026-10-04")
MC_PULL = os.environ.get("MC_PULL_ID", "medicare-pt-2024")

con = connect()
for p in (PULL_ID, MC_PULL):
    replace_pull(con, p)
con.execute(f"ATTACH '{PT}/data/rates.duckdb' AS hp (READ_ONLY)")
con.execute(f"ATTACH '{PT}/data/rates_bcbs.duckdb' AS bc (READ_ONLY)")
add_pull(con, PULL_ID, "pt-rates-data (payer Transparency-in-Coverage files)", "2026-10-04",
         "HealthPartners 2026-10-01 (19 networks), UCare 2026-09-16, BCBS MN 2026-07/08 (13 networks); 39 PT/E&M CPT codes; MN")

# parties: every NPI is in nppes_providers (2,190 of 2,190 checked 2026-10-17); payers
con.execute("""
INSERT OR REPLACE INTO party (party_id, kind, name, npi, city, state, zip, note)
SELECT 'npi:' || npi, CASE WHEN provider_type = 'Organization' THEN 'clinic' ELSE 'provider' END,
  provider_name, npi, city, state, left(zip, 5), taxonomy_desc
FROM hp.nppes_providers""")

con.execute("""
CREATE TEMP TABLE r AS
WITH src AS (
  SELECT * FROM hp.rates UNION ALL SELECT * FROM bc.rates
), tagged AS (
  SELECT payer_name, last_updated, billing_code, billing_code_type, negotiated_rate, negotiated_type, billing_class,
    place_of_service, npi, tin,
    nullif(regexp_extract(file_source, '#network=([^#]+)', 1), '') AS network,
    coalesce(nullif(regexp_extract(file_source, '#mod=([^#]+)', 1), ''), '') AS mods
  FROM src
)
SELECT payer_name, network, mods, billing_code, billing_code_type, negotiated_type, billing_class, place_of_service,
  npi, tin, negotiated_rate, max(last_updated) AS last_updated, count(*) AS n_files,
  md5(concat_ws('|', payer_name, network, mods, billing_code, negotiated_type, billing_class, place_of_service, npi, tin,
      negotiated_rate))[:16] AS price_id
FROM tagged GROUP BY ALL""")

con.execute("""
INSERT OR REPLACE INTO party (party_id, kind, name)
SELECT DISTINCT 'payer:' || payer_name, 'payer', payer_name FROM r""")
con.execute("""
INSERT OR IGNORE INTO party (party_id, kind, npi)
SELECT DISTINCT 'npi:' || npi, 'provider', npi FROM r""")
con.execute("""
INSERT OR IGNORE INTO thing (thing_id, domain, code_system, code)
SELECT DISTINCT lower(billing_code_type) || ':' || billing_code, 'health_service', billing_code_type, billing_code FROM r""")

con.execute(f"""
INSERT INTO price (price_id, pull_id, source, thing_id, seller_id, buyer_id, basis, amount, unit, per, observed_on, state)
SELECT price_id, '{PULL_ID}', 'tic:' || lower(replace(payer_name, ' ', '_')), lower(billing_code_type) || ':' || billing_code,
  'npi:' || npi, 'payer:' || payer_name, 'negotiated', negotiated_rate::DOUBLE,
  CASE WHEN negotiated_type = 'percentage' THEN 'pct_of_billed' ELSE 'usd' END, 'service', last_updated, 'MN'
FROM r""")
con.execute("""
INSERT INTO rate (price_id, payer, network, billing_class, negotiated_type, modifiers, place_of_service, tin, n_files)
SELECT price_id, payer_name, network, billing_class, negotiated_type,
  CASE WHEN mods = '' THEN []::TEXT[] ELSE string_split(mods, ',') END, place_of_service, tin, n_files
FROM r""")
con.execute("DROP TABLE r")

# Medicare 2024: per NPI x HCPCS, average allowed (what Medicare paid, incl. patient share) and average submitted charge
mc = pd.read_json(MEDICARE, dtype=False)
add_pull(con, MC_PULL, "CMS Medicare Physician & Other Practitioners by Provider and Service", "2026-10-13",
         "MN physical therapists, service year 2024; amounts are per-provider averages over Tot_Srvcs")
mc["npi"] = mc["Rndrng_NPI"].astype(str)
name = (mc["Rndrng_Prvdr_First_Name"].fillna("") + " " + mc["Rndrng_Prvdr_Last_Org_Name"].fillna("")).str.strip()
party = pd.DataFrame({"party_id": "npi:" + mc["npi"], "kind": mc["Rndrng_Prvdr_Ent_Cd"].map({"I": "provider", "O": "clinic"}),
                      "name": name, "npi": mc["npi"], "city": mc["Rndrng_Prvdr_City"], "state": mc["Rndrng_Prvdr_State_Abrvtn"],
                      "zip": mc["Rndrng_Prvdr_Zip5"], "note": mc["Rndrng_Prvdr_Type"]}).drop_duplicates("party_id")
con.register("mc_party", party)
con.execute("INSERT OR IGNORE INTO party SELECT party_id, kind, name, npi, NULL, city, state, zip, NULL, NULL, NULL, note FROM mc_party")
thing = pd.DataFrame({"thing_id": "cpt:" + mc["HCPCS_Cd"], "label": mc["HCPCS_Desc"]}).drop_duplicates("thing_id")
con.register("mc_thing", thing)
con.execute("INSERT OR IGNORE INTO thing (thing_id, domain, code_system, code) SELECT thing_id, 'health_service', 'CPT', substr(thing_id, 5) FROM mc_thing")
con.execute("UPDATE thing SET label = mc_thing.label FROM mc_thing WHERE thing.thing_id = mc_thing.thing_id")
con.execute("INSERT OR IGNORE INTO party (party_id, kind, name) VALUES ('payer:Medicare', 'payer', 'Medicare')")

rows, stats = [], []
for basis, col, statname in [("paid", "Avg_Mdcr_Alowd_Amt", "mean_allowed"), ("list", "Avg_Sbmtd_Chrg", "mean_submitted_charge")]:
    pid = [f"mc{basis}:{a}:{b}:{c}" for a, b, c in zip(mc["npi"], mc["HCPCS_Cd"], mc["Place_Of_Srvc"])]
    rows.append(pd.DataFrame({"price_id": pid, "pull_id": MC_PULL, "source": "medicare_puf", "thing_id": "cpt:" + mc["HCPCS_Cd"],
        "seller_id": "npi:" + mc["npi"], "buyer_id": "payer:Medicare" if basis == "paid" else None, "basis": basis,
        "amount": pd.to_numeric(mc[col], errors="coerce"), "unit": "usd", "per": "service",
        "observed_on": pd.Timestamp("2024-12-31").date(), "city": mc["Rndrng_Prvdr_City"], "state": mc["Rndrng_Prvdr_State_Abrvtn"],
        "zip": mc["Rndrng_Prvdr_Zip5"]}))
    stats.append(pd.DataFrame({"price_id": pid, "statistic": statname, "n": pd.to_numeric(mc["Tot_Srvcs"], errors="coerce"),
                               "geography": "provider", "note": "place of service " + mc["Place_Of_Srvc"]}))
price = pd.concat(rows).drop_duplicates("price_id")
stat = pd.concat(stats).drop_duplicates("price_id")
insert(con, "price", price)
insert(con, "stat", stat)
con.execute("CHECKPOINT")
counts(con)
