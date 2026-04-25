# CLI UI kit

A high-fidelity recreation of the **rikdom** command-line experience — the primary interface to the toolkit. Demonstrates the visual language of a session: prompts, output, tables, schema hints, help text, and plugin messages.

This is a recreation, not a working CLI. State is faked in JS. It behaves like a terminal transcript you can scroll through and interact with at key points (init, add holding, snapshot, dashboard).

## Files

- `index.html` — interactive transcript: init a folder, add holdings, snapshot, generate a dashboard.
- `Terminal.jsx` — the terminal chrome + scroll container.
- `Line.jsx` — prompt / output / system-note primitives.
- `Prompt.jsx` — the input line with history.
- `Output.jsx` — multi-line output rendering (tables, JSON, tree views).
- `Schema.jsx` — pretty-printed JSON / JSONL snippets.

No real process runs. All commands are dispatched through a small switch in `index.html`.
