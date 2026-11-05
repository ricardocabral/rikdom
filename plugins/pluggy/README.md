# MeuPluggy portfolio connector and importer

Read your own MeuPluggy (Brazil) connections into a saved JSON acquisition, then preview
and explicitly import investments, bank cash balances and available investment
movements. Acquisition makes no portfolio changes. The plugin uses Python's
standard library and requires no additional dependencies.

## Connect your banks and save an acquisition

Run commands from the repository root after the usual `uv sync` setup.

1. Follow Pluggy's [personal-use guide](https://docs.pluggy.ai/en/docs/guides/meu-pluggy-personal-use).
   Connect and authorize each bank at [Meu Pluggy](https://meu.pluggy.ai).
   Sign in to the [Pluggy Dashboard](https://dashboard.pluggy.ai) with the same
   account. In Applications → your application → Demo → Connect Account,
   select **MeuPluggy** and sign in. If using custom connector selection, enable
   MeuPluggy under Customization → Connectors → Direct Connectors → Personal.
   Selecting a bank directly or selecting Sandbox does not connect your personal
   Meu Pluggy data.
2. In Demo → Connected Items, copy and retain each bank's item ID. Supply these
   explicitly on every fetch: `GET /v2/items` is unavailable for Meu Pluggy
   accounts. Copy your application's Client ID and generate/store its Client
   Secret (shown once).
3. Export `PLUGGY_CLIENT_ID` and `PLUGGY_CLIENT_SECRET`, or put them in a private
   `.env` file using the following names and your own values:

   ```dotenv
   PLUGGY_CLIENT_ID=replace-with-your-client-id
   PLUGGY_CLIENT_SECRET=replace-with-your-client-secret
   ```

   The plugin reads `.env` only when `env_file` is explicitly supplied. Exported
   environment variables take precedence. It does not automatically load files;
   its simple credentials reader supports assignments and quoted values, without
   shell interpolation. Keep credentials and acquisitions out of version control.
4. Inspect capabilities without authentication:

   ```bash
   uv run rikdom connector describe --plugin pluggy
   ```

5. Replace the example UUID with a copied item ID; include additional bank IDs in
   the array as needed. Save the full provider-native acquisition envelope:

   ```bash
   mkdir -p data/pluggy
   umask 077
   uv run rikdom connector query --plugin pluggy --operation portfolio \
     --params '{"item_ids":["11111111-1111-4111-8111-111111111111"],"env_file":".env"}' \
     > data/pluggy/acquisition-2026-11-05.json
   ```

   Use a new filename for each acquisition. Check that the command succeeds
   before importing; a failed command can leave an empty redirected file. The
   CLI writes JSON to stdout and has no `--output` flag. When using exported
   credentials, omit `env_file`.

The only operation is `portfolio`. Its required `item_ids` parameter is a
nonempty array of UUID strings. Optional `include_transactions` and
`include_bank_accounts` booleans both default to `true`. Setting either to
`false` excludes that product from the acquisition. The plugin fetches selected
items, paginated BANK accounts, investments and investment transactions. It
does not fetch bank spending, credit cards or loans, make payments, force a
synchronization, or automate bank authorization.

## Preview and import a saved acquisition

For a portfolio with existing holdings, first prepare reviewed mappings as
described below. For a new portfolio, preview the saved envelope directly:

```bash
uv run rikdom import-statement --plugin pluggy \
  --input data/pluggy/acquisition-2026-11-05.json --dry-run
```

This targets the default workspace portfolio; use `--portfolio path/to/portfolio.json`
to select a different file. Review the holdings, activities, history coverage
and unsupported-event diagnostics. Once the preview matches your intended
changes, run the same input against the same portfolio with `--write --reconcile`:

```bash
uv run rikdom import-statement --plugin pluggy \
  --input data/pluggy/acquisition-2026-11-05.json --write --reconcile
```

The explicit write updates the portfolio and import log. Reconciliation emits
trust artifacts; see [import a statement](../../docs/how-to/import-a-statement.md).
Replaying a saved acquisition requires no credentials or network access.

## Map existing holdings and review overlaps

Input accepts a raw `pluggy-portfolio-v1` snapshot, the complete connector
envelope, or a descriptor pointing to either. For example, save the following as
`data/pluggy/import.json`, replacing all source and destination IDs with reviewed
values. The snapshot path resolves relative to this descriptor:

```json
{
  "snapshot": "acquisition-2026-11-05.json",
  "mappings": {
    "items": {
      "11111111-1111-4111-8111-111111111111": {"account_id": "broker-a"}
    },
    "investments": {
      "22222222-2222-4222-8222-222222222222": {
        "holding_id": "existing-position",
        "account_id": "broker-a",
        "asset_type_id": "stock",
        "canonical_key": "reviewed-instrument-key"
      },
      "overlapping-investment-id": {"skip": true}
    },
    "accounts": {
      "33333333-3333-4333-8333-333333333333": {
        "holding_id": "existing-cash",
        "account_id": "broker-a"
      }
    },
    "transactions": {
      "reviewed-distribution-id": {"event_type": "dividend"},
      "overlapping-transaction-id": {"skip": true}
    }
  }
}
```

Use `--input data/pluggy/import.json` for both preview and write. Mapping groups
are optional. `items` sets an account default; `investments` and `accounts` may
override `holding_id`, `account_id`, `asset_type_id`, `canonical_key`, or `skip`.
Transaction mappings accept `skip` and an `event_type` of `income`, `interest`,
or `dividend`; classification overrides apply only to provider `INTEREST` rows.
Destination asset-type IDs must exist in the portfolio or available catalogs.
Account IDs should name existing policy accounts; check them with
`rikdom validate --portfolio path/to/portfolio.json --policy path/to/policy.json`.
These mappings do not create policy accounts.

Default holding IDs are `pluggy:investment:<investment-id>` and
`pluggy:account:<account-id>`. Activity IDs and idempotency keys are
`pluggy:transaction:<transaction-id>`. They deliberately omit the item ID, so
renewing an item does not duplicate unchanged provider record IDs. If renewal
also changes investment/account IDs, review and update the mappings before
writing. Identical repeated snapshots are idempotent.

Match existing holdings explicitly after reviewing account and instrument
identity; ticker similarity is insufficient. Multiple items representing the
same economic asset are not automatically deduplicated. Mapping distinct
source positions onto one holding is rejected: select the authoritative source
and skip overlapping positions or transactions. Prefer direct `holding_id`
mappings for ledger imports: core `--collapse-canonical` merges holding slots
without remapping activity holding references.

## Valuations, movements and coverage

The plugin retains provider rows under `metadata.pluggy` and uses its own
`pluggy_*` asset types: stock/BDR, FII, fund/ETF, fixed income, cash, retirement,
structured note and unclassified investment. Retirement and structured-note
underlying exposures remain unclassified. A reviewed mapping can select a more
appropriate existing asset type.

- Investment `amount` supplies gross `market_value`; `balance` is retained as
  `valuation.net_value`, and `value` as unit price. Position tax provisions stay
  provisions. Missing gross value never promotes net balance into gross value.
- BANK balances become cash positions. Automatically invested or reserved
  balance details remain provider metadata and do not create extra positions.
- Pending positions and contradictory nonzero `TOTAL_WITHDRAWAL` positions
  are excluded with diagnostics. A consistent explicit total withdrawal can
  establish a zero position; disappearance from a response cannot close one.
  For missing gross values or contradictory closed positions, valid movements
  can survive without a holding reference, preserving instrument/source evidence;
  an explicit reviewed `holding_id` can link them to an existing holding.
- `BUY`, `SELL`, `TAX`, directional `TRANSFER` and `AMORTIZATION` map to their
  canonical movement types. Tax movements are positive canonical costs.
  Provider `date` supplies the effective time; its documented settlement field
  `tradeDate` supplies `settled_at`. Unknown, missing-ID or unexpected-direction
  movements remain diagnostics rather than fabricated events.
- Provider `INTEREST` includes dividends, FII distributions, JCP and coupons;
  it becomes generic gross `income` unless a reviewed transaction mapping
  establishes `dividend` or `interest`. Reported fees and withheld taxes remain
  separate. Under the documented Open Finance convention, `incomeTax` contains
  IRRF and `other` contains other taxes; `iof` is also a tax. `iofProvision`
  is not a paid tax. Raw expenses remain available for review.

These interpretations follow Pluggy's [investment](https://docs.pluggy.ai/en/docs/products/investment)
and [investment transaction](https://docs.pluggy.ai/en/docs/products/investment-transactions)
contracts. Available investment history is marked **partial**, never complete
from inception. It does not establish complete tax records, cost basis or XIRR
coverage. Excluding transactions leaves history coverage unknown.

## Refresh and failure handling

Meu Pluggy mirrors refresh about every 24 hours; the plugin cannot request a
manual update. The application's MeuPluggy authorization lasts one year and
is separate from each bank's consent. Expiry can produce empty product lists;
renew in Meu Pluggy/the Dashboard rather than importing emptiness as a closure.
See the [personal-use guide](https://docs.pluggy.ai/en/docs/guides/meu-pluggy-personal-use)
for renewal steps.

Acquisition fails closed for expired authorization, item errors, required user
action or incomplete requested products. Endpoint or pagination failure aborts
the entire fetch. Offline replay checks item health and consent against the
saved `fetched_at`, making historical replays reproducible rather than judging
old authorization against today's date.

Authentication success alone does not establish access to bank data. In checks
on 2026-11-05, the supplied application credentials authenticated successfully
while item enumeration returned HTTP 403. An official Sandbox `portfolio`
acquisition returned one bank account, eight investments and fourteen investment
transactions. Importing twice into an isolated test portfolio produced eight
holdings and fourteen activities with zero inserts or updates on the second run;
a contradictory nonzero closed position remained a diagnostic. A second,
user-supplied Open Finance Sandbox item reported `PARTIAL_SUCCESS`, investment
collection `isUpdated: false`, and an account warning; acquisition rejected it.
These checks do not establish production coverage for any particular bank.
