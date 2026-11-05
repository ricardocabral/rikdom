# Local market series enrichment

This Experimental API 1.2 provider reads a local, explicitly supplied
MarketSeries 1.0 price/FX JSON file. It is free to run and requires no credentials
or network. It can replay a user-maintained file or an existing cache; it never
refreshes that cache. Real data licensing remains the user's responsibility.

From the repository root:

```bash
uv run rikdom enrichment --plugin local-market-series --plugins-dir plugins \
  --request '{"contract_version":"1.0","source":{"path":"plugins/local-market-series/fixtures/sample/input.json"},"lookups":[{"series_id":"br-price","as_of":"2026-01-02T00:00:00Z","max_age_seconds":0,"retrieved_before":"2026-01-02T00:00:00Z"}]}'
```

The synthetic sample selects value `10` at the cutoff. Omitting the cutoff
selects corrected value `12` and retains the original in `superseded`.
The command prints validated series and lookups without changing the file.

`source` accepts exactly `{"path":"..."}`. No URLs, provider fallbacks,
credentials or implicit paths are supported. An empty lookup list validates
and returns the complete series document. See the [normalized enrichment
contract](../../docs/reference/enrichment.md) for shapes and diagnostics.

Contract fixtures cover synthetic BRL/BVMF, USD/XNAS, JPY/XTKS and USD/JPY FX,
plus invalid JSON. These examples are not live coverage or calendar support.
No corporate actions, symbol recovery, automatic FX inversion, or holidays are
inferred. Every observation retains its source, retrieval date and revisions;
every series retains its coverage, adjustment convention and license.
