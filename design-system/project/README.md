# Rikdom Design System

> **rikdom** *(Norwegian, noun)* — "wealth", "riches". A portable, local-first wealth-portfolio schema and storage toolkit.

This is the design system and brand guide for **rikdom**, a CLI-first toolkit for durable, plain-text financial data. It gives designers and coding agents the foundations — type, color, voice, UI kits — needed to produce interfaces, landing pages, docs, and slides that feel unmistakably *rikdom*.

---

## What rikdom is

rikdom treats wealth data as **durable, long-lived information** — not a locked product database. Your portfolio lives in a folder you own, as plain JSON and JSONL files, independent of any broker app or SaaS dashboard.

It solves:

- Defining a portfolio for a person or company.
- Tracking holdings across stocks, REITs, funds, real estate, cash equivalents, digital assets and cryptocurrencies.
- Modeling recurring operations (monthly/yearly tasks) with an auditable "last done" history.
- Extending asset types with country-specific classes, metadata, and typed instrument attributes.
- Persisting data in simple disk files (JSON + JSONL).
- Generating a minimal static dashboard for allocation and progress over time.
- Ingesting provider statements through community plugins.

### Core Principles

1. **Local-first** — data stays in your folder.
2. **Durable formats** — JSON schema and line-delimited snapshots.
3. **Extensible by design** — metadata and extensions fields, plugin system.
4. **Agent-friendly** — explicit schema + instructions for Codex/Claude.

### Products / Surfaces in this system

- **CLI** — the primary interface. `rikdom init`, `rikdom add`, `rikdom snapshot`, `rikdom dashboard`.
- **Static dashboard** — the zero-dependency HTML page rikdom generates from your data.
- **Marketing / docs site** — a small site that introduces the toolkit and hosts the handbook.

---

## Sources

No codebase, Figma, or other design resources were provided when this system was created. The system is derived from:

- The written product description (paste prompt, April 2026).
- The brief: *"warm, stable tone that reminds of Nordic or Norwegian minimalism and stability"*.

If a codebase or Figma eventually exists, reattach them and we'll tighten everything against real source of truth (icons, actual component states, real copy from the CLI).

---

## Content Fundamentals

rikdom's voice is **quiet, steady, and literal**. It sounds like a well-written man page crossed with a Nordic public-broadcasting announcement. It respects the reader's time and intelligence. It does not shout. It does not upsell. It does not use growth-copy tropes.

### Tone

- **Calm, factual, slightly spare.** Short declarative sentences. The things we say are things we can prove.
- **Durable, not trendy.** Copy should read fine in five years. Avoid slang, year-specific references, hype words ("revolutionize", "supercharge", "unleash").
- **Honest about scope.** rikdom is a toolkit, not a product with promises. We say what it does, not what it will do for you.
- **Warm, not cold.** Nordic minimalism is *stone and linen*, not *steel and chrome*. Copy should feel hand-finished, not clinical.

### Person & address

- Prefer **"you"** when addressing the reader directly in docs and marketing.
- Prefer **imperative mood** in the CLI and docs (`Add a holding.`, `Run a snapshot.`).
- Use **"we"** sparingly, only when speaking as the project's maintainers. Never "I".

### Casing

- **Sentence case everywhere.** Headings, buttons, labels, menu items — all sentence case.
- **`rikdom` is always lowercase** in running text. Only capitalize at the start of a sentence if unavoidable — better to rewrite.
- Code identifiers stay in their native casing (`JSONL`, `snapshot.jsonl`, `addHolding`).

### Punctuation & numbers

- Proper em-dashes (—) and en-dashes (–). Curly quotes in prose ("like this"), straight quotes in code.
- Use the **thin non-breaking space** between number and currency/unit where typographically right; otherwise a normal space. Write `1 200 NOK` or `1,200 NOK` — pick one per document and stick with it.
- Amounts in docs are illustrative; prefer round example numbers (`100 000 NOK`, not `97 384.12 NOK`) unless the precision matters.

### Emoji & decoration

- **No emoji.** Not in UI, not in docs, not in commit messages. If a glyph is needed, use a proper icon or a typographic mark (✱ · † ¶ §).
- **Minimal exclamation.** At most one per page; preferably zero.
- **No marketing superlatives.** "Simple" beats "incredibly simple". "Fast" beats "blazingly fast".

