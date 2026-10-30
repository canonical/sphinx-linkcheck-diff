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

1. **Ensure baseline.** The target calls the collection helper, which resolves the head SHA of the base branch and checks the cache. On a hit, the cached baseline is used. On a miss, the helper runs an isolated build of the base branch to collect its URLs and records the baseline.
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
- **The base branch contains broken links**: not a failure. The linkcheck build records every URI in `output.json` even when it exits nonzero, so the base branch's own broken links don't prevent collection.

# **Sphinx extension (baseline filter)**

```py
app.add_config_value("linkcheck_diff_baseline", "", "linkcheck", (str,))
```

The extension knows one thing: the baseline path. It never learns where the file came from, so you can feed it a baseline from anywhere.

The extension is dormant unless you run the linkcheck builder with the config value set: `make html` and `make linkcheck` are unaffected. In a linkcheck build with a baseline set, it loads the JSON, checks its shape, and appends each baseline URI to `linkcheck_ignore` as an anchored, escaped pattern. Invalid baseline data fails the build with an error naming the path.

Existing `linkcheck_ignore` entries in `conf.py` are preserved — the extension appends, never replaces.

# **Collection helper**

The helper is `sphinx_stack_baseline(sphinx_opts='')`, exported from the package root and defined in `sphinx_linkcheck_diff/sphinx_stack_baseline.py`. The Makefile invokes it with `python3 -c`. It resolves the docs directory and cache location from its working directory, so no paths are needed in the standard setup. It prints the baseline path to stdout and returns it. The Makefile captures the printed path.

The `sphinx_opts` argument carries the project's `SPHINX_OPTS` value. The helper forwards it to `make linkcheck` inside the worktree, so the collect build runs under the same settings as the project's real build.

The helper reads `github_url` and `repo_default_branch` from `html_context` in the docs `conf.py`, finds the git remote matching `github_url`, fetches it, and resolves the base head SHA from the remote-tracking ref. Warnings go to stderr, leaving stdout to the baseline path.

## **Isolated baseline collection**

On a cache miss, the helper builds the base branch's docs in a temporary git worktree, using the project's own `make install` and `make linkcheck` targets. Your working tree is not touched, and customized install recipes work unchanged.

The two make steps have no timeout. This is deliberate: CI can impose its own job-level timeout. Only the fetch is time-bounded.

The install dominates the collection time. The Sphinx build itself is a small fraction of it.

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

The SHA makes every entry self-describing: the file name, the `base_sha` field, and the base branch state always agree. The URI list is deduplicated and sorted, so re-collecting the same SHA reproduces the same URI list; `collected_at` records the time and differs between recollections.

# **Makefile target**

```
linkcheck-diff: install
	@export BASE_BRANCH; \
	CODE="from sphinx_linkcheck_diff import sphinx_stack_baseline; sphinx_stack_baseline('$(SPHINX_OPTS)')"; \
	BASELINE=$$(. $(DOCS_VENV); python3 -c "$$CODE"); \
	if [ ! -f "$$BASELINE" ]; then echo "linkcheck-diff: baseline collection failed" >&2; exit 1; fi; \
	. $(DOCS_VENV); $(SPHINX_BUILD) -b linkcheck "$(DOCS_SOURCEDIR)" "$(DOCS_BUILDDIR)" $(SPHINX_OPTS) -D linkcheck_diff_baseline="$$BASELINE" || { grep --color -F "[broken]" "$(DOCS_BUILDDIR)/output.txt"; exit 1; }
```

The target differs from `linkcheck` only in the `export BASE_BRANCH` line, the baseline step, and the `-D` flag. It does not pass `-q`: the per-URL output is the point of the command.

The recipe exports `BASE_BRANCH` into the helper's environment. The helper reads it and falls back to `repo_default_branch` when it's unset or empty, so which branch is the base is the author's intent: `make linkcheck-diff` uses the default branch, and `make linkcheck-diff BASE_BRANCH=1.19-maintenance` collects a maintenance branch's baseline instead. The environment is the right channel for the value: the helper's Python code is composed inside the recipe's double quotes, so a `$` in the value would be shell-expanded before Python sees it. The cache is keyed by SHA, so a repository's default- and maintenance-branch baselines coexist without invalidating each other.

If the helper produced no usable baseline, the file check fails the target before Sphinx runs.

# **Implementation and packaging**

The pip package is `sphinx-linkcheck-diff`, listed in `docs/requirements.txt`. It ships three modules:

- `sphinx_linkcheck_diff._extension` — the extension, registered as `sphinx_linkcheck_diff`.
- `sphinx_linkcheck_diff.baseline` — the library: the git and JSON plumbing (repo root, `conf.py` execution, remote matching, fetch and fallback, worktree, `output.json` parsing, cache, baseline writing), including the collection driver `collect`, which carries the Stack's defaults (`make install`, `make linkcheck`, `_build/output.json`).
- `sphinx_linkcheck_diff.sphinx_stack_baseline` — the policy module: the entry point and the `html_context` values it requires, exported from the package root as `sphinx_stack_baseline`.

The helper is Stack-specific by design. A project that builds its docs differently copies only `sphinx_stack_baseline.py` into `docs/_dev/` and edits its wiring: swap the `html_context` values, or replace a `baseline.*` call with a call to a local function that fits the build. The project then points its Makefile recipe at the copy instead of the `python3 -c` import. The interface is the same: print the baseline path.

To adopt it in a project:

1. Add `sphinx-linkcheck-diff` to `docs/requirements.txt`.
2. Add `sphinx_linkcheck_diff` to the `extensions` list in `conf.py`.
3. Add the `linkcheck-diff` target to the `Makefile`, as shown above.

# **Known limitations**

1. **No re-checking existing links.** A URL that was fine when the baseline was collected but later rots is not caught. Use `make linkcheck` for a full check.
2. **The first diff for a base SHA is slow.** Collection is a venv install plus a full Sphinx build. Subsequent diffs reuse the cache.
3. **Requires an upstream remote and one successful fetch.** Without a remote matching `github_url`, or before the first fetch, the base SHA can't be resolved and the command errors. Here "upstream" means the repo the docs describe, discovered from `github_url` — which may be your fork. A fork checkout fixes this with `git remote add upstream https://github.com/<org>/<project>`; the helper's error names the remedy.
4. **Assumes the Sphinx Stack Makefile targets.** The helper runs `make install` and `make linkcheck` inside the worktree. A project with different targets copies the policy module and adapts its wiring (see "Implementation and packaging").

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
