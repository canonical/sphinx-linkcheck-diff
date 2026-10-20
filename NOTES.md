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
