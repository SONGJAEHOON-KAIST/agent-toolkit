---
name: diff
description: Explain what a branch changed, block by block, as an interactive architecture map in a single self-contained HTML file. Compares a head branch against a base (default — the current branch against main or master), assigns every changed file to the module box it lives in, explains each block's changes as features with file:line references, and draws the map with added, modified and removed boxes, arrows and interfaces marked. Use when asked what a branch or PR changed structurally, to explain or review a branch's changes by module, for a visual change summary, or "브랜치 변경 내용을 블럭별로 설명해줘".
argument-hint: "[head [base]] [--save-to[=<path>]] [--include-uncommitted]"
---

# Branch change map

Produce **one HTML file** that shows what a branch changed: the architecture
map of the code at the head of the branch, with every box, arrow and interface
the branch touched marked, and under it one card per block explaining which
features changed and where.

This skill builds on `/arch-explorer:build`. Read its `SKILL.md` — the sibling
`build/SKILL.md` in this plugin — and follow its sections 1–4 (reading the
code, interfaces, rendering, verifying) with the overrides below. Its rule
holds here too, and applies to changes as much as to structure: **never claim
a change you have not seen in the diff.**

## 0. Arguments

```
/arch-explorer:diff [head [base]] [--save-to[=<path>]] [--include-uncommitted]
```

| Given | head (the new work) | base (compared against) |
|---|---|---|
| `head base` | `head` | `base` |
| `head` | `head` | auto-detected (§1) |
| nothing | the current branch | auto-detected (§1) |

Two flags, and no others; anything else that is not a ref, ask about rather
than guess.

- `--save-to` changes where the file is written (§6).
- `--include-uncommitted` compares against the working tree instead of head's
  last commit: staged, unstaged and untracked (not ignored) files all count as
  part of the branch's work. It applies only when head is the current branch,
  since only the current branch has a working tree here.

## 1. Resolve the range

Everything below reads refs; **never check out, reset or stash in the user's
working tree.**

1. **Head.** With no positional argument, `git branch --show-current`. Empty
   output means a detached HEAD — ask which branch to explain.
2. **Base, when not given.** Take the first of these that exists
   (`git rev-parse --verify --quiet <ref>^{commit}`):
   `refs/heads/main`, `refs/remotes/origin/main`, `refs/heads/master`,
   `refs/remotes/origin/master`. Refer to it by the branch name (`main`), not
   the remote-tracking name. If a local and an `origin/` ref both exist and
   point at different commits, use the local one and say so in the report.
3. **Ask the user for the base, and do not proceed, when:**
   - head is itself `main` or `master` and no base was given — with
     `--include-uncommitted`, offer "only the uncommitted changes" (base = head
     itself) as one of the choices,
   - neither `main` nor `master` exists,
   - a ref the user named does not resolve,
   - head and base resolve to the same commit — unless
     `--include-uncommitted` is given, in which case the comparison is simply
     the uncommitted changes,
   - `git merge-base <base> <head>` finds no common ancestor.

   Also ask, rather than silently dropping the flag, when
   `--include-uncommitted` is given but head is not the current branch.
4. **Compare from the merge-base**, `mb = git merge-base <base> <head>`. All
   diffs run from `mb` — the same as `git diff base...head`. A two-dot diff
   against the base tip would also show everything that landed on the base
   after the branch forked, as if the branch had reverted it.
5. **Fix the after side, `<after>`.** Without `--include-uncommitted` it is
   `head`. With it, it is a tree snapshot of the working tree, taken through a
   temporary index so the user's own index is never touched:

   ```
   tmp=<scratch-dir>/index
   cp "$(git rev-parse --git-path index)" "$tmp"
   GIT_INDEX_FILE="$tmp" git add -A
   after=$(GIT_INDEX_FILE="$tmp" git write-tree)
   ```

   `git add -A` honours `.gitignore`, so ignored files stay out. Every diff
   below uses `<after>`; the commit list still reads `mb..head`.
6. If `git diff --quiet mb <after>` reports no changes, say so and stop; do not
   write a file.
7. If head is the current branch, `git status --porcelain` is non-empty and
   `--include-uncommitted` was not given, note in the report that uncommitted
   changes are not part of the comparison and that the flag would include
   them. With the flag, report how many files came from uncommitted work
   (`git diff --name-only head <after>`).

## 2. Collect the change

```
git log --reverse --format='%h %s' mb..head
git diff --name-status -M mb <after>
git diff --numstat -M mb <after>
```

**Where to read code.** The code before the change is `git show mb:<path>`.
The code after it is the working tree when head is the current branch and
either the tree is clean or `--include-uncommitted` is given; otherwise add a
temporary worktree,
`git worktree add --detach <scratch-dir> <head>`, read there, and remove it
with `git worktree remove` when done.

## 3. Map the head — only as deep as the change

Build the map of the code at head following build's sections 1–2, with these
overrides:

- **Scope** is the whole repository — a change can reach anywhere. Do not ask.
- **Start from an existing map when there is one.** If
  `git show mb:docs/architecture/index.html` succeeds, take its `MODEL` as the
  starting point and bring it up to date with head, instead of mapping from
  nothing.
- **Depth follows the change.** Draw L0 and L1 in full. Below that, drill only
  into boxes that contain a changed file; an unchanged box stays a leaf with
  no `drill`. Mapping untouched subtrees makes the cost grow with the
  repository instead of with the change.
- **Keep what was removed.** A module, arrow or interface that existed at `mb`
  and is gone at head stays in the map, marked `removed`, where it used to be.
