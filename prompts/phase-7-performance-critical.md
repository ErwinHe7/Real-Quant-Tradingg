# Phase 7 — Performance-Critical Hot Paths (Optional)

Prerequisite: read `prompts/00-agent-charter.md`. Phases 2-6 complete. This
phase is **optional** and should only be started when profiling proves
that Python performance is a real bottleneck for a real workload.

## Goal

Identify the small subset of code where Python is genuinely too slow, and
replace it with Rust (preferred) or C++ via PyO3 / pybind11. The point is
not to "use C++ because Jane Street uses C++". The point is to remove
specific measured bottlenecks.

## Why This Matters (And Why It Probably Doesn't)

For a retail swing/position strategy that:
- holds positions for days to weeks,
- rebalances at most a few times per day,
- trades tens to low-hundreds of names,

Python + NumPy + Pandas is faster than any reasonable trade horizon by
many orders of magnitude. Rewriting in C++ buys nothing.

The only places where a native rewrite is plausibly justified:
- the realtime feed handler if subscribing to several thousand symbols at
  tick frequency (we are not),
- the OPS algorithms during a wide parameter sweep where a single sweep
  takes hours (measure first),
- a covariance-matrix recomputation on a very wide universe.

## Required Reading

- charter
- profiling output you generate in this phase (see D1)

## Deliverables

### D1. Honest profiling

Before writing any non-Python code:
- pick the longest-running real workload (probably the full-universe
  parameter sweep from Phase 3),
- run it under `cProfile` and `py-spy --rate 1000`,
- write `artifacts/phase-7-profile.md` showing the top 20 hot functions
  by self-time and cumulative time, and the wallclock cost,
- identify functions where (a) the function takes >5% of total time AND
  (b) the operation is fundamentally numeric / loop-heavy / not already
  vectorised.

If no function clears that bar, **stop**. Document the conclusion and
end the phase. This is the right answer for almost any retail workload.

### D2. Rust extension (if D1 justified it)

If D1 surfaces a real hotspot:
- create `native/` with a Rust crate built via `maturin` and exposed as a
  Python module via PyO3,
- port the smallest possible function (one function, one file),
- write a benchmark `benches/<name>.py` comparing the Python and Rust
  implementations on representative inputs,
- add a property test that runs the same input through both and asserts
  numerical equivalence within tolerance.

Do **not** port "everything that looked slow". One function. Measure the
end-to-end speedup of the full workload. If it is <2x, the extension is
not worth the maintenance burden — delete it.

### D3. Build + CI

- `pyproject.toml` builds the Rust wheel as part of `pip install -e .`,
- CI builds and tests on Linux only (the owner's primary environment) —
  Windows / macOS support is not required for this project,
- the Python fallback for the same function stays in the repo and is
  used when the native extension is not built; tests run both paths and
  assert equivalence.

### D4. Documentation

`docs/NATIVE.md` documents:
- the specific bottleneck found,
- the speedup measured,
- how to build / debug,
- when to **not** add another native module (default: never).

## Acceptance Criteria

1. A profiling report exists. Decision (port or do not port) is justified
   by numbers, not by aesthetics.
2. If a port was done, end-to-end speedup of the originally chosen
   workload is documented and is at least 2x.
3. Tests cover both the Python and native paths.
4. The system still passes phase-5 paper-trading runs after the change.

## Out Of Scope

- rewriting the OMS or risk layer in a native language. They spend
  almost no time computing; they spend their time waiting on IO.
- OCaml. The owner asked about it because Jane Street uses it. Jane
  Street uses it because they have decades of internal libraries in it.
  We do not. Adding OCaml here is a vanity project, not an engineering
  decision.
- low-latency networking, FPGA, kernel-bypass, etc. These are
  retail-incompatible.

## Stop Conditions

Stop if you find yourself rewriting code that is already fast enough.
Stop if the build complexity is making the rest of the repo harder to
work on. Stop if a maintainer joining the project would find the native
layer surprising. The goal is to be faster where it matters and boring
everywhere else.
