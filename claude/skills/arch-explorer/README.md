# arch-explorer

Turn a codebase into an interactive architecture map — a single HTML file you
open from `file://`, no build step, no network.

Boxes are modules. Arrows are calls that actually exist in the source, labeled
with the name of the interface that crosses the boundary. Click a box to descend
into what it is made of; keep clicking until there is nothing left to decompose.
Under the diagram, every arrow expands into a card with full signatures, the
transport, and `file:line` source locations.

## Install

```
/plugin marketplace add robintech-seoul/agent-toolkit
/plugin install arch-explorer@robintech
```

## Use

```
/arch-explorer:build
```

Then say what to map — the whole repo, or one service. The skill also triggers
on its own when you ask for an architecture diagram, a system map, or a
structural overview of a codebase.

Output defaults to `docs/architecture/index.html` plus a short `README.md`
covering the layer tree and how to update it, and `arch-explorer.json`
recording the commit it was built from. All structure data lives in one
`MODEL` object at the top of the HTML, so later edits are data edits.

## Open it with a chat panel

```
/arch-explorer:open [map path] [--engine=claude|codex] [--reset-engine] [--port=N]
```

Opens the map in your browser with a chat panel on the right. Ask about the
code there; a headless `claude` or `codex` answers from the project's
[code-wiki](../code-wiki), read-only, citing wiki pages and `file:line`.
Citations that match an interface card link to it, and each question carries
the layer you are viewing and the box you selected, so "what does this do?"
means that box.

Before opening, it checks that both the map and the wiki are current:

| Found | Asks |
|---|---|
| no map | build it? (then opens without asking again) |
| map older than the code | rebuild, or open as is? |
| no code-wiki | create it? (no → the map opens without the chat) |
| wiki older than the code | sync it? (no → the panel shows a warning) |

When both engines are installed, the first run asks which should answer by
default and saves the choice in `~/.config/arch-explorer/config.json`.
`--engine` overrides it for one run; `--reset-engine` asks again.
`/arch-explorer:build` offers to open the map when it finishes, and offers
to open instead of rebuilding when the map is already current.

The chat runs through a local server (`bin/chat_server.py`), since a page
opened from `file://` cannot start programs. The server:

- listens on `127.0.0.1` only, and accepts only its own `Host` and `Origin`,
- requires a per-launch token (in the URL it opens, then an HttpOnly cookie),
- adds the panel while serving the page — the HTML file on disk is never
  changed, and still opens from `file://` without the panel,
- runs Claude with only Read/Grep/Glob and no MCP servers, and Codex in its
  read-only sandbox.

It keeps running until you stop it:

```
python3 <plugin>/bin/chat_server.py stop --root <repo> --map <map path>
```

`build` now writes `arch-explorer.json` next to the map, recording the commit
and scope it was built from; commit it with the map. Maps built before 0.3.0
have none, so `open` treats their age as unknown and the panel cannot see box
selection in them — rebuild to get both.

## Map what a branch changed

```
/arch-explorer:diff [head [base]] [--save-to[=<path>]] [--include-uncommitted]
```

Draws the same map for the code at the head of a branch, with the boxes,
arrows and interfaces it added, modified or removed marked, and under it one
card per block explaining which features changed, with `file:line`. Subagents
explain the blocks in parallel.

| Given | Compares |
|---|---|
| nothing | the current branch against `main` (or `master`) |
| `head` | `head` against `main` (or `master`) |
| `head base` | `head` against `base` |

The diff runs from the merge-base, so only the branch's own work shows. The
skill asks for a base instead of guessing when you are on `main`/`master`,
when neither exists, or when the branches share no history. It reads other
branches through `git show` or a temporary worktree and never checks anything
out in your working tree.

| Option | Output |
|---|---|
| (none) | `./<head>-vs-<base>.html` |
| `--save-to` | `docs/architecture/changes/<head>-vs-<base>.html` |
| `--save-to=<path>` | `<path>` if it ends in `.html`, else `<path>/<head>-vs-<base>.html` |

`/` in branch names becomes `-`. If the file already exists, it is
overwritten.

By default only commits count. `--include-uncommitted` compares against the
working tree instead — staged, unstaged and untracked files, minus what
`.gitignore` excludes — and works only for the current branch. On `main` it
can show just your uncommitted changes. The file gets `-uncommitted` after the
head name (`feature-login-uncommitted-vs-main.html`), so it never overwrites
the committed comparison. The snapshot goes through a temporary index; your
staging area is left as it was.

## Development

```
python3 -m unittest discover -s claude/skills/arch-explorer -t claude/skills/arch-explorer -v
```

The tests use throwaway git repositories and fake `claude`/`codex` scripts;
they do not show that the real CLIs work. Check that by running
`/arch-explorer:open` against a real repo with each engine.
