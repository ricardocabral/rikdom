#!/usr/bin/env bash
set -euo pipefail

# Charles Schwab plugin E2E runner
# - Uses an isolated temporary portfolio workspace
# - Never touches repo ./data
# - Runs import twice to verify idempotency

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PLUGIN_DIR="$ROOT_DIR/plugins/charles-schwab"
INPUT_CSV="${1:-$PLUGIN_DIR/fixtures/taxable-mixed/input.csv}"
KEEP_WORKDIR="${KEEP_E2E_DIR:-0}"

if [[ ! -f "$INPUT_CSV" ]]; then
  echo "Input file not found: $INPUT_CSV" >&2
  echo "Usage: $0 [input.csv]" >&2
  exit 1
fi

E2E_DIR="$(mktemp -d /tmp/rikdom-e2e-schwab-XXXXXX)"
cleanup() {
  local exit_code=$?
  if [[ "$KEEP_WORKDIR" == "1" ]]; then
    echo "E2E artifacts kept at: $E2E_DIR"
  else
    rm -rf "$E2E_DIR"
    if [[ $exit_code -eq 0 ]]; then
      echo "E2E artifacts removed (set KEEP_E2E_DIR=1 to keep them)."
    else
      echo "E2E failed; E2E artifacts removed (set KEEP_E2E_DIR=1 to keep them)." >&2
    fi
  fi
  return "$exit_code"
}
trap cleanup EXIT

cp "$ROOT_DIR/tests/e2e-data/charles-schwab/portfolio.json" "$E2E_DIR/portfolio.json"
cp "$ROOT_DIR/tests/e2e-data/charles-schwab/import_log.jsonl" "$E2E_DIR/import_log.jsonl"

echo "E2E workspace: $E2E_DIR"
echo "Input: $INPUT_CSV"

echo "== Run 1 (write) =="
PYTHONPATH="$ROOT_DIR/src" uv run rikdom import-statement \
  --plugin charles-schwab \
  --plugins-dir "$ROOT_DIR/plugins" \
  --input "$INPUT_CSV" \
  --portfolio "$E2E_DIR/portfolio.json" \
  --import-log "$E2E_DIR/import_log.jsonl" \
  --write > "$E2E_DIR/run1.json"

python - <<'PY' "$E2E_DIR/run1.json"
import json,sys
p=json.load(open(sys.argv[1]))
print(json.dumps({
  'holdings': p['holdings'],
  'activities': p['activities'],
  'preflight_ok': p['preflight']['ok'],
  'issues_total': p['preflight']['summary']['issues_total'],
}, indent=2))
PY

echo "== Run 2 (write, idempotency) =="
PYTHONPATH="$ROOT_DIR/src" uv run rikdom import-statement \
  --plugin charles-schwab \
  --plugins-dir "$ROOT_DIR/plugins" \
  --input "$INPUT_CSV" \
  --portfolio "$E2E_DIR/portfolio.json" \
  --import-log "$E2E_DIR/import_log.jsonl" \
  --write > "$E2E_DIR/run2.json"

python - <<'PY' "$E2E_DIR/run2.json"
import json
import sys

p = json.load(open(sys.argv[1]))
dry_run_diff = p.get('dry_run_diff')
dry_run_summary = dry_run_diff.get('summary') if isinstance(dry_run_diff, dict) else None
summary = {
  'holdings': p['holdings'],
  'activities': p['activities'],
  'preflight_ok': p['preflight']['ok'],
  'issues_total': p['preflight']['summary']['issues_total'],
  'blocking_issues': p['preflight']['summary']['blocking_issues'],
  'dry_run_diff': dry_run_summary,
}
print(json.dumps(summary, indent=2))


def counter_value(counter, key):
  return counter.get(key, 0) if isinstance(counter, dict) else None


def has_mutations(diff_summary):
  if not isinstance(diff_summary, dict):
    return bool(diff_summary)
  for section in diff_summary.values():
    if isinstance(section, dict):
      for key, value in section.items():
        if key in ("create", "update", "inserted", "updated") and value != 0:
          return True
  return False


errors = []
if counter_value(summary['holdings'], 'inserted') != 0 or counter_value(summary['holdings'], 'updated') != 0:
  errors.append(f"expected run 2 holdings inserted/updated to be 0, got {summary['holdings']}")
if counter_value(summary['activities'], 'inserted') != 0 or counter_value(summary['activities'], 'updated') != 0:
  errors.append(f"expected run 2 activities inserted/updated to be 0, got {summary['activities']}")
if summary['blocking_issues'] != 0:
  errors.append(f"expected run 2 blocking_issues=0, got {summary['blocking_issues']}")
if not isinstance(summary['dry_run_diff'], dict):
  errors.append("expected run 2 dry_run_diff.summary to exist and be an object")
elif has_mutations(summary['dry_run_diff']):
  errors.append(f"expected run 2 dry_run_diff summary to have no create/update mutations, got {summary['dry_run_diff']!r}")

if errors:
  print("Idempotency check failed:", file=sys.stderr)
  for err in errors:
    print(f"- {err}", file=sys.stderr)
  sys.exit(1)
PY

echo "== Validate resulting portfolio =="
PYTHONPATH="$ROOT_DIR/src" uv run rikdom validate --portfolio "$E2E_DIR/portfolio.json"

echo "== Final portfolio counts =="
python - <<'PY' "$E2E_DIR/portfolio.json" "$E2E_DIR/import_log.jsonl"
import json,sys
portfolio=json.load(open(sys.argv[1]))
with open(sys.argv[2], 'r', encoding='utf-8') as f:
    lines=[ln for ln in f.read().splitlines() if ln.strip()]
print(json.dumps({
  'holdings_total': len(portfolio.get('holdings',[])),
  'activities_total': len(portfolio.get('activities',[])),
  'import_log_rows': len(lines),
}, indent=2))
PY

