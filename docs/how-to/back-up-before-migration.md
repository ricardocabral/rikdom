# Back up before a migration

Migrations rewrite long-lived JSON state in place. Rikdom's automatic backup
keeps you one `mv` away from the previous file. This guide covers the rules
and how to roll back.

## Automatic sibling backup

Before overwriting a portfolio in place, `migrate` writes a sibling backup
named `<portfolio>.bak-YYYYMMDDTHHMMSSZ` (UTC). The same applies to
`migrate-policy`.

To roll back, replace the file with the backup:

```bash
mv data/portfolio.json.bak-20260420T153000Z data/portfolio.json
```

## When backups are skipped

Backups are skipped when:

- `--no-backup` is passed (use only when the file is under version control), or
- `--output <path>` is passed (the source file is not modified).

## Belt-and-braces: version control

On top of automatic backups, keep portfolio and policy files under version
control (git) so every migration lands as an auditable commit. A
`git checkout -- data/portfolio.json` then becomes an additional rollback path.

## See also

- [Run a schema migration](run-a-migration.md)
- [Migration version history reference](../reference/migrations.md)
