---
name: rikdom-design
description: Use this skill to generate well-branded interfaces and assets for rikdom, either for production or throwaway prototypes/mocks. Contains essential design guidelines, colors, type, fonts, assets, and UI kit components for prototyping.
user-invocable: true
---

Read the `README.md` file within this skill, and explore the other available files. Start there — it contains the full brand voice, content fundamentals, visual foundations, and iconography rules.

## What's here

- `README.md` — brand overview, content fundamentals, visual foundations, iconography.
- `colors_and_type.css` — drop-in tokens (colors, type, spacing, radii, motion) + Google Fonts import. `@import` this file at the top of any HTML you make.
- `assets/` — logo wordmark (`logo.svg`, `logo-dark.svg`) and square mark (`mark.svg`).
- `fonts/` — font notes (Fraunces + JetBrains Mono, loaded via Google Fonts).
- `preview/` — small HTML cards documenting each system piece (colors, type, spacing, components, brand).
- `ui_kits/cli/` — terminal UI kit: `Terminal.jsx`, `Prompt.jsx`, `Line.jsx`, `Output.jsx`, plus `index.html`.
- `ui_kits/dashboard/` — static dashboard UI kit: `Header.jsx`, `Summary.jsx`, `Allocation.jsx`, `HoldingsTable.jsx`, `Operations.jsx`, `SnapshotChart.jsx`, plus `index.html`.

## If creating visual artifacts

Copy `colors_and_type.css` and relevant `assets/` into your artifact folder. `@import "colors_and_type.css"` at the top of your stylesheet — everything keys off the CSS variables defined there. Reuse the CLI or dashboard JSX components when a terminal view or static dashboard view is needed; otherwise compose fresh markup using the tokens.

## If working on production code

Read the README's visual foundations in full before making component decisions. The rules are opinionated: no emoji, no gradients (except the one permitted), no bounces, hairlines over shadows, sentence case everywhere, `rikdom` always lowercase in running text. These are not suggestions — they are what makes the brand feel like rikdom.

## If invoked with no guidance

Ask the user what they want to build or design, ask a few sharpening questions (audience, surface, fidelity, which product area), and then act as an expert designer who outputs HTML artifacts or production code, depending on the need.
