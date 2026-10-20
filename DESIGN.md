**For agents:** This file is frozen. Do not update it.

# **Goal**

Add a restricted link check to any Sphinx project: only URLs that are new or changed relative to the base branch are checked. The existing `make linkcheck` command is unchanged and checks all links.
The tool follows the Canonical Sphinx Stack model: a pip package with a Sphinx extension and a collection helper, and a Makefile target that ties them together.

# **User experience**

## **Commands**

| Command               | What it does                                                                                                                               |
| :-------------------- | :----------------------------------------------------------------------------------------------------------------------------------------- |
| `make linkcheck`      | Unchanged. Checks every external link.                                                                                                     |
| `make linkcheck-diff` | Checks only URLs that are new or changed relative to the base branch. Collects a baseline automatically on first use for a given base SHA. |

## **What make linkcheck-diff does**

The make target runs two phases in sequence:

1. **Ensure baseline.** The target calls the collection helper, which resolves the head SHA of the base branch and checks the cache. On a hit, the cached baseline is used. On a miss, the helper runs an isolated build of the base branch to collect its URLs and records the baseline. The helper prints the path of the baseline file.
2. **Run the linkcheck build.** A normal `sphinx-build -b linkcheck` run, plus `-D linkcheck_diff_baseline=<path>`. The extension adds every baseline URL to `linkcheck_ignore`, so only URLs outside the baseline are checked.

If there are no new URLs, the command makes no linkcheck HTTP requests. Sphinx still parses the docs and resolves intersphinx before the linkcheck phase runs.

## **What "new or changed" means**

A URL is checked if the current build discovers it and the baseline does not contain it. This catches:

- A brand-new link added to a doc or a Python docstring.
- An existing link whose URL was changed. The old URL is in the baseline, the new one is not.

The baseline build runs the base branch's own `conf.py` and source code in an isolated environment, so it discovers docstring URLs as they are on the base branch. Docstring URL changes are diffed the same as doc URL changes.

## **What is not checked**

- **Unchanged URLs** — those in the baseline. They exist on the base branch, so they are not new.
- **Intersphinx links** — these are resolved at build time from remote inventory files, and the resolved URLs are discovered like any other URL, so they appear in the baseline and are ignored in the diff. An unresolvable intersphinx reference is a Sphinx warning, not a linkcheck result.

## **Failure behavior**

If a step fails, `make linkcheck-diff` fails with a clear error. It never silently falls back to a full check.

- **The fetch fails** (for example, you are offline): the helper prints a warning and continues with the SHA from the last successful fetch. A baseline cached for that SHA is still used.
- **The base branch cannot be resolved** (no remote matches `github_url`, or the ref was never fetched): the helper errors out.
- **The baseline collection build fails** (broken `conf.py` on the base branch, dependencies that no longer install): the error propagates. There are no retries or workarounds.
- **The base branch contains broken links**: not a failure. See "Success criterion" below.

# **Architecture**

| Component             | Lives in                                                                      | Purpose                                                                                                                   |
| :-------------------- | :---------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------ |
| **Sphinx extension**  | `sphinx_linkcheck_diff` pip package, registered in `conf.py`                  | Given a baseline path, append its URLs to `linkcheck_ignore`. No git, no subprocesses, no state.                          |
| **Collection helper** | `sphinx_linkcheck_diff.sphinx_stack_baseline`, a single module in the package | Resolve the base head SHA, check the cache, and on a miss run the isolated collection. All git and JSON logic lives here. |
| **Makefile target**   | `docs/Makefile`                                                               | Call the helper, then run the linkcheck build with the baseline path.                                                     |
| **Baseline cache**    | `docs/_dev/.linkcheck-diff/baselines/`                                        | SHA-keyed baseline files. A cache hit is a file existence check.                                                          |

Principles behind the split:

- The extension is generic Sphinx. It knows one thing: the baseline path. It never learns where the file came from.
- The helper is specific to the Canonical Sphinx Stack: it assumes the Stack's Makefile targets and the standard `html_context` values. It is a single file so a project with a custom build can copy it into `docs/_dev/`, adapt it, and point the Makefile at the copy.
- The Makefile owns the user-facing build. The project's own variables and recipes do the work.
- A cache entry always matches the SHA in its file name, so a baseline can never be silently wrong for the base it claims. If the base moves, the new SHA misses and the collection runs again.
- Everything outside the cache directory is temporary. The worktree, venv, and build directory are removed after collection.

# **Sphinx extension (baseline filter)**

```py
app.add_config_value("linkcheck_diff_baseline", "", "linkcheck", (str,))
```

