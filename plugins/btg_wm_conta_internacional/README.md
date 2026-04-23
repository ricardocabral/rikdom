# btg_wm_conta_internacional

Pluggy `source/input` plugin that imports holdings and activities from BTG WM "conta internacional" monthly statements.

## Expected input

- Primary: PDF monthly statement exported by BTG WM / DriveWealth
- Test/fixture mode: extracted `.txt` text (same `pdftotext -layout` format)

## Notes

- Requires `pdftotext` (Poppler) when input is PDF.
- Emits:
  - `holdings` from the `HOLDINGS` section
  - `activities` from both `ACTIVITY` and `SWEEP ACTIVITY` tables
- Uses USD as `base_currency` and validates parsed holdings sum against the statement `Ending Account Value`.

## CLI example

```bash
uv run rikdom import-statement \
  --plugin btg_wm_conta_internacional \
  --plugins-dir plugins \
  --input ~/Downloads/btg-wm-monthly-statement.pdf
```
