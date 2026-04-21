# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Pending.

## [0.1.0] - 2026-04-21

### Added

- Initial release of `rikdom` as a local-first portfolio schema and CLI toolkit.
- JSON schema and storage model for durable `portfolio.json` and append-only snapshot/event history.
- Plugin engine with first-party plugins for statement import, asset-type catalogs, report rendering, and storage sync.
- Multi-portfolio workspace support with portfolio registry and per-portfolio data isolation.

### Changed

- Snapshot generation now captures FX locks for deterministic historical valuation.

### Fixed

- Hardened CSV statement import and activity deduplication paths.
- Strengthened aggregation quality guardrails and merge validation behavior.

[Unreleased]: https://github.com/ricardocabral/rikdom/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/ricardocabral/rikdom/releases/tag/v0.1.0
