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