The rebuild domain is `linkcheck`, not `env`. Sphinx re-reads every doctree when an `env`\-domain value changes, and this value alternates between empty (`make html`) and a path (`make linkcheck-diff`). An `env` domain would force a full re-parse on each switch between the two commands.

The `builder-inited` handler:

1. If the builder is not `CheckExternalLinksBuilder`, return.
2. If `linkcheck_diff_baseline` is empty, return. The extension is dormant, so `make linkcheck` and `make html` are unaffected. Dormancy is only reachable through those commands: the `linkcheck-diff` target always passes a baseline, and the file check in the recipe fails the target before Sphinx starts if the helper produced nothing usable.
3. Load the baseline JSON. If the path doesn't exist, the file isn't valid JSON, or the JSON lacks a `uris` list, fail the build with an error naming the path. The make target guarantees a valid baseline before invoking Sphinx; this check catches hand-written invocations.
4. Append `^<re.escape(uri)>$` to `linkcheck_ignore` for each URI in the baseline.

Existing `linkcheck_ignore` entries in `conf.py` are preserved — the extension appends, never replaces.

Appending in `builder-inited` is sufficient: `Config.__getitem__` returns the live list object, and `HyperlinkAvailabilityChecker` compiles the patterns later, in `finish()`. No other hooks are needed.

# **Collection helper**

The helper is `sphinx_stack_baseline(sphinx_opts='')`, exported from the package root and defined in `sphinx_linkcheck_diff/sphinx_stack_baseline.py`. The Makefile invokes it with `python3 -c`. It resolves the docs directory and cache location from its working directory, so no paths are needed in the standard setup. It prints the baseline path to stdout and returns it; the Makefile captures the stdout.

The `sphinx_opts` argument carries the project's `SPHINX_OPTS` value. The helper forwards it to `make linkcheck` inside the worktree, so the collect build runs under the same settings as the project's real build.

The helper's flow:

1. Read `github_url` and `repo_default_branch` from `html_context` in the docs `conf.py`. It executes `conf.py` in a fresh namespace — the same file Sphinx executes on every build.
2. Find the remote: run `git remote -v` from the repo root and match remote URLs against `github_url`. Both HTTPS (`https://github.com/owner/repo`) and SSH (`git@github.com:owner/repo`) forms are matched, and the `.git` suffix is normalized on both sides, so no remote name is assumed.
3. Fetch the remote with `git fetch <remote>`, which updates the remote-tracking ref. The fetch runs with a timeout of about 30 seconds. DNS failures exit immediately with a clear message, but an unreachable host can block for minutes, and git's own HTTP timeout settings don't cover the TCP connect phase. If the fetch fails or times out, print a warning to stderr and continue with the tracking ref from the last successful fetch. Warnings go to stderr because stdout carries only the baseline path.
4. Resolve the base head SHA from the remote-tracking ref `<remote>/<repo_default_branch>`. If the ref can't be resolved, error out.
5. If the cache holds a baseline for this SHA, return its path.
6. Otherwise, collect one (below), write it to the cache, and return its path.

In both cases the path is printed to stdout, which is how the Makefile captures it.

## **Isolated baseline collection**

On a cache miss, the helper runs the collection inside a worktree, using the project's own targets:

1. Create a temporary `git worktree` of the base head SHA. Your working tree is not touched.
2. Run `make install` inside the worktree. The project's own install recipes create the venv and install the worktree's `requirements.txt`, so customized installs work unchanged.
3. Run `make linkcheck` inside the worktree, with `SPHINX_OPTS="<sphinx_opts> -D linkcheck_ignore=.*"`. The command-line override replaces the Makefile's `SPHINX_OPTS` wholesale; the forwarded opts keep the project's settings, and the ignore-all flag makes the build discover every URL without checking it. The override also replaces the base branch's own `linkcheck_ignore`, which `.*` makes harmless. Sphinx's `HyperlinkCollector` still discovers every URL and writes `output.json`.
4. Parse `output.json` (JSONL, one object per line) and extract the `uri` fields.
5. Remove the worktree, the venv, and the build directory.

The install dominates the collection time. The Sphinx build itself is a small fraction of it.
The success criterion is `output.json` existing, not the exit code. Sphinx writes all results to `output.json` before setting its failure exit code, so a base branch with broken links still produces a complete URL set. Harder failures (a bad `conf.py`, missing dependencies) produce no `output.json` at all, and the collection fails with the build's error output.

# **Baseline cache**

Baselines live at `docs/_dev/.linkcheck-diff/baselines/<sha>.json`, one file per base SHA. The `_dev` directory already holds regenerable build caches such as `.doctrees`, and this follows that convention. Add `_dev/.linkcheck-diff/` to `docs/.gitignore`.
Neither `make clean-doc` nor `make clean` removes the directory. Deleting it by hand is always safe — the next diff recollects.

