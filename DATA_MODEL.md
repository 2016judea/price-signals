# Data model: `prices.duckdb`

**What things cost, and what is offered for sale.** The mirror of
[`demand-signals`](https://github.com/2016judea/demand-signals) (what organizations say
they NEED). A payer's negotiated rate for a PT visit, a salon's price for a balayage, a
house's asking price, a used lathe on Craigslist and a county-recorded sale are the
same shape of fact: **someone, on a date, attached a dollar figure to a thing.** What
differs is the *basis* of the figure (asked, sold, contracted, published, summarised),
and that is a column, not a separate database.

## Section 1 — the ideal model (written from the need, before reading any source)

The questions a person brings: *What does X cost here? What is the market rate? What did
it actually sell for, versus what was asked? Who charges the most and least? Is this
price high for this thing?* Every field below answers one of them.

```
pull ──< price >── thing   (what: code_system + code, label, maker, model, domain)
           │  └──── party   seller  (who sets / receives the price: provider, business, person, dealer, agency)
           │  └──── party   buyer   (who pays, when the price is bilateral: payer, buyer of record)
           ├── rate      (basis = negotiated: payer, plan, billing class, negotiated type, modifiers)
           ├── property  (domain = property: beds, baths, sqft, year built, est value, days on market)
           ├── vehicle   (domain = vehicle: year, make, model, mileage)
           └── stat      (basis = benchmark: statistic, n, geography the figure summarises)
```

