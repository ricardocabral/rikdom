# ghostfolio_export_json

Pluggy `source/input` plugin that imports holdings and activities from a Ghostfolio JSON export.

## Expected Input

JSON exported from Ghostfolio API/client containing one or both:

- activity-like rows (`activities`, `transactions`, or `orders`)
- holding-like rows (`holdings`, `positions`, or `assets`)

The importer accepts top-level arrays/objects and common nested envelopes (`data`, `result`, `export`).

## CLI Example

```bash
uv run rikdom import-statement \
  --plugin ghostfolio_export_json \
  --plugins-dir plugins \
  --input tests/fixtures/ghostfolio_export_sample.json \
  --portfolio tests/fixtures/portfolio.json
```
