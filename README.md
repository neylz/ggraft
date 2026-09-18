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
| What it does | **operation**: `insert`, `replace`, `wrap`, `declare`, `function` |
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
op    = "replace"
match = "gl_Position = ProjMat * ModelViewMat * vec4({expr}, 1.0);"
with  = "gl_Position = iso_position(ProjMat, ModelViewMat, vec4({expr}, 1.0));"
```

Injections apply in order, to every matching target. Patches stack in filename order.

### Anchors

> [!NOTE] `match` is literal text, not a regex. `{name}` captures what sits in that position, and both `{name}` and `{match}` (the whole match) are available in whatever the operation writes back: `with`, `text`, `prefix` and `suffix`.

| Key | Meaning |
| --- | --- |
| `match` | the anchor pattern |
| `regex = true` | treat `match` as a regex, with named groups |
| `multiline = true` | let one `{name}` (or a regex `.`) span lines (false by default) |
| `occurrence = N` | take the Nth match (1-based) |
| `every = true` | apply to all matches |

`occurrence` and `every` cannot both be set. `multiline` is only about letting a single `{name}` (or a regex `.`) cross one. A capture is non-greedy and must match at least one character, so `vec4({expr})` does not match `vec4()`.

Under `regex = true` the pattern is used as written, with `^` and `$` matching at every line boundary, and its named groups `(?P<name>...)` fill the same `{name}` placeholders. In the replacement, a `{name}` that captured nothing is left exactly as it is, so GLSL braces and unrelated placeholders survive untouched.

No match is an **unresolved injection**, and so is an `occurrence` past the number of matches. More than one match without `occurrence` or `every` is an **ambiguous injection**, reported with the line of every match. Both name the patch, the injection index and the target, and both fail the build.

### Operations

| Operation | Keys | Effect |
| --- | --- | --- |
| `replace` | `match`, `with` | swap the anchored text |
| `insert` | `match`, `text`, `where` (`before`/`after`, `after` by default) | add text beside it |
| `wrap` | `match`, `prefix` and/or `suffix` | surround it, keeping it |
| `declare` | `include` or `text` | add a top-level declaration; no anchor |
| `function` | `function`, `text`, `at` (`HEAD`/`TAIL`/`RETURN`/`INVOKE`/`BEFORE`/`AFTER`, `HEAD` by default), `occurrence`, and `call` plus `where` for `INVOKE` | add code in or beside a function; no anchor |

`replace`, `insert` and `wrap` are the anchored operations, so they also take `regex`, `multiline`, `occurrence` and `every` from [Anchors](#anchors). `declare` and `function` find their own place in the file and take no anchor.

`declare` writes the [directive the version calls for](#import-directives), and inserts after the last import at conditional-nesting depth zero, falling back to `#extension` then `#version`, and is idempotent. Appending after the *last* `#include` in the file would strand it inside an `#ifdef` branch that some shader variants skip.

### Function injections

`function` targets a function body rather than a piece of text, the way a regular mixin does. `at` names a structural point, not an anchor pattern.

```toml
[[injection]]
op       = "function"
function = "main"
at       = "HEAD"           # HEAD by default
text     = "iso_setup();"
```

| Point | Where the text lands |
| --- | --- |
| `HEAD` | first statement of the body |
| `TAIL` | last statement, before the closing brace |
| `RETURN` | before every `return`, nested ones included |
| `INVOKE` | around every statement that calls `call` |
| `BEFORE` | above the definition, at top level |
| `AFTER` | below the definition, at top level |

Text lands on a line of its own, indented like its neighbours. Multi-line `text` is indented line by line and keeps its blank lines; a one-line body stays on one line. Nothing is substituted, so `{x}` stays `{x}`.

`INVOKE` needs `call`, the function being called, and takes `where` (`before` by default, or `after`):

```toml
[[injection]]
op       = "function"
function = "main"
at       = "INVOKE"
call     = "fog_distance"
where    = "after"
text     = "iso_note_fog();"
```

It wraps the whole statement holding the call, never the expression inside it, and hits every call in the body. for one call in particular, use `insert` with a `match` anchor. A call that opens a block, like `if (helper(x)) {`, has no statement to follow: `where = "after"` is unresolved there, `before` always works.

Prototypes, calls and commented-out code are not definitions. An overloaded name is an **ambiguous injection** until `occurrence = N` picks one, and `RETURN` on a function that never returns is an **unresolved injection**, use `TAIL` insteaad.

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

## Tests

```bash
python -m unittest discover -s tests   # everything
python -m unittest tests.test_cli      # one module
```

One module per layer: `test_structure`, `test_glsl`, `test_anchor`, `test_operations`, `test_engine`, `test_sources`, `test_cli`. Shared shaders, project files and a network-free mcmeta client live in `tests/fixtures.py`.

## MOJ_IMPORT support

Versions before ``26.3`` were using the ``#moj_import`` directive instead of ``#include``. Setting in ``ggraft.toml`` the target version strictly below ``26.3`` will automatically convert behavior of ``declare`` operator to output the ``#moj_import`` directive.


## Planned Features
- [ ] python module API
