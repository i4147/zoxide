# zoxide

A Python re-implementation of [zoxide](https://github.com/ajeetdsouza/zoxide),
the "smarter cd command" — it tracks the directories you actually use and
lets you jump to them with a few keystrokes, ranked by **frecency**
(frequency + recency).

```
z proj        # jump to your most "frecent" directory matching "proj"
z proj web    # multiple keywords narrow the match
zi proj       # interactively pick from matches (uses fzf if installed)
z -           # like `cd -`
z             # go home
```

## How it works

* Every time you `cd`, a shell hook calls `zoxide add -- "$PWD"`, bumping
  that path's rank in a small JSON database
  (`~/.local/share/zoxide/db.json`, or `$XDG_DATA_HOME/zoxide/db.json`).
* `zoxide query <keywords>` searches the database: every keyword must be a
  case-insensitive substring of the path, and the *last* keyword must match
  the final path component — this is the same rule the original zoxide uses,
  so `z foo` prefers `/home/me/foo-project` over some deeply nested
  unrelated match that merely contains "foo" earlier in the path.
* Ranking combines **rank** (times visited, incremented on each `add`) with
  **recency** (a multiplier: 4x if visited in the last hour, 2x in the last
  day, 0.5x in the last week, 0.25x older) — again mirroring upstream
  zoxide's aging algorithm. When the sum of all ranks crosses a threshold,
  every entry's rank is scaled down (aging out unused directories) instead
  of using a hard entry-count cap.

## Install

```bash
cd zoxide
pip install -e .
```

This installs a `zoxide` executable (equivalent to the real zoxide binary).

## Shell integration

Add one line to your shell config, exactly like the real zoxide:

```bash
# ~/.bashrc
eval "$(zoxide init bash)"

# ~/.zshrc
eval "$(zoxide init zsh)"

# ~/.config/fish/config.fish
zoxide init fish | source
```

This defines:
* `z` — the jump command (customize the name with `--cmd j`)
* `zi` — interactive jump via `fzf` if available, else a numbered fallback
  prompt
* an automatic hook that calls `zoxide add` on every directory change
  (`PROMPT_COMMAND` in bash, `precmd_functions` in zsh, `--on-variable PWD`
  in fish)

A minimal `posix` template is also available for `sh`/`dash` (jump function
only — no automatic tracking hook, since that requires shell-specific prompt
support).

## CLI reference

```
zoxide add <path>...                 # add/bump one or more paths
zoxide query [-l] [-s] [-i] <kw>...  # search (-l list all, -s show score, -i interactive)
zoxide query --exclude <path> <kw>.. # exclude a path (used internally by `z`)
zoxide remove <path>                 # remove an entry
zoxide remove -i                     # interactively pick an entry to remove
zoxide edit <path> <score>           # directly set an entry's rank
zoxide import <file> [--merge]       # import from a z.sh/autojump-style dump
zoxide init <bash|zsh|fish|posix>    # print shell integration script
```

## Differences from the original (Rust) zoxide

* Database is plain JSON, not bincode — easy to inspect/edit by hand, but
  less compact for very large histories.
* No PowerShell/Nushell templates (only bash/zsh/fish/posix).
* `import` supports two simple text formats (autojump's `weight<TAB>path`
  and z.sh's `path|rank|epoch`) rather than reading the original zoxide's
  binary database directly.

## Tests

```bash
python3 -m unittest discover -s tests -v
```
