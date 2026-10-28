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
regress it. (The three sample projects only pass by luck: their `tags` usage
is guarded behind environment variables.)

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
also pin the docs venv's interpreter (the integration tests pin it to the
repository's minimum Python, and collect their fixtures under it), or
accept that anchor URIs are interpreter-dependent as well.

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