### Examples

| Don't | Do |
| --- | --- |
| "🚀 Supercharge your portfolio with rikdom!" | "rikdom keeps your portfolio in a folder you own." |
| "Click here to get started on your wealth journey." | "Start with `rikdom init`." |
| "Our AI-powered dashboard reimagines asset tracking." | "Generate a static dashboard from your data." |
| "Welcome back, investor! 👋" | "Welcome back." |
| "Oops! Something went wrong. 😬" | "Couldn't read `holdings.json`. Check the path and try again." |

---

## Visual Foundations

### Mood

Warm Nordic minimalism. Think **unbleached paper, oak, birch bark, stone, indigo twilight**. Materials that age well. Long winter light. A handbook, not an app.

The visual system should feel like it could be printed on good paper and still work. If a decision would break in print, reconsider it.

### Color

The palette is anchored in three neutral tones that come from natural materials (paper, stone, ink), plus a single **Fjord** accent — a deep, slightly desaturated indigo that acts as our only "brand" color. Semantic colors (gain / loss / caution) are muted earth tones, not saturated traffic-light greens and reds.

- **Paper** `#F4EFE6` — default background. Warm off-white, not cool white.
- **Linen** `#E9E2D4` — secondary surface / card background.
- **Stone** `#B8AE9E` — hairline borders, muted text.
- **Ink** `#1F1A14` — primary text. Near-black, warmed with brown.
- **Graphite** `#4A4239` — secondary text.
- **Fjord** `#2C4A6B` — the only accent. Links, focus rings, primary buttons.
- **Moss** `#5F6B3A` — gains / positive.
- **Rust** `#8A3A1F` — losses / destructive.
- **Amber** `#B98A2C` — caution / pending.

All colors have matching **dark-mode** values tuned for an evening reading feel — no harsh black. The dark background is `Midnight #14161A` (warm near-black with a hint of blue).

### Type

A two-family system:

- **Display & body:** [Fraunces](https://fonts.google.com/specimen/Fraunces) — a warm, high-contrast serif with slight softness; reads like a well-set book. *Flagged as a Google Fonts substitution — see Fonts note below.*
- **Mono:** [JetBrains Mono](https://www.jetbrains.com/mono/) — the CLI is our primary interface; the mono face carries equal weight to the serif.

Scale: modest, typographically quiet. No giant 120px hero numbers. Display maxes around 64px.

> **Font note:** No custom font files were provided. We use Fraunces and JetBrains Mono as Google-Fonts stand-ins. If a bespoke face is later chosen, swap the CSS vars in `colors_and_type.css` and drop the `.ttf`/`.woff2` into `fonts/`.

### Spacing & rhythm

An **8-point baseline**, but with generous whitespace — most pages use `space-6` (48px) as the section rhythm. Content columns are narrow (max ~640px for prose, ~960px for dashboards). Let the page breathe; Nordic design earns its reputation through air.

### Backgrounds

- Default: flat **Paper**. No gradients, no noise, no hero imagery on most surfaces.
- When a texture *is* used, it is a very subtle paper grain (1–3% opacity), never decorative.
- No full-bleed photography on marketing surfaces. Where imagery is needed, use one of:
  - A flat vector illustration in `Ink` on `Paper` (woodcut or linocut style).
  - A single high-quality black-and-white photograph with warm tint.
- **No gradients.** The one exception: a barely-perceptible vertical `Paper → Linen` on very long pages, for rest.

### Animation

Restrained. Animations exist to confirm, not to entertain.

- **Durations** — 150ms (micro), 240ms (standard), 400ms (entrance). Nothing above 500ms except dashboards fading in.
- **Easing** — custom `cubic-bezier(0.2, 0, 0, 1)` ("settle"); slightly decelerated, never bouncy.
- **No bounces, no springs, no elastic.** This is a ledger, not a toy.
- Page transitions: content cross-fades. Route changes do not slide.

### Hover & press

- **Hover** — text gains underline (`text-decoration: underline`, 1px, `currentColor`, offset 3px). Buttons darken background by ~4% (we use an overlay, not a new color). No color changes for brand consistency.
- **Press** — buttons shift 1px down and darken by ~8%. No scale transforms.
- **Focus** — 2px `Fjord` ring with 2px offset, fully opaque. Always visible. No "focus:ring-blue-500/50" softness.

### Borders & shadows

- **Borders** — 1px solid `Stone`. Hairlines. We prefer borders over shadows.
- **Shadows** — used *only* for modals and dropdowns. One shadow token, soft and vertical: `0 2px 12px rgba(31,26,20,0.08), 0 8px 32px rgba(31,26,20,0.06)`. No `box-shadow` on cards or buttons.
- **Inner shadow** — never.
- **Protection gradients** — never; we use solid backgrounds and hairlines.

### Corner radii

Modest and consistent. We never fully round.

- **`radius-sm`** — 2px (inputs, small chips).
- **`radius`** — 4px (buttons, cards, most surfaces).
- **`radius-lg`** — 8px (modals, dashboard panels).
- No pill-shaped buttons. No fully rounded avatars — avatars are `radius-lg` squares, like passport photos.

### Cards

Flat. 1px `Stone` border, `radius`, `Linen` background on a `Paper` page (or `Paper` on `Linen`). Never a drop shadow. Padding is generous: `space-5` (32px) minimum on desktop.

### Transparency & blur

Both are rare. The only sanctioned uses:

- **A sticky header** may use `Paper` at 85% opacity with a 12px backdrop blur. Nothing else.
- **Overlays** (modal scrims) are solid `Ink` at 40% opacity. No blur.

### Iconography

See the **Iconography** section below. Short version: thin line icons (1.5px stroke), minimal set, never emoji.

### Imagery vibe

Warm neutral tones. If color photographs are used, they are tinted slightly warm. Avoid cold blue-hour imagery. Prefer:

- Long-exposure landscapes.
- Close-ups of natural materials (wood grain, linen weave, paper fiber).
- Black-and-white archival photography.

Never stock imagery of people pointing at laptops.

### Layout rules

- The CLI is where real work happens. Marketing pages should not oversell a GUI that isn't the point.
- Narrow content columns. Generous margins. Pages anchored to the left, not centered, when the content is procedural (docs, changelogs).
- A persistent `rikdom` wordmark top-left; minimal top-right nav (docs, github, handbook).
- Footers carry the **license**, the **schema version**, and the **commit hash** the site was built from. This is a data tool; we show the data about ourselves.

---

## Iconography

- **Set:** [Lucide](https://lucide.dev) — outline icons at 1.5px stroke. Linked from CDN (`https://unpkg.com/lucide-static@0.441.0/icons/`). *Flagged as substitution: no custom icon set was provided.*
- **Size:** 16px default in UI, 20px for section headers, 24px maximum. Never larger.
- **Stroke:** 1.5px. Never vary stroke within one screen.
- **Color:** `currentColor`. Icons inherit text color. Never colored icons, never brand-filled icons.
- **Emoji:** Never used. Not in UI, not in docs.
- **Unicode marks as glyphs:** Permitted for typographic flourishes: `§` for section, `¶` for paragraph, `†` / `‡` for footnotes, `✱` as a list bullet on marketing pages. Never as replacement for functional icons.
- **Logo:** A wordmark, not a symbol. See `assets/logo.svg`. The wordmark uses Fraunces display in `Ink`. There is no app icon equivalent — the CLI doesn't need one. If a square mark is required (social preview, favicon), use `assets/mark.svg` — the letter `r` in Fraunces on `Paper`.

---

## Index

Root of this design system:

```
README.md                  — this file
SKILL.md                   — Agent-SKill frontmatter for use in Claude Code
colors_and_type.css        — design tokens (CSS custom properties) + @font-face
fonts/                     — web fonts (Fraunces, JetBrains Mono — served via Google)
assets/                    — logos, marks, background images
preview/                   — Design System tab cards
ui_kits/                   — high-fidelity interface recreations
  cli/                     — terminal / CLI UI kit
  dashboard/               — static dashboard UI kit
```

There are no slides in this system — no deck template was provided. If a deck template is later shared, slides will live in `slides/`.

---
