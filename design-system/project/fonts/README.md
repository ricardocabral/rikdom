# fonts/

rikdom uses two Google Fonts, loaded via `@import` in `colors_and_type.css`:

- **Fraunces** — display + body (variable font, opsz 9–144, weights 300–700, SOFT axis).
- **JetBrains Mono** — code + CLI + tabular numbers (weights 400, 500, 700).

No custom `.woff2`/`.ttf` files are shipped in this repo. If a bespoke face is chosen later, drop files here and update the `@font-face` block at the top of `colors_and_type.css`.

**Flagged to user:** Fraunces + JetBrains Mono are Google-Fonts substitutions. If rikdom has a chosen custom face, please provide it.
