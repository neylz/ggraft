# ggraft

**GLSL Graft** is a cli tool allowing declarative injection patches for vanilla Minecraft shaders.

Overriding a core shader means copying Mojang's file and changing one line. Do that across twenty shaders and every Minecraft update becomes twenty manual re-copies, with no record of what you actually changed. ggraft keeps the *edit* under version control instead of the result: you declare which line to change, and it re-derives the overrides from any version on demand.

## Terminology

| Concept | Name |
| --- | --- |
| The vanilla GLSL going in | **base** |
| A file declaring edits | **patch** |
| Which shader it's for | **target** |
| Where in the source | **injection point** (or **anchor**) |
| One edit inside a patch | **injection** |
| What it does | **operation**: `insert`, `replace`, `wrap`, `declare` |
| Anchor didn't match | **unresolved injection** |
| Anchor matched N times | **ambiguous injection** |
| GLSL coming out | **patched shader** |

## Install

### From PyPI

```bash
pip install ggraft
```

### From source

Needs Python 3.11+ and [Click](https://click.palletsprojects.com/).
Everything else is standard library.

```bash
pip install -e .
```

## Quick start

```bash
ggraft init 26.3      # write ggraft.toml
ggraft pull           # fetch bases from misode/mcmeta
ggraft build          # apply patches -> patched shaders
```

## Project configuration

`ggraft.toml`, found by walking up from the working directory. Paths resolve relative to it.

```toml
[base]
version = "26.3"                      # Minecraft version to pull
dir     = ".ggraft/base"              # where bases land (gitignore this)
source  = "assets/minecraft/shaders"  # subtree to pull, stripped from local paths
repo    = "misode/mcmeta"             # optional

[patches]
dir = "patches"

[output]
dir    = "assets/minecraft/shaders"   # required
header = true                         # stamp a provenance comment
```

Targets are relative to `base.source`: `core/terrain.vsh` reads from `.ggraft/base/core/terrain.vsh` and writes to `<output.dir>/core/terrain.vsh`.

## Patches

```toml
name    = "iso-world"
targets = ["core/terrain.vsh", "core/rendertype_*.vsh"]
exclude = ["core/rendertype_lines.vsh"]

[[injection]]
op      = "declare"
include = "foo:iso.glsl"

[[injection]]
op   = "replace"
at   = "gl_Position = ProjMat * ModelViewMat * vec4({expr}, 1.0);"
with = "gl_Position = iso_position(ProjMat, ModelViewMat, vec4({expr}, 1.0));"
```

Injections apply in order, to every matching target. Patches stack in filename order.

### Anchors

`at` is literal text, not a regex. `{name}` captures what sits in that position, `{match}` is the whole match; both are available in the replacement.

| Key | Meaning |
| --- | --- |
| `at` | the anchor pattern |
| `regex = true` | treat `at` as a regex, with named groups |
| `multiline = true` | let one `{name}` (or a regex `.`) span lines (false by default) |
| `occurrence = N` | take the Nth match (1-based) |
| `every = true` | apply to all matches |


No match is an **unresolved injection**; more than one without `occurrence` or `every` is an **ambiguous injection**. Both fail the build, naming the patch, injection index, target and line numbers.

### Operations

| Operation | Keys | Effect |
| --- | --- | --- |
| `replace` | `with` | swap the anchored text |
| `insert` | `text`, `where` (`before`/`after`) | add text beside it |
| `wrap` | `prefix`, `suffix` | surround it, keeping it |
| `declare` | `include` or `text` | add a top-level declaration; no anchor |

`declare` inserts after the last `#include` at conditional-nesting depth zero, falling back to `#extension` then `#version`, and is idempotent. Appending after the *last* `#include` in the file would strand it inside an `#ifdef` branch that some shader variants skip.

## Commands

| Command | Purpose |
| --- | --- |
| `ggraft pull [version]` | fetch bases; `--force` refetches, `-j` sets parallelism. Pulling another version replaces the base |
| `ggraft build` | apply patches; `--check` dry run, `-t` filters by glob |
| `ggraft targets` | show which patches hit which targets |
| `ggraft init [version]` | write a starter config; `--force` overwrites |

`-h`/`--help` works on the group and every command, `-V`/`--version` prints the version, and `-c`/`--config` points at a specific `ggraft.toml` instead of searching upwards. `pull --token` also reads `GITHUB_TOKEN`.

### Build guarantees

- `--check` dry run without output writes.
- A target pattern matching no base file fails the build. What a patch orphaned by a Minecraft update looks like.
- A patch applying to nothing fails the build, so a mistake in `targets` or `exclude` cannot disable a patch silently.
- Stale output is pruned. Shaders ggraft wrote are recorded in `.ggraft/manifest.json`, and a target dropped from a patch has its override deleted on the next build. Only manifest entries are ever deleted; `-t` disables pruning, since a partial build cannot tell what is stale.

## Bases

Uses [misode/mcmeta](https://github.com/misode/mcmeta).
Tree walk might be rate limited. Set `GITHUB_TOKEN` or pass `--token` to bypass the limit.

A pull downloads into a sibling `.partial` directory and swaps it in, so an interrupted pull leaves the existing base untouched and a completed one leaves nothing of it behind: `base.dir` is replaced wholesale, never merged into.

What the directory holds — version, repo and source — is recorded in `.ggraft/base.json`. Pulling a different version, repo or source therefore refetches instead of reporting the base as already present, and files from the old version cannot linger as targets for the next build. A base ggraft did not record is treated as stale and refetched too. `--force` refetches regardless.

## Tests

```bash
python -m unittest discover -s tests   # everything
python -m unittest tests.test_cli      # one module
```

One module per layer: `test_structure`, `test_glsl`, `test_anchor`, `test_operations`, `test_engine`, `test_sources`, `test_cli`. Shared shaders, project files and a network-free mcmeta client live in `tests/fixtures.py`.

## Planned Features
- [ ] functions injections
- [ ] python module API

