# Warntrace

Trace the origin of Python warnings — classify them by ownership (application, direct
dependency, transitive, stdlib), suppress noise, and fail CI when policy is violated.

## Installation

```bash
uv add --dev warntrace
# or
pip install warntrace
```

Requires Python >= 3.10.

## Quick start

```bash
# Capture warnings from any Python command
warntrace run python your_script.py

# Capture warnings from your test suite
warntrace run pytest
```

Warntrace intercepts every `warnings.warn()` call in the child process, classifies each
warning by origin, and writes a JSON report to stdout after the child exits.

## CLI reference

```
warntrace run [options] -- <command> [args...]
```

| Flag | Default | Description |
|---|---|---|
| `--format` | `json` | Output format: `json`, `detailed`, or `summary` |
| `--output FILE` | stdout | Write report to a file instead of stdout |
| `--max-frames N` | unlimited | Limit stack frames per warning in terminal output |
| `--show-all` | off | Capture normally-suppressed warnings (e.g. `BytesWarning`) |
| `--no-passthrough` | off | Suppress original warning output from the child process |
| `--fail-on POLICY` | off | Exit code 3 when a warning matches the policy (see below) |
| `--root PATH` | child's CWD | Application root directory for classification |
| `--no-color` | off | Disable ANSI color in terminal output |

### Examples

```bash
# Basic — run a script and see the default JSON report
warntrace run python -c "import warnings; warnings.warn('hello')"

# Detailed terminal output with limited stack frames
warntrace run --format detailed --max-frames 5 pytest

# Summary — one line per warning with total counts
warntrace run --format summary pytest

# Write report to a file (no ANSI codes in file output)
warntrace run --output report.json pytest

# Collect all warnings silently, even normally-suppressed ones
warntrace run --no-passthrough --show-all pytest

# Fail CI when application-origin warnings are found
warntrace run --fail-on application pytest

# Treat triggered dependency warnings as application-level too
warntrace run --fail-on application pytest

# Fail on any warning (application + deps + stdlib + unknown)
warntrace run --fail-on all pytest

# Opt out of policy failure explicitly
warntrace run --fail-on none pytest

# Specify granular origins to fail on
warntrace run --fail-on direct_dependency transitive_dependency pytest

# Combined: silent, fail on app warnings, save report
warntrace run --no-passthrough --fail-on application --output ci-report.json pytest
```

## Python API

```python
from warntrace import capture_warnings

with capture_warnings() as tracer:
    import warnings
    warnings.warn("something is deprecated", DeprecationWarning)

report = tracer.stop()
print(report.to_dict())
```

The context manager installs the capture hook, runs your code, restores the
original warning state, and returns a classified `WarningReport`. The report
contains the full warning list with origin, stack, dependency paths, and
occurrence counts.

### Lower-level API

```python
from warntrace import WarningTracer

tracer = WarningTracer(show_all=True, passthrough=False)
tracer.start()
# ... your code ...
report = tracer.stop()
print(report.to_dict())
```

### Configuration

| Parameter | Default | Description |
|---|---|---|
| `root` | `Path.cwd()` | Application root for origin classification |
| `show_all` | `False` | Capture normally-suppressed warning types |
| `passthrough` | `True` | Forward warnings to the original handler |

## Output formats

### JSON (default)

```json
{
  "schema_version": "0.1",
  "summary": {
    "unique_warnings": 2,
    "total_occurrences": 5,
    "application": 1,
    "direct_dependency": 1,
    "transitive_dependency": 0,
    "standard_library": 0,
    "unknown": 0
  },
  "warnings": [
    {
      "category": "DeprecationWarning",
      "message": "use foobar() instead of deprecated_func()",
      "origin": "direct_dependency",
      "triggered_directly_by_application": true,
      "occurrences": 3,
      "emitted_from": {
        "filename": "/path/to/site-packages/oldpkg/utils.py",
        "lineno": 42,
        "distribution": {
          "name": "oldpkg",
          "normalized_name": "oldpkg",
          "version": "1.2.3"
        }
      },
      "application_frame": {
        "filename": "/home/user/project/app.py",
        "lineno": 15,
        "function": "run",
        "source_line": "oldpkg.deprecated_func()"
      },
      "dependency_path": [
        {"name": "myproject", "normalized_name": "myproject", "version": null},
        {"name": "oldpkg", "normalized_name": "oldpkg", "version": "1.2.3"}
      ],
      "stack": [
        {"filename": "/home/user/project/app.py", "lineno": 15, "function": "run", "source_line": "oldpkg.deprecated_func()"},
        {"filename": "/path/to/site-packages/oldpkg/utils.py", "lineno": 42, "function": "deprecated_func", "source_line": "warnings.warn(...)"}
      ]
    }
  ]
}
```