Each baseline records its own SHA and collection time:

```json
{
  "base_sha": "a1b2c3d...",
  "collected_at": "2026-09-22T14:03:11+08:00",
  "uris": ["https://example.com/docs", "..."]
}
```

The SHA makes every entry self-describing: the file name, the `base_sha` field, and the base branch state always agree. The URIs are sorted, so rewriting a baseline for the same SHA always produces the same bytes.

# **Makefile target**

```
linkcheck-diff: install
	@CODE="from sphinx_linkcheck_diff import sphinx_stack_baseline; sphinx_stack_baseline('$(SPHINX_OPTS)')"; \
	BASELINE=$$(. $(DOCS_VENV); python3 -c "$$CODE"); \
	if [ ! -f "$$BASELINE" ]; then echo "linkcheck-diff: baseline collection failed" >&2; exit 1; fi; \
	. $(DOCS_VENV); $(SPHINX_BUILD) -b linkcheck "$(DOCS_SOURCEDIR)" "$(DOCS_BUILDDIR)" $(SPHINX_OPTS) -D linkcheck_diff_baseline="$$BASELINE" || { grep --color -F "[broken]" "$(DOCS_BUILDDIR)/output.txt"; exit 1; }
```

The target differs from `linkcheck` only in the baseline step and the `-D` flag. It does not pass `-q`: the per-URL output is the point of the command.

The recipe defines the Python invocation in a shell variable on its own line, then captures the helper's stdout on the next line. This flattens the quoting: the Python code sits in a double-quoted shell string with no command substitution around it, and `$(SPHINX_OPTS)` interpolates inside single quotes. The recipe is one shell invocation (the backslashes continue the line), so `$$BASELINE` carries the baseline path into the `-D` argument. The file check propagates a helper failure: a command substitution discards the exit code, so the only failure signal is bad stdout. The check requires an existing file, not just a non-empty string, so partial or garbage output can't reach the build. If the check fails, the target exits before Sphinx runs — a full check never happens.

# **Implementation and packaging**

The pip package is `sphinx-linkcheck-diff`, listed in `docs/requirements.txt`. It ships two modules:

- `sphinx_linkcheck_diff._extension` — the extension, registered as `sphinx_linkcheck_diff`.
- `sphinx_linkcheck_diff.sphinx_stack_baseline` — the collection helper, exported from the package root as `sphinx_stack_baseline`.

The helper is Stack-specific by design. A project that builds its docs differently copies `sphinx_stack_baseline.py` into `docs/_dev/`, adapts it, and points the Makefile recipe at the copy instead of the `python3 -c` import. The interface is the same: print the baseline path.

To adopt it in a project:

1. Add `sphinx-linkcheck-diff` to `docs/requirements.txt`.
2. Add `sphinx_linkcheck_diff` to the `extensions` list in `conf.py`.
3. Add the `linkcheck-diff` target to the `Makefile`, as shown above.

# **Known limitations**

1. **No re-checking existing links.** A URL that was fine when the baseline was collected but later rots is not caught. Use `make linkcheck` for a full check.
2. **The first diff for a base SHA is slow.** Collection is a venv install plus a full Sphinx build. Subsequent diffs reuse the cache.
3. **Requires an upstream remote and one successful fetch.** Without a remote matching `github_url`, or before the first fetch, the base SHA can't be resolved and the command errors. Here "upstream" means the repo the docs describe, discovered from `github_url` — which may be your fork.
4. **Assumes the Sphinx Stack Makefile targets.** The helper runs `make install` and `make linkcheck` inside the worktree. A project with different targets copies and adapts the helper (see "Implementation and packaging").

# **CI caching**

PR checks must not pay the baseline cost on every run. The cache directory holds one small JSON file per base SHA, and the helper re-resolves the base SHA and validates the file name on every run. A stale entry is a miss followed by recollection, never a wrong baseline. No invalidation logic is needed.
The workflow adds one step before `make linkcheck-diff`:

```
- uses: actions/cache@v4
  with:
    path: docs/_dev/.linkcheck-diff
    key: linkcheck-diff-${{ github.run_id }}
    restore-keys: |
      linkcheck-diff-
```

The key can't contain the base SHA, because the SHA isn't known until the run fetches. It doesn't need to be exact: `restore-keys` restores the branch's most recent cache directory, and the helper picks the `<sha>.json` file matching the current base out of it. If the base has moved, the file isn't there, so the run recollects and the post-step saves the updated directory.

Each PR populates its own cache. The first run of a PR collects; re-runs and pushes to the branch reuse the baseline for as long as the base SHA stays put. Runs on `main` reuse the same workflow unchanged: the SHA has just changed, so the restore misses and the run collects.
