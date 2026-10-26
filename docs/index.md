# Rikdom Documentation

Documentation is organized along the [Diataxis](https://diataxis.fr/) framework.
Pick the section that matches what you are trying to do right now.

## [Tutorials](tutorials/) — learn by doing

Hands-on lessons for newcomers. Start here.

- [Your first portfolio](tutorials/first-portfolio.md) — validate, snapshot, visualize.
- [Author your first plugin](tutorials/first-plugin.md) — scaffold a `source/input` plugin end-to-end.

## [How-to guides](how-to/) — solve a specific problem

Goal-oriented recipes for users who already know the basics.

- [Import a broker statement](how-to/import-a-statement.md)
- [Enter and correct activities](how-to/enter-and-correct-activities.md)
- [Query external data through a connector](how-to/query-external-data.md)
- [Render a portfolio report](how-to/render-a-report.md)
- [Run a schema migration](how-to/run-a-migration.md)
- [Author a new migration](how-to/author-a-migration.md)
- [Back up before a migration](how-to/back-up-before-migration.md)
- [Compute portfolio TWR / MWR](how-to/compute-performance.md)
- [Work with multi-currency holdings](how-to/work-with-multi-currency.md)
- [Recover from a crash or torn write](how-to/recover-from-crash.md)

## [Reference](reference/) — facts and contracts

Information-oriented descriptions of the machinery.

- [CLI commands](reference/cli.md)
- [Schemas](reference/schemas.md) — portfolio, snapshot, plugin-statement
- [Storage layout](reference/storage-layout.md)
- [Plugin manifest fields](reference/plugin-manifest.md)
- [Plugin hooks](reference/plugin-hooks.md)
- [Bundled plugin catalog](../plugins/README.md) — importers, connectors, reports, and storage.
- [Migration version history](reference/migrations.md)
- [Reconciliation issue codes](reference/reconciliation-codes.md)
- [Import diagnostics and identity recovery](reference/import-diagnostics.md)
- [Performance output](reference/performance-output.md)
- [FX snapshot fields](reference/fx-snapshot-fields.md)
- [Export bundle format](reference/export-format.md)

## [Explanation](explanation/) — understand the why

Background, design decisions, and trade-offs.

- [Schema design](explanation/schema-design.md)
- [Plugin architecture](explanation/plugin-architecture.md) — lifecycle, external data connectors, and REST/MCP boundaries.
- [Plugin compatibility & stability](explanation/plugin-compatibility.md)
- [Calculation trust & reconciliation](explanation/calculation-trust.md)
- [Storage durability](explanation/storage-durability.md)
- [Multi-currency engine](explanation/multi-currency-engine.md)
- [Performance methodology](explanation/performance-methodology.md)
