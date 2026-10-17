# price-signals

What things cost and what is offered for sale, in one DuckDB (`prices.duckdb`, gitignored, rebuildable).
The mirror of [demand-signals](https://github.com/2016judea/demand-signals), which holds what organizations say they need.

7.92M prices across MN payer-negotiated PT rates, Medicare allowed and charged amounts, Twin Cities salon menus,
home asks, MLS closes and county deeds, Craigslist and auction asks for parts, equipment and goods, private car and
boat asks, Kansas commercial sales and cap rates. One core: `thing` ← `price` → `party`, with `basis` saying what
kind of number each one is (ask, bid, sold, paid, negotiated, list, benchmark, estimate).

- Model and the field-by-field reality check: [DATA_MODEL.md](DATA_MODEL.md)
- `./build.sh` rebuilds everything (~30 s); each `load_*.py` reads one source repo in place and writes nothing there.
- Skill: `~/.claude/skills/price-signals`

Private on purpose: paid-product data and individual names are inside. Never deploy it.
