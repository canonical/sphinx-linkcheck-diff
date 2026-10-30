# Notes

DESIGN.md records the design. This file names the behaviors that surprise in
use.

## 1. A reproducible baseline needs two pins

Two things outside the docs decide which `#` anchors a collected baseline
holds. The same base SHA can collect differently on different machines.

The first is read parallelism. In a parallel build, Sphinx splits the sorted
document list into chunks and merges each chunk's domain data in completion
order, so the same cross-reference can resolve to a different page. That
changes which anchors linkcheck discovers. A parallel build is not uniformly
different from a serial one. References whose pages land in the same chunk
resolve as in a serial build, so `-j auto` collects the serial set on one
machine and a different set on another. (On a pinned jubilant checkout: 69
anchors with `-j auto` on 14 cores, 70 with `-j 4`, 72 with `-j 1`.)

The second is the docs venv's Python. Autodoc introspects the project under
that venv's interpreter, and the same typehint cross-reference can resolve to
a different page under a different Python. (Same pin, `-j 1`: 73 anchors
under Python 3.10 and 3.12, 72 under 3.14.)

A serial build reads documents in sorted order and collects the same anchors
everywhere, so pin `-j 1` in `SPHINX_OPTS`. Pin the venv's interpreter too.
With both pins, a given SHA always collects the same baseline.

## 2. The baseline is the base's current head, not your fork point

The collector resolves the base branch's head at fetch time, however long
ago your feature branch forked from it.

The gap is mostly harmless on the base's side. Every link the base added or
changed after your fork point is in the baseline, so it is ignored. A link
that broke on the base after your fork point doesn't fail the run either:
that breakage is the base's own linkcheck problem.

The reverse bites. When the base fixes a link after your fork point, the old
URI drops out of the baseline. An un-rebased branch still carrying that URI
gets it checked, and it fails, though the branch never touched it. The
failure is loud and a rebase clears it. Until you know this, "it failed on a
link I didn't touch" reads like a bug.
