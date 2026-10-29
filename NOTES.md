# Notes on the design

Suggestions for DESIGN.md, which is frozen and therefore not edited directly.
Each arose from implementing and validating the collection helper against
canonical/sphinx-stack-docs, canonical/jubilant, and canonical/pebble.

## 1. The conf.py namespace must include `__file__` and a `Tags` instance

DESIGN.md says the helper executes the base branch's conf.py to read
`html_context`, but does not specify the namespace it runs in. Sphinx's
`eval_config_file` always provides `__file__` and a `Tags` object, so a
conf.py may call `tags.add()` or `tags.has()` unconditionally. A helper
that executes conf.py without a `Tags` instance crashes on such files.

The helper therefore mirrors Sphinx and executes conf.py with:

```python
{"__file__": str(conf_path), "tags": Tags()}
```

The design should state this requirement so future implementations don't
regress it. (The three Stack sample projects only pass by luck: their `tags`
usage is guarded behind environment variables. The fourth, microcloud,
genuinely exercises the requirement: its `tags.add('integrated')` runs
whenever `SINGLE_BUILD` is unset, which is the helper's case.)

## 2. Baseline URIs are deduplicated; byte-stability holds only for the URI list

Sphinx's linkcheck `output.json` contains one line per (document, URI) pair,
so a URI referenced from several documents appears several times. The helper
deduplicates and sorts the URIs before writing the baseline, which is what
makes rewrites of an unchanged baseline byte-stable.

The design should state the dedup-and-sort step explicitly. It should also
note that `collected_at` differs between recollections, so byte-stability
strictly holds only for the URI list, not the whole baseline file.

## 3. Only the fetch has a timeout; `make install` and `make linkcheck` can hang

The helper wraps `git fetch` in a timeout (30 seconds) and falls back to
cached refs on failure. The collection steps — `make install` and
`make linkcheck` in the worktree — have no timeout: a hung network
operation or build leaves the helper running indefinitely.

This is a deliberate scope decision (the design's success criterion is that
`output.json` exists, and CI can impose its own job-level timeout), but the
design should record it so it reads as a choice rather than an oversight.

## 4. The collected anchor set depends on Sphinx's read parallelism

The design says the helper forwards the project's `SPHINX_OPTS` to the
collection build, and the Stack's default is `-j auto`. But with parallel
reads Sphinx splits the sorted document list into chunks of
`len(docnames) // nproc` documents and merges each chunk's domain data in
completion order, and cross-reference resolution picks the first match in
that order — so which page a reference resolves to, and therefore which `#`
anchors linkcheck collects, varies with the machine's core count. (Observed
on jubilant at a pinned SHA: 69 anchors with `-j auto` on 14 cores, 72 with
`-j 1`, 70 with `-j 4`.) A parallel build is not uniformly different from a
serial one, though: references whose pages land in the same chunk resolve
as in a serial build. On a 4-vCPU CI runner jubilant's 15 documents give a
chunk size of 3, the reference pages share a chunk, and `-j auto` collects
the serial set.

The design should state that callers needing a reproducible baseline must
pin `-j 1` (a serial build reads documents in sorted order and collects the
same set everywhere), or accept that anchor URIs are machine-dependent.

## 5. The collected anchor set also depends on the docs venv's Python

The Stack's Makefile builds the docs venv with whatever `python3` is first
on PATH, and autodoc introspects the project under that venv's interpreter.
The same typehint cross-reference can resolve to a different page — and so
a different anchor — under a different interpreter. (Observed on jubilant at
a pinned SHA with `-j 1`: `Juju.show_secret`'s `-> RevealedSecret` typehint
resolves cross-page to the defining module under Python 3.10 and 3.12,
which linkcheck collects, but same-page to the `__init__.py` re-export under
Python 3.14, which linkcheck does not.)

This is independent of the parallelism in §4: the same serial build
collects 73 anchors under Python 3.10 and 3.12 but 72 under 3.14, and under
3.14 the same project collects 72, 70, or 69 anchors at `-j 1`, `-j 4`, and
`-j auto`. A reproducible baseline needs both pins.

The design should state that callers needing a reproducible baseline must
also pin the docs venv's interpreter (the functional tests pin each project
to its own docs requirements' minimum Python — 3.10 for the Stack projects,
3.11 for microcloud, whose `sphinx-autobuild` pin needs it — and collect their
fixtures under it), or accept that anchor URIs are interpreter-dependent as
well.

## 6. The plumbing is library functions; only the policy module is copied

