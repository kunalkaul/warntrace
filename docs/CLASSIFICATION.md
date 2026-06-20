# Warning classification

Warntrace assigns an **origin** to every captured warning by walking the stack,
mapping each frame to a package or to the Python standard library, then
traversing the dependency graph to determine the relationship to the project
root. This document describes each step in detail.

## Pipeline overview

```
captured warning stack
        │
        ▼
OwnershipChecker ─── maps each frame filename to an owner
  • application root (──root or CWD)
  • standard library paths (sysconfig)
  • site-packages / .venv / warntrace internals
        │
        ▼
DistributionIndex ─── resolves owned paths to package metadata
  • importlib.metadata.distributions() (primary)
  • importlib.metadata.packages_distributions() (fallback)
        │
        ▼
DependencyGraph ─── determines relationship to root project
  • direct dependency? (in project's Requires-Dist)
  • transitive dependency? (BFS shortest path to root)
  • unknown? (not reachable)
        │
        ▼
WarningClassifier ─── assigns origin + triggered_directly_by_application
```

## 1. Ownership detection

Source: `src/warntrace/ownership.py` — `OwnershipChecker`

The checker assigns every stack frame filename to one of three buckets:

### Application code

A file belongs to the application if its path is **under the project root**
(defaults to the child process's CWD, overridable with `--root`) AND is not
inside a `.venv`, `venv`, or `site-packages` directory. This excludes
installed dependencies and virtual-env internals while including all project
source files.

### Standard library

A file belongs to the standard library if its path matches any directory
returned by `sysconfig.get_paths()`. This covers everything CPython ships:
`os.py`, `pathlib.py`, `http`, `unittest`, etc.

### Installed distribution (package)

A file belongs to a package if its path is within `site-packages` (or
another `purelib`/`platlib` path). The specific package is resolved by the
DistributionIndex (see below).

### Warntrace internals

Frames inside the warntrace package itself are stripped from the stack
during `clean_stack()` *before* classification — they are never classified.
This keeps the stack clean of capture machinery.

### Unknown

A file that does not fall into any of the above categories is marked as
unknown. This can happen with dynamically generated files, files from
unusual `PYTHONPATH` entries, or paths that don't exist on disk.

## 2. Distribution index

Source: `src/warntrace/dependencies.py` — `DistributionIndex`

The index lazily builds a map from filesystem path to `DistributionInfo`
(name, normalized name, version) on the first query.

### Primary strategy

`importlib.metadata.distributions()` lists all installed distributions.
For each distribution, the index iterates over the files it owns (via
`dist.files`) and records the mapping from absolute file path to
distribution info.

### Fallback strategy

If the primary strategy fails (e.g., `dist.files` is empty for a
zip-unsafe package), the index falls back to
`importlib.metadata.packages_distributions()`, which maps top-level
import names to distributions. This is less precise but catches edge
cases.

### Caching

The index is built once and cached in a module-level dictionary. Repeated
lookups for the same path return instantly. The cache is process-scoped and
lives for the duration of the child process.

### Ambiguity

Namespace packages can have multiple distributions owning files in the same
top-level namespace. The index returns `None` (unknown) for ambiguous paths
rather than guessing.

## 3. Dependency graph

Source: `src/warntrace/dependencies.py` — `DependencyGraph`

The graph determines how each discovered package relates to the project root.

### Root detection

The root project is identified by reading the nearest `pyproject.toml` from
the project root directory (CWD or `--root`) and extracting `[project].name`.
If no `pyproject.toml` is found, the root is `None` and all dependencies are
classified as `unknown`.

### Graph construction

For every installed distribution, `importlib.metadata.requires()` returns
the `Requires-Dist` lines. Each line is parsed with
`packaging.requirements.Requirement` to extract the package name. Names are
canonicalized with `packaging.utils.canonicalize_name()`.

Only non-optional, non-extra requirements whose environment markers match
the current runtime are included.

The result is an adjacency map:
```python
{"canonical-root-name": {"dep-a", "dep-b", ...},
 "dep-a": {"sub-dep-c", ...}, ...}
```

### Path lookup

The `dependency_path_to_root(root, package_name)` method runs a BFS from
the package back to the root. If the package is a direct dependency of the
root, the path is `[root, package]`. If it is transitively reachable, the
path includes all intermediate packages. Unreachable packages return an
empty path.

Cycles are handled by a visited set in the BFS traversal.

## 4. Origin assignment

Source: `src/warntrace/classifier.py` — `WarningClassifier`

The classifier runs after capture is complete, as a post-process step on the
built report. For each `CapturedWarning`, it inspects the frame that emitted
the warning and assigns an origin according to these rules:

### `application`

The emitting frame's path resolves to the application root and is not inside
a virtual environment or site-packages.

### `direct_dependency`

The emitting frame's path resolves to an installed distribution, AND that
distribution is a direct dependency of the root project (found via
`DependencyGraph.is_direct_dependency()`).

### `transitive_dependency`

The emitting frame's path resolves to an installed distribution, AND that
distribution is reachable from the root through a chain of dependencies
(found via `DependencyGraph.dependency_path_to_root()`), but is not a direct
dependency.

### `standard_library`

The emitting frame's path matches a standard-library path from
`sysconfig.get_paths()`.

### `unknown`

None of the above — either the path cannot be mapped, the dependency graph is
unavailable, or the root project could not be identified.

## 5. `triggered_directly_by_application`

This boolean flag is set independently of the origin. It answers: *did
application code appear in the call stack between the warning emission and
the top of the stack?*

The classifier walks the cleaned stack from the emission frame upward,
looking for the first frame whose path is within the application root. If
such a frame is found, `triggered_directly_by_application` is set to `true`,
and that frame is recorded as `application_frame`.

This is useful for distinguishing between:
- A dependency that is emitting a warning on its own (e.g., a background
  thread in a library) — `triggered_directly_by_application` is `false`
- A dependency emitting a warning because your code called it —
  `triggered_directly_by_application` is `true`, making it actionable even
  though the origin is `direct_dependency`

The `--fail-on application` policy uses this flag: it matches both
`origin == "application"` AND
`triggered_directly_by_application == true`.
