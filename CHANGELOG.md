# Changelog

## v0.1.0.post1 — 2026-06-20

- Fix author email in pyproject.toml.

## v0.1.0 — 2026-06-20

Initial release of Warntrace — a lightweight CLI and Python library for
diagnosing Python runtime warnings.

### Features

- **Warning capture** — intercepts warnings via `warnings.showwarning` hook
  and `warnings.warn` wrapper (handles pytest replacing `showwarning`).
- **Deduplication** — groups identical warnings by stable fingerprint
  (category + normalized message + emission location + first app call site).
- **Path classification** — detects application roots, standard-library
  paths, and virtual-environment boundaries.
- **Distribution ownership** — maps warning-emitting files to installed
  packages via `importlib.metadata.distributions()` with lazy caching.
- **Dependency graph** — builds an installed-dependency graph from
  `importlib.metadata.requires()` and classifies warnings as direct or
  transitive dependencies using BFS shortest-path.
- **Classification** — five origins (application, direct dependency,
  transitive dependency, standard library, unknown) plus
  `triggered_directly_by_application` boolean.
- **Python API** — `capture_warnings()` context manager and `WarningTracer`
  class with start/stop/report lifecycle.
- **CLI** — `warntrace run` injects capture into child processes via
  `sitecustomize.py` and `PYTHONPATH`, preserves child exit codes.
- **Rendering** — detailed, summary, and JSON output with ANSI color,
  path shortening, and message wrapping.
- **Pytest compatibility** — tested with `warntrace run pytest`, all common
  flags (`-x`, `-k`, `-W`, `pytest.ini` `filterwarnings`).
- **CI integration** — `--fail-on` policy with levels
  (`none`/`application`/`direct`/`all`) and per-origin selection; exit
  code 3 on policy match.
- **Privacy** — never captures locals, arguments, or secrets; no network
  requests; all processing local.
