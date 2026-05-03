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
control (git) so every migration lands as an auditable commit with a diff you
can review before it leaves your machine.

### One-time setup

If your portfolio lives outside an existing repo, initialise one alongside it:

```bash
cd data
git init
git add portfolio.json policy.json
git commit -m "Initial portfolio and policy snapshot"
```

Add an ignore rule for the sibling backups so they don't pollute history (the
JSON files themselves are the record of truth; the `.bak-*` files are just a
short-lived safety net):

```bash
echo '*.bak-*' >> .gitignore
git add .gitignore
git commit -m "Ignore migration sibling backups"
```

### Migration workflow with git

1. **Start clean.** Run `git status` and confirm there are no unstaged
   changes to `portfolio.json` or `policy.json`. A migration on top of a
   dirty working tree mixes hand edits with schema rewrites in the same
   diff.
2. **Run the migration.** For example:

   ```bash
   uv run rikdom migrate --portfolio data/portfolio.json
   ```

3. **Review the diff.** Inspect exactly what the migration changed before
   committing:

   ```bash
   git diff -- data/portfolio.json
   ```

   For large rewrites, `git diff --stat` gives a per-file summary first.
4. **Commit the result.** Reference the schema version in the message so
   the history doubles as a migration log:

   ```bash
   git add data/portfolio.json
   git commit -m "migrate portfolio.json to schema vX.Y"
   ```

### Rolling back with git

If something looks wrong after a migration, you have two git-based options
in addition to the sibling `.bak-*` file:

- **Discard uncommitted changes** (migration not yet committed):

  ```bash
  git checkout -- data/portfolio.json
  ```

- **Revert a committed migration** (history preserved):

  ```bash
  git revert <migration-commit-sha>
  ```

  Use `git log -- data/portfolio.json` to find the commit SHA.

For a hard reset to a known-good commit, prefer `git revert` over
`git reset --hard` — revert keeps the bad migration in history, which is
useful when reproducing the issue or filing a bug.

## See also

- [Run a schema migration](run-a-migration.md)
- [Migration version history reference](../reference/migrations.md)