DESIGN.md describes the collection helper as a single module where "All git
and JSON logic lives", which a project with a custom build copies wholesale
into `docs/_dev/` and adapts. In practice nearly all of that file is plumbing
that never varies: resolving the repository root, executing `conf.py`,
matching the remote, fetching with the cached-refs fallback, the temporary
worktree, parsing `output.json`, and the baseline cache. Only a handful of
decisions vary with the build: which `html_context` values are required, which
Makefile targets build the docs, how `SPHINX_OPTS` is composed for the
collection build, and where the build writes `output.json`.

The package therefore exposes _all_ helpers as library functions in
`sphinx_linkcheck_diff.baseline`, including the collection driver `collect`
(which carries the Stack's defaults: the `install` and `linkcheck` Makefile
targets and `_build/output.json`) and the required-`html_context`-value
lookup `setting`. `sphinx_stack_baseline.py` is reduced to pure wiring: the
entry point and the `html_context` values it requires. A project that builds
its docs differently copies only that module into `docs/_dev/`, adapts the
wiring, and defines module-local versions of any library function whose
defaults don't fit — the entry point calls the module-local version, which
shadows the library's. The design should be updated to say the package ships
every helper as a library module and that the copy surface is the policy
module alone. The entry point `sphinx_stack_baseline(sphinx_opts)` and its
stdout contract are unchanged, as is the baseline content: the library's
`write_baseline` performs the same deduplicate-and-sort the helper did.

## 7. The base branch comes from `BASE_BRANCH`, falling back to `repo_default_branch`

DESIGN.md resolves the base branch as `repo_default_branch` from
`html_context`: the repository's default branch. A repository with a
maintenance branch (`1.19-maintenance`, say) has docs that differ
significantly from the default branch's, and a feature branch may be intended
to merge into either. Which one is the base is the author's intent, not
something the helper can detect: a backport descends from the default branch,
so ancestry can't distinguish "based on" from "targets", and a branch can
legitimately target either.

The Makefile target therefore takes the base branch as an optional argument.
Make targets can't take arguments; the idiomatic equivalent is a variable on
the command line, and the recipe routes it to the helper through the
environment: the Makefile exports `BASE_BRANCH`, and the helper reads it,
falling back to `repo_default_branch` when it's unset or empty. The design's
Makefile snippet gains one line:

```
export BASE_BRANCH
```

`make linkcheck-diff` is unchanged: `BASE_BRANCH` is empty, so the base branch
is `repo_default_branch`. `make linkcheck-diff BASE_BRANCH=1.19-maintenance`
collects that branch's baseline instead. The environment is the right channel
for the value: the alternative, interpolating it into the Python code like
`$(SPHINX_OPTS)`, passes through the recipe's double quotes, where the shell
would expand a `$` in a refname before Python sees it; the environment hands
the bytes through untouched. (GNU make exports command-line variables to
recipes on its own, but the explicit `export` also covers a `BASE_BRANCH`
assignment inside the Makefile.)

The rest of the design is unchanged: `fetch` already fetches every branch,
`base_sha` resolves any `remote/<branch>`, and the baseline cache is keyed by
SHA, so a repository's default- and maintenance-branch baselines coexist
without invalidating each other. An unknown branch fails where it always did,
in `git rev-parse`, with git's own error.

## 8. End-to-end trial findings (jubilant, `linkcheck-trial`)

The full design was proven end-to-end in a jubilant checkout with the
extension blocked out as a project-local module (`docs/_dev/linkcheck_diff_ext.py`,
loaded via a `sys.path.insert` in `conf.py`) and the package's dev version
editable-installed into the docs venv. Baseline collection (first run:
auto-collected from `upstream/main` in the worktree), the filtered build
(69 URIs all `-ignored-`, zero HTTP checks), broken-link detection (changed
URL, new URL, and a Python-docstring URL all flagged `[broken]` with the
target exiting 1), `BASE_BRANCH` routing (vs `jubilant-backports`: a second
baseline collected, cached alongside the first, and the URL set checked
changed accordingly), and cache hits (ensure-baseline ≈ 2s) all behaved as
designed. Alternating `make html` and `make linkcheck-diff` never re-parsed
sources. The findings the implementation must carry:

1. **`'linkcheck'` is not in Sphinx's rebuild-domain typing.**
   `Config.add` performs no runtime validation — `environment/__init__.py`
   invalidates only config values whose `rebuild` is `'env'`
   (`config.filter(frozenset({'env'}))`), so the design's no-re-parse claim
   holds — but mypy rejects the call against Sphinx's `_ConfigRebuild`
   `Literal['', 'env', 'epub', 'gettext', 'html', 'applehelp', 'devhelp']`.
   The shipped extension needs a `# type:` suppression or cast at this one
   call.

