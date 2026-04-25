# Handoff Guide

## What Is Already Done

- the repo now has a GitHub-friendly frontend homepage
- the Python research harness supports both coursework and extension tracks
- the proposal algorithms are implemented
- the extension track includes ridge, attention, and deterministic optimization
- the pipeline writes machine-readable and human-readable artifacts

## What A Strong Next Engineer Should Build

### 1. Better Data Coverage

- add sector ETFs and factor ETFs as first-class supported universes
- add cached local data storage to reduce repeated downloads
- optionally support Polygon, Alpha Vantage, or broker historical APIs

### 2. Better Proposal Diagnostics

- parameter sweeps for `eta`, `beta`, `epsilon`, `M`, and window lengths
- regime-conditioned performance tables
- cumulative regret plots versus BCRP

### 3. Better Industry Extension

- richer factor library
- residual momentum, beta, correlation, and risk features
- stronger transformer model with a controlled training loop
- paper broker integration

### 4. Better Agent Layer

- persistent experiment memory
- explicit task queue for feature / validation / risk / report agents
- artifact diffing across runs

## What Must Stay True

- the live path stays deterministic
- proposal-core algorithms stay training-free and online
- BCRP stays clearly marked as an offline oracle benchmark
- transaction costs and turnover remain first-class evaluation inputs

## Recommended Near-Term Priorities

1. Add parameter sweep scripts and plots for the proposal track.
2. Add a paper-trading adapter with strict risk gates.
3. Add richer feature engineering to the ML extension.
4. Add CI for both frontend build and research smoke tests.