- **Assign every changed file to a block** — the deepest box whose code
  contains it. A file that belongs to no box (lockfiles, CI config, docs) goes
  in an explicit `other` block. No changed file is dropped.

## 4. Explain each block — subagents

The block is the unit of explanation. For a small change (about five files or
fewer, or a single block) do this yourself. Otherwise launch **one subagent
per block, all in a single message** so they run in parallel; with more than
six blocks, group sibling blocks until there are six at most.

Give each subagent: head, `mb`, `<after>`, where to read head's code (§2),
the block's box title and its list of changed files. Tell it to read
`git diff mb <after> -- <files>`, the surrounding code at head and the old
code with `git show mb:<path>`, and to **return only this JSON, writing no
files**:

```json
{
  "block": "<viewId>/<nodeId>",
  "summary": "one or two sentences: what this block's change does",
  "features": [
    { "title": "name of the behaviour that changed",
      "desc": "what it did before, what it does now, why it matters",
      "refs": ["path:line"] }
  ],
  "ifaces": [
    { "name": "SqlStorage.put_objective",
      "change": "added | modified | removed",
      "before": "old signature or null", "after": "new signature or null",
      "ref": "path:line" }
  ],
  "modules": [
    { "path": "src/foo/", "change": "added | removed", "what": "one line" }
  ]
}
```

Describe **features, not lines.** "Retries the upload three times on 5xx" is
an explanation; "added a for loop in upload.py" is a diff read aloud.

You are the only writer of `MODEL`. Merge the subagents' results into it
yourself, and spot-check a few of their `refs` before trusting them.

## 5. The change overlay

The file carries build's `MODEL` plus change marks. An element with no
`change` is unchanged, so an untouched part of the map is plain build output.

```js
const MODEL = {
  <viewId>: {
    ...,                                  // as in build
    nodes:  [{ ..., change?: 'added' | 'modified' | 'removed' }],
    edges:  [{ ..., change? }],
    ifaces: [{ ..., change?,
               items: [{ sig, before?, desc, ref }] }]   // before: old signature
  }
}
const CHANGES = {
  range:  { head, base, mergeBase, uncommitted: bool, commits: [{ sha, subject }] },
  blocks: [{ node: '<viewId>/<nodeId>' | 'other', summary,
             features: [{ title, desc, refs: [] }],
             files:    [{ path, status, added, removed }] }]
}
```

Do not store what can be derived. Whether a box *contains* changes is
computed by the renderer from its descendants, not written into the data.

The renderer is yours to write, as in build, and must add to build's
interaction contract:

- A header with head vs base, the merge-base short sha and the commit list
  (collapsed by default). When `uncommitted` is true, the header says the map
  includes uncommitted work, so nobody mistakes it for the pushed branch.
- A legend. Added, modified and removed each get a distinct colour; removed
  elements are drawn ghosted and dashed.
- A badge on every box with changes inside it, showing how many changed files
  it holds, so a reader can follow the change down from L0.
- Under the diagram, the change cards for the blocks in the current view,
  before the interface cards. Clicking a box filters both to that box.
- An interface card whose signature changed shows `before` and the new
  signature together.
- `refs` link to nothing outside the file; show them as `path:line` text.

## 6. Where to write it

Name the file `<head>-vs-<base>.html`, with `/` in branch names replaced by
`-` (`feature/login` against `main` → `feature-login-vs-main.html`). With
`--include-uncommitted`, `<head>` becomes `<head>-uncommitted`
(`feature-login-uncommitted-vs-main.html`), so a snapshot of work in progress
never overwrites the map of the committed branch.

| `--save-to` | Written to |
|---|---|
| absent | `./<head>-vs-<base>.html` in the current directory |
| `--save-to` | `docs/architecture/changes/<head>-vs-<base>.html` |
| `--save-to=<path>` ending in `.html` | exactly `<path>` |
| `--save-to=<path>`, any other path | `<path>/<head>-vs-<base>.html` |

Paths are relative to the current directory. Create missing directories. If
the file already exists, overwrite it — it is the same comparison, re-run —
and say in the report that you did. Unlike build, write no `README.md` next to
it: this is a review of one branch, not a document to maintain.

## 7. Verify before you call it done

Run build's section 4 checks, and add:

- **Coverage** — every path from `git diff --name-status mb <after>` appears in
  exactly one block's `files`. Check this by script.
- **Reachability** — every element with a `change`, and every block's node,
  can be reached from L0 through `drill` links.
- **Refs land on the change** — each feature has at least one ref inside a
  changed hunk: after-side line numbers from `git diff -U0 mb <after>` for added
  or modified code, `mb`-side for removed code. Check this by script.
- **Removed means removed** — every `removed` element existed at `mb` and does
  not exist at `<after>`.

Then remove any worktree and temporary index you added, and report: the output path, the range
(head, base, merge-base, commit count), blocks and files changed, and the
notes from §1 and §6 that applied — which base ref was used, uncommitted
changes left out or how many were included, a file overwritten.

## Common failure modes

- **A two-dot diff.** Comparing against the base tip shows the base's newer
  commits as reverted by the branch. Always diff from the merge-base.
- **Reading the diff aloud.** Cards that list changed lines instead of saying
  which behaviour changed.
- **Mapping the whole repository deeply.** Only changed paths get depth.
- **Dropping files that do not fit a box.** They go in `other`, visibly.
- **Snapshotting through the real index.** `git add` without
  `GIT_INDEX_FILE` stages the user's files behind their back.
- **Checking out the branch to read it.** Use `git show` or a separate
  worktree; the user's working tree is not yours to move.