| Table | Field | Question it answers |
|---|---|---|
| `pull` | pull_id, source, pulled_on, note | Where and when did these rows come from? Re-run a pull = replace; new pull = append. |
| `thing` | domain | Which market is this (health service, salon service, part, property, vehicle, goods)? |
| | code_system, code | Is this the *same* thing as another row? (CPT/HCPCS, salon service code, maker+part number, parcel id, VIN) — the join key for every comparison. |
| | label, category | What is it, in words, and what family does it roll up to? |
| | maker, model | Who made it (parts, vehicles)? |
| `party` | kind | Who is on this side: provider, business, person, dealer, agency, payer? |
| | name, ids (npi, tin, ein) | Which one, and can I join it to another dataset? |
| | city, state, zip, lat, lon | Where are they — local market comparisons. |
| | url | Where can I see or reach them? |
| `price` | thing_id, seller_id, buyer_id | What, from whom, paid by whom. |
| | basis | What *kind* of number: `ask` (offered), `sold` (closed), `negotiated` (payer contract), `list` (published menu/fee schedule), `benchmark` (a statistic over many), `estimate` (a model's value). The single most important column: an ask is not a sale. |
| | price_usd, price_low, price_high | The figure; a range when the source states one ("from $45", "$80–120"). |
| | unit, qty | Per what: per service, per visit, per unit, each, total, per sqft, per year. |
| | condition | New, used, refurbished — parts and goods. |
| | observed_on | When was this price true (listing date, sale date, file date)? |
| | valid_until | When does it stop being true (contract expiry)? |
| | city, state, zip, lat, lon | Where the thing is priced, when it differs from the seller (a house). |
| | url | Show me the original. |
| `rate` | payer, plan, billing_class, negotiated_type, modifiers, place_of_service | Which contract, professional vs institutional, $ vs % vs per diem, which modifier. |
| `property` | beds, baths, sqft, lot_sqft, year_built, property_type, est_value, list_price, days_on_market | Is this ask high for what it is? How far below ask did it close? |
| `vehicle` | year, make, model, mileage | Same question for a car or boat. |
| `stat` | statistic (median/p25/p75/mean), n, geography | How many observations stand behind a benchmark, over what area? |

Views wanted: `market_rate` (median/p25/p75 per thing × basis × place), `ask_vs_sold`
(same thing, both bases), `price_spread` (does this thing's price vary enough to matter).

## Section 2 — reality check, field by field (2026-10-17, counts from `prices.duckdb`)

7.92M price rows. By basis: negotiated 7,583,098 · ask 160,724 · sold 127,669 · list 19,464 ·
estimate 14,462 · paid 6,910 · benchmark 4,032 · bid 1,644.

| Field | Filled? | Reality |
|---|---|---|
| `thing.code` | **Partly** | Exact codes for CPT (100%), MN/KS parcel PIN (county sales 100%, Realtor asks 99% via index.csv), salon code (4,936 of 12,883 listings = 38%; the rest are the shop's own words in `title`, `thing_id` NULL). Parts: 28,141 maker+PN groups from Legacy, but a Craigslist-only group's "PN" is regex-pulled from the title and often junk (`SAMSUNG 50`). 108k Craigslist + 362 Facebook asks have **no code at all**: they sit under a category bucket (`cl:<cat>`, `fb:<segment>`) that `market_rate` excludes. |
| `thing` sameness across sources | **Partly** | Realtor *closed* rows carry no PIN (only `rdc:` ids), so a home's MLS close and its county deed do not join. 1,215 homes have both an ask and a county sale. |
| `party` seller identity | **Partly** | Named: every payer-rate NPI (5,337 from NPPES), every salon, listing agents, Facebook profiles. **Unfillable**: Craigslist and auction sellers (148k rows point at `anon:dealer` / `anon:person` / `anon:agency`, kind only); county deeds name no seller or buyer in the files we hold. The homeowner behind an ask is never named; the agent is. |
| `party` buyer | Payer rates and Medicare (buyer = payer), agency paid prices. Everywhere else the buyer is not in the source. |
| `basis` | **Filled 100%.** | |
| `amount_high` | 209 rows | Only salon `range` prices state one. 4,725 salon prices are "from $X" floors (`service.price_type='from'`), stored as `amount` = the floor. |
| `unit` / `per` | Filled | Non-dollar: UCare/BCBS `percentage` rates (`pct_of_billed`, 210k) and Johnson County cap rates (`cap_rate_pct`). |
| `condition` | **431 rows** | Only presale/Facebook state it. Craigslist and dealer listings: unfillable without reading each post. |
| `observed_on` | 100% (1 null) | Hennepin deed dates are month grain (`property.note`); Medicare is the service year (2024-12-31). |
| `valid_until` | **0** | TiC files carry no contract expiry; nothing else has one. |
| location | 168k rows with lat/lon; state on all MN sources | Craigslist location is the metro slug only (`city`), no state. |
| `rate.*` | Filled | network + modifiers recovered from the `#network=` / `#mod=` tags the pt-rates ingester put on `file_source`. |
| `property.list_price` on a sale | 28,577 of 48,839 Realtor closes | On 20,262 rows Realtor's `list_price` equals the sold price (the last ask was overwritten), so it is NULL with a note. |
| `property.est_value` | 92,550 | County EMV on deeds; the index's `worth` on asks. |
| `vehicle.*` | 450 rows | Only presale-detail. The 31k Craigslist vehicle asks have year/make/mileage only inside `title`. |
| `stat` | Filled where basis=benchmark/paid | Salon benchmarks (n shops, p25/p75), Medicare (n services), cap rates. |

**Call: build, not reframe.** The fields that fail (seller names on anonymous marketplaces,
condition, contract expiry, a code for free-text goods) fail in the sources, not in the model;
every domain still answers "what does X cost, on what basis, from whom" where a code exists.
The uncoded goods are kept, labelled as uncoded, rather than dropped or forced into a fake code.

**Left out, on purpose:**
- `mn-next-ask` (foundation grants given): a grant is a gift with no thing exchanged and no
  market to compare against. It is not a price. Neither model fits it well; if anything it is
  demand-side context (what a funder will give), so it stays in its own repo.
- `bricks/data/sector_benchmarks.json`: hand-typed cost-structure ratios stored as strings
  ("32–36%"), not price points.
- `salon.db shop_price`: one listing per venue × code picked from `service_listing` (a derived duplicate).
- arbitrage `counterparty` (2 of 6,801 rows carry a price) and 10 `illustrative` market prices (placeholders).
- Craigslist `wan` (wanted) rows: demand, not supply.

## Tables

| Table | Grain |
|---|---|
| `pull` | one load run. Same `PULL_ID` replaces, new one appends. |
| `thing` | one priceable thing (or one category bucket for uncoded goods) |
| `party` | one seller / buyer / payer / agent |
| `price` | one dollar figure (or rate %) on one thing, on one basis, on one date |
| `rate` | detail for payer-negotiated prices (payer, network, class, type, modifiers, POS, TIN, n_files) |
| `property` | detail for homes and commercial buildings |
| `vehicle` | detail for cars and boats |
| `service` | salon menu detail (price_type, duration, provider tier) |
| `stat` | n / p25 / p75 / geography behind a benchmark or average |

## Views
- `price_full` — price with thing, seller and buyer names. Start here.
- `market_rate` — n / p25 / median / p75 per thing × basis, dollars only; payer rates base-only (no modifier, `negotiated` type).
- `price_spread` — `market_rate` with n ≥ 5 and p75/p25.
- `ask_vs_sold` — Realtor closes with a known last ask (median sold/ask 0.994, p10 0.948, p90 1.056).

## Loaders

| Script | Source (read in place) | Pull id |
|---|---|---|
| `load_pt_rates.py` | `~/Desktop/pt-rates-data/data/rates*.duckdb` (ATTACH, SQL only), `~/Desktop/pt-rates/pipeline/cache/medicare_mn_pt_2024.json` | `pt-rates-2026-10-04`, `medicare-pt-2024` |
| `load_salon.py` | `~/Desktop/salon-rates/pipeline/salon.db` (sqlite scanner) | `salon-2026-10-13` |
| `load_houses.py` | `~/Desktop/msp-house-index/data` (listings_raw, sold_raw, index.csv, county.duckdb) | `msp-house-2026-10-12`, `mn-county-sales-2026-10-11` |
| `load_parts.py` | `~/Desktop/the-google-of-obsolete-infrastructure-parts/data/supply`, `worth_items.json` | `legacy-supply-2026-10-01` |
| `load_marketplace.py` | `~/Desktop/presale-detail/data/listings.json`, `~/Desktop/on-the-house/drafts/fb-marketplace/listings_2026-10-10.json` | `marketplace-2026-10-10` |
| `load_bricks.py` | `~/Desktop/bricks/data` (Sedgwick sales, Johnson cap rates, arbitrage market_price) | `bricks-data-2026-10-17` |

## Rules that keep it honest
- **An ask is not a sale.** Never median across bases. Twin Cities homes close at 0.994× the last ask (median), so a records gap is not a discount.
- **Payer rates: base rows only, per payer.** Modifier rows (52/53 reduced, CO/CQ assistant at 85%) are not competitors. Payers differ by ~3× on the same code (97110: HealthPartners median $25.08, BCBS MN $73.90), so a pooled "negotiated" median is a mix, not a market.
- **`from` salon prices are floors.** Filter `service.price_type='fixed'` for a like-for-like median.
- **Cross-posted Craigslist ads were collapsed at load** (same title + price = one price; 49,087 dropped).
- **Private.** Paid-product data (PT rates, the house index, Legacy supply) and individual names (agents, therapists, sellers) are inside. The DB is gitignored and is never deployed. The Kansas files are not cleared for republication.