### Detailed terminal output

```
warntrace report — 1 unique warning, 3 total occurrences

─── Warning 1 of 1 ───────────────────────────────────────────────────────────
  Origin:        !  direct_dependency (triggered by your code)
  Category:      DeprecationWarning
  Message:       use foobar() instead of deprecated_func()
  Location:      oldpkg/utils.py:42
  Occurrences:   3
  Application:
    myproject/app.py:15  run()
      -> oldpkg.deprecated_func()
  Dependency path:
    myproject → oldpkg 1.2.3
  Stack:
     1  myproject/app.py:15  run()
     2  oldpkg/utils.py:42  deprecated_func()
```

### Summary output

```
  application       1  DeprecationWarning: use foobar() instead...
  direct_dependency  3  DeprecationWarning: use foobar() instead...
────────────────────────────────────────────────────────
warntrace report — 2 unique warnings, 4 total occurrences
```

## Classification

Warntrace assigns an **origin** to every captured warning by walking the stack and
mapping each frame to a package or to the Python standard library. There are five
origin levels:

| Origin | Meaning |
|---|---|
| `application` | The warning was emitted from your own code (under the project root) |
| `direct_dependency` | The warning was emitted by a package listed in your dependencies |
| `transitive_dependency` | The warning was emitted by a dependency of one of your dependencies |
| `standard_library` | The warning was emitted from CPython stdlib |
| `unknown` | The file could not be mapped to any known package |

Additionally, each warning has a `triggered_directly_by_application` boolean.
This is `true` when an application frame appears in the call stack below the
warning emission — meaning your code called the code that warned, even if the
warning itself comes from a dependency.

See `docs/CLASSIFICATION.md` for the detailed pipeline documentation.

## CI integration

Policies are expressed via `--fail-on`:

| Policy | Warnings that trigger failure |
|---|---|
| `none` | Never (explicit opt-out) |
| `application` | Origin is `application` **or** `triggered_directly_by_application` is true |
| `direct` | Origin is `application` or `direct_dependency` |
| `all` | Any captured warning |
| *(individual origins)* | `direct_dependency`, `transitive_dependency`, `standard_library`, `unknown` |

Exit codes:

| Code | Meaning |
|---|---|
| 0 | Success — no policy failure |
| 2 | Warntrace usage error (e.g. missing command) |
| 3 | Policy matched — warnings exceed the configured threshold |

> Child-process failure (e.g. pytest test failures) takes priority over policy:
> if the child exits non-zero, that exit code is returned even when a policy
> would have matched.

### Example: CI workflow

```yaml
# .github/workflows/ci.yml
- run: warntrace run --no-passthrough --fail-on application --output warnings.json pytest
```

The test suite runs normally. If any application-origin or application-triggered
warnings are found, the step exits with code 3. The full report is saved to
`warnings.json` for inspection.

## Privacy

Warntrace makes **no network requests**. All analysis is local. It reads:
- Your project's dependency metadata (`importlib.metadata`)
- The filesystem path of each stack frame
- Environment variables (for configuration only)

No data is collected, logged, or transmitted.

## Known limitations

- **Pytest stack frames.** Under pytest, captured stacks include ~30 frames of
  pytest/pluggy internals. Use `--max-frames` to limit terminal output.
- **Self-testing.** Running `warntrace run pytest` on warntrace's own test suite
  reports 0 warnings because the test files manipulate capture state at import
  time. This does not affect normal projects.
- **Dependency graph accuracy.** The graph is built from installed package
  metadata (`Requires-Dist`). Optional/extra dependencies are excluded.
  Namespace packages with ambiguous ownership return `unknown`.
