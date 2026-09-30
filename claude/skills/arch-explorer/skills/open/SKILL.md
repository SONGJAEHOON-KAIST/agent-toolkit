---
name: open
description: Open the architecture map in the browser with a chat panel beside it that answers questions about the code from the project's code-wiki, using headless Claude or Codex, read-only. Checks first that the map and the wiki are current, and offers to build, create or sync whichever is missing or behind. Use when asked to open, show or view the architecture map, to ask questions about the codebase next to the map, or "지도 열어줘", "아키텍처 맵 보여줘".
argument-hint: "[map path] [--engine=claude|codex] [--reset-engine] [--port=N]"
---

# Open the map with a chat panel

Serve the map built by `/arch-explorer:build` from a local server that adds a
chat panel, and open it in the browser. The reader asks questions in the
panel; a headless `claude` or `codex` answers them from the code-wiki,
read-only, in the repository root.

The program decides freshness and runs the server. This skill asks the user
the questions the program cannot answer, and runs the builds they agree to.
**Never edit the map, the wiki, `.code-wiki/state.json` or the runtime files
by hand to make a check pass.**

`<plugin>` below is this plugin's root: two levels above this skill's base
directory. `<root>` is `git rev-parse --show-toplevel`. Outside a git
repository, stop and say that freshness checks and the chat need one.

## 0. Arguments

```
/arch-explorer:open [map path] [--engine=claude|codex] [--reset-engine] [--port=N]
```

| Given | Meaning |
|---|---|
| map path | the map's HTML; default `docs/architecture/index.html` |
| `--engine` | answer with this engine, this time only; the saved default is untouched |
| `--reset-engine` | forget the saved default engine and choose again (§3) |
| `--port` | fixed port for the server; default: any free port |

Anything else, ask about rather than guess.

## 1. The map

```bash
python3 "<plugin>/bin/status.py" check --root <root> --map <map path>
```

Read `map` from the output:

| `map.state` | Do |
|---|---|
| `missing` | Ask "No map at `<path>`. Build it now?" Yes → follow `/arch-explorer:build` (the sibling `build/SKILL.md`) for this output path; it skips its own freshness check and its offer to open. Then go on to §2. No → stop. |
| `unknown` | Ask "Can't tell when this map was built (`<reason>`). Rebuild, or open as is?" |
| `stale` | Ask "`<changed>` files changed since this map was built, e.g. `<sample>`. Rebuild, or open as is?" Offer *open as is* first: a rebuild rereads the whole codebase, and changed files do not always mean a changed structure. |
| `fresh` | Go on. |

Skip this section when `/arch-explorer:build` sent you here — the map was
just built.

## 2. The code-wiki

The chat answers from the code-wiki. Without one, open the map without the
panel (chat off).

1. **Is code-wiki installed?** Look for `code-wiki:sync` among the available
   skills. If it is not there, say the chat needs it —
   `/plugin install code-wiki@robintech` — and continue with chat off.
2. Read `wiki` from the §1 output (re-run the check if you built the map):

| `wiki.state` | Do |
|---|---|
| `missing` | Ask "This repo has no code-wiki; the chat answers from one. Create it now? It reads the whole codebase." Yes → run `/code-wiki:init`, then `/code-wiki:build`. No → chat off. |
| `unknown` | Ask "Can't tell whether the wiki is current (`<reason>`). Sync it?" Yes → `/code-wiki:sync`. No → go on. |
| `stale` | Ask "`<changed>` files changed since the wiki was last updated. Sync it?" Yes → `/code-wiki:sync`. No → go on; the panel shows a warning and answers note the gap. |
| `fresh` | Go on. |

Run code-wiki through its own skills (the Skill tool) and let them ask their
own questions. Do not call code-wiki's scripts by path. If init or build is
declined or fails partway, continue with chat off and say so.

After a create or sync, run the check again. If the wiki still is not
`fresh`, report what the check says rather than retrying — the check is
conservative and can call a wiki stale when only files code-wiki ignores
changed; `/code-wiki:sync` reporting "up to date" settles it.

## 3. The engine

Only with chat on.

```bash
python3 "<plugin>/bin/engines.py" choose [--engine <e>] [--reset]
```

- `engine` set → use it. Mention `reason` when it is not the saved default
  (a fallback, or `--engine`).
- `ask: true` → both are installed and no default is saved. Ask "Which engine
  should answer questions by default — Claude or Codex? (Saved for next time;
  change it with `--reset-engine`.)" Then:
  ```bash
  python3 "<plugin>/bin/engines.py" set-default <answer>
  ```
- `engine: null` and no `ask` → neither CLI is installed (or `--engine` named
  a missing one): say so and continue with chat off.

## 4. Open it

Chat on:

```bash
python3 "<plugin>/bin/chat_server.py" launch --root <root> --map <map path> \
  --engine <engine> [--port N]
```

This reuses a server already running for this repo and map (a different
engine restarts it), otherwise starts one detached, waits until it answers,
and opens the browser. It prints `url`, `pid`, `reused` and `log`, or `error`
and `log` — on an error, show the last lines of the log and stop.

Chat off: open the file directly, with no server.

```bash
python3 -m webbrowser -t "file://<absolute map path>"
```

## 5. Report

In a few lines:

- the URL (it carries a one-time token; it works only on this machine),
- the engine, and whether it is the saved default,
- the map's and wiki's state, including anything left stale by choice,
- chat off, and why, when that is the case,
- how to stop the server:
  `python3 "<plugin>/bin/chat_server.py" stop --root <root> --map <map path>`.

The server keeps running after this session ends, until stopped or the
machine restarts; running `/arch-explorer:open` again reuses it.

## What the chat can and cannot do

- Answers are read-only: Claude runs with only Read, Grep and Glob and no MCP
  servers; Codex runs in its read-only sandbox. Neither can change files.
- The panel sends the layer being viewed and the selected box with each
  question, so "what does this do?" means the selected box.
- A conversation continues until "새 대화" in the panel or a server restart.
- Each question is limited to 300 seconds; the engine's errors are shown as
  they are, never as an empty answer.
