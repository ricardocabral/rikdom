# {{plugin_name}} enrichment provider

This scaffold implements Experimental API 1.2 `enrichment(ctx, request)` with a
working file-only MarketSeries provider, a synthetic fixture and a runtime test.
It requires Rikdom installed in the Python environment. The source/input
scaffold remains the default for `rikdom plugin init`.

Run from the generated plugin directory:

```bash
uv run python -m unittest discover -s tests -v
```

From the directory containing the generated plugin:

```bash
uv run rikdom enrichment --plugin {{plugin_name}} --plugins-dir . \
  --request '{"contract_version":"1.0","source":{"path":"{{plugin_name}}/fixtures/sample/input.json"},"lookups":[{"series_id":"br-price","as_of":"2026-01-02T00:00:00Z","max_age_seconds":0}]}'
```

The example selects corrected synthetic BRL value `12`; adding
`retrieved_before: "2026-01-02T00:00:00Z"` selects original value `10`.
The host validates returned series and derives queries. Keep the response
exactly `{"contract_version":"1.0","market_series":DOCUMENT}`. Providers cannot
return their own lookup values. The reference `source` accepts only `path`.

Extend `plugin.py` to read your reviewed local format and return the normalized
MarketSeries document. Preserve namespace/id/currency, source, effective and
retrieval time, revisions, license, adjustment and coverage metadata. Add
success/failure cases under `fixtures/<case>/`; `case.json` declares the hook
and request, with `source.path` relative to the case directory. `expected.json`
is the complete pipeline result, including host plugin identity and lookups.

The included data is CC0 synthetic test evidence. This scaffold provides no
live provider, market coverage, exchange calendar, network fallback, portfolio
mutation, corporate action processing, or data redistribution permission.