2. **A fork checkout needs a `git remote` matching `conf.py`'s `github_url`.**
   The collector matches remotes against `github_url`; a gimmegit checkout of
   a fork has only `origin` = fork, while jubilant's `conf.py` says
   `https://github.com/canonical/jubilant`. Adding
   `git remote add upstream https://github.com/canonical/jubilant` resolves
   it without touching `conf.py` — the mechanism DESIGN.md's limitation 3
   anticipates ("which may be your fork").

3. **`linkcheck_retries` dominates the broken-link run's wall time.**
   jubilant's `conf.py` sets `linkcheck_retries = 3`; a rate-limited broken
   GitHub URL sleeps through retries, so a run with broken links takes minutes
   even though the baseline step is instant. Not a defect — but worth knowing
   when interpreting CI timings.

## 9. Extension dormancy and the filtered build both verified

`make html` and `make linkcheck` (with `-D linkcheck_ignore=.*`) both succeed
with the extension loaded and `linkcheck_diff_baseline` unset: the handler
returns before reading anything, so nothing outside `linkcheck-diff` is
affected. The filtered build shows each baseline URI exactly once as
`-ignored-` (including conf.py-appended `linkcheck_ignore` entries, which are
simply never reached) and checks zero URLs when the docs match the base.

## 10. Adversarial trial findings (extension)

The extension was attacked as a black box in the Jubilant simulation, with
trial URIs designed as near-misses of the baseline (prefix extensions, query
additions, subdomain swaps, substring embeds) and as regex metachar traps
(`*`, `+`, `%`-encoded brackets, punycode hosts). All 11 trials behaved as
designed: exact recorded forms stay ignored, every near-miss is reported
broken. The findings the landed extension carries:

1. **URI normalization happens before the extension sees anything.**
   MyST/docutils percent-encode brackets (`q[e]` → `q%5Be%5D`) and punycode
   unicode hosts (`canonicãl.example` → `xn--canonicl-xza.example`) at
   reference-extraction time, so output.json records normalized forms. The
   pipeline is symmetric — a collected baseline holds the same normalized
   forms the filtered build compares against — so a hand-written baseline in
   keyboard form simply never matches anything. No extension-side change;
   the escape/anchor semantics are what matter, and they held.

2. **`str()` coercion of the baseline path.** Sphinx warns at `config-inited`
   when `linkcheck_diff_baseline` has a wrong type but passes the value
   through, so the handler previously crashed with a bare `TypeError` from
   `Path()` on values such as `42`. The handler now stringifies first and
   fails with "can't read baseline 42" instead.

3. **Non-string `uris` entries fail loudly.** A hand-edited baseline holding
   say `13` in `uris` previously produced a garbage pattern `^13$`; now it
   fails the build naming the entry.

4. **Conf.py's `linkcheck_ignore` may be a tuple.** Sphinx accepts both list
   and tuple; `.extend()` on a tuple crashed with `AttributeError`. The
   handler rebuilds the list instead of mutating it: existing entries first,
   then anchored, escaped baseline patterns.

The rebind is safe because linkcheck's `HyperlinkAvailabilityChecker` reads
`linkcheck_ignore` once, in its constructor, which runs in `finish()` — after
`builder-inited` fires. Sphinx deep-copies config defaults per app, so
rebinding never leaks into later builds.

## 11. The baseline is the base branch's current head, not the fork point

DESIGN.md has the helper "resolve the head SHA of the base branch": the
base branch's head at fetch time, however long ago the feature branch
forked from it. The consequences of that gap deserve a place in the
design.

The gap is mostly harmless on the base branch's side. Every link the base
branch added or changed after the fork point is in the baseline and so
ignored. A link that broke on the base branch after the fork point
doesn't fail the run either: it is the base's breakage, and the base
branch's own linkcheck owns it.

The reverse bites. When the base branch fixes a link after the fork
point — old URI out, new URI in — the baseline holds only the new URI.
An un-rebased branch still carrying the old one has it checked, and it
fails, even though the branch never touched that link. `BASE_BRANCH`
doesn't address this: it chooses which branch to resolve, but still
resolves that branch's current head.

The failure is loud and a rebase clears it, so this is branch hygiene,
not a helper defect. The design should state the resolution rule and name
the un-rebased failure mode, because "it failed on a link I didn't touch"
reads like a bug until you know it.
