# Configuration Reference

## CLI Flags

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--format FMT` | string | `text` | Output format: `text`, `json`, `github`, `sarif`, `junit`, `gitlab` |
| `--json` | flag | — | Deprecated alias for `--format json` |
| `--min-severity SEV` | string | `info` | Only display findings at or above this severity: `info`, `warning`, `error` |
| `--fail-on SEV` | string | `error` | Exit 1 if any finding meets or exceeds this severity: `info`, `warning`, `error` |
| `--select CODES` | string | — | Only run these checks (comma-separated SC codes, e.g. `SC701,SC601`) |
| `--ignore CODES` | string | — | Skip these checks (comma-separated SC codes, e.g. `SC601,SC202`) |
| `--scope SCOPE` | string | — | Only show findings of this scope: `file`, `cross_file`, `metric` |
| `--explain [CODE]` | string | — | Show rule docs: `SC701` (single), `SC4` (family), or `all` |
| `--baseline PATH` | path | — | Compare against baseline; only report new findings |
| `--generate-baseline` | flag | — | Output a JSON baseline of current findings to stdout |
| `--plan` | flag | — | Show a phased refactoring plan and exit |
| `--diff REF` | string | — | Only scan files changed since REF (e.g. `main`, `HEAD~1`) |
| `--changed-only` | flag | — | Shorthand for `--diff HEAD` (uncommitted changes) |
| `--no-cache` | flag | — | Disable file-level caching |
| `--cache-dir PATH` | path | `.smellcheck-cache` | Custom cache directory |
| `--clear-cache` | flag | — | Delete cached results and exit |
| `--version` | flag | — | Show version and exit |
| `-h`, `--help` | flag | — | Show help and exit |

## pyproject.toml Configuration

smellcheck reads `[tool.smellcheck]` from the nearest `pyproject.toml`. CLI flags override config values.

```toml
[tool.smellcheck]
format = "text"
min-severity = "info"
fail-on = "error"
select = ["SC701", "SC601"]
ignore = ["SC202"]
baseline = ".smellcheck-baseline.json"
cache = true
cache-dir = ".smellcheck-cache"
extends = "base.toml"
```

### Config Inheritance

Use `extends` to inherit from a shared config file:

Single base:

```toml
[tool.smellcheck]
extends = "base.toml"
```

Multiple bases (later file wins on conflict):

```toml
[tool.smellcheck]
extends = ["base.toml", "strict.toml"]
```

Paths are relative to the file containing the `extends` key. Maximum chain depth is 5.

### Merge Strategy

When extending configs:

| Key | Strategy |
|-----|----------|
| `select` | Override (child replaces parent entirely) |
| `ignore` | Union (deduplicated, base order preserved, new codes appended) |
| `per-file-ignores` | Deep merge (same glob unions codes) |
| `fail-on`, `format`, `baseline`, `cache`, `cache-dir` | Override (child wins) |
| `extends` | Consumed and stripped |

## Inline Suppression

### Line-level

```python
x = input("name")  # noqa: SC203
x = input("name")  # noqa: SC203,SC601  (multiple codes)
x = input("name")  # noqa                (all rules)
```

### Block-level

```python
# smellcheck: disable SC701
# ... code exempt from SC701 ...
# smellcheck: enable SC701
```

### File-level

```python
# smellcheck: disable-file SC701    (at top of file)
# smellcheck: disable-all           (disable everything)
# smellcheck: enable-all            (re-enable)
```

## Exit Code Semantics

| Code | Meaning |
|------|---------|
| `0` | No findings at or above the `--fail-on` severity level |
| `1` | At least one finding meets or exceeds the `--fail-on` severity, or an error occurred |

The default `--fail-on` is `error`, so smellcheck exits 0 unless an error-severity finding is detected.

## Flag Interactions

- **`--select` + `--ignore`**: `--select` runs first (whitelist), then `--ignore` removes from that set. If only `--ignore` is provided, all rules run except the ignored ones.
- **`--plan` + `--generate-baseline`**: Mutually exclusive. Using both produces an error.
- **`--diff` + `--generate-baseline`**: Mutually exclusive. A diff-scoped scan covers only changed files, so the resulting baseline would be incomplete. Run `--generate-baseline` without `--diff` to capture the full codebase baseline.
- **`--diff` + cross-file checks**: Cross-file checks run on the changed file set only (best-effort). For full accuracy, run without `--diff` periodically.
- **`--min-severity` vs `--fail-on`**: `--min-severity` controls display filtering. `--fail-on` controls the exit code. You can display all findings (`--min-severity info`) but only fail on warnings (`--fail-on warning`).

## JSON Output Schema

When using `--format json`, each finding is serialized as:

```json
{
  "file": "src/example.py",
  "line": 42,
  "pattern": "SC701",
  "name": "Use Context Manager",
  "severity": "warning",
  "message": "Use a context manager for 'open' (SC701)",
  "category": "idioms",
  "scope": "file"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `file` | string | Path to the source file (as passed to the CLI or resolved by the scanner) |
| `line` | int | Line number where the smell was detected |
| `pattern` | string | SC code (e.g. `SC701`) |
| `name` | string | Human-readable rule name |
| `severity` | string | `info`, `warning`, or `error` |
| `message` | string | Detailed description of the finding |
| `category` | string | Rule family: `state`, `functions`, `types`, `control`, `architecture`, `hygiene`, `idioms`, `metrics` |
| `scope` | string | Detection scope: `file`, `cross_file`, or `metric` |

## Baseline JSON Schema

Generated by `--generate-baseline`:

```json
{
  "version": "X.Y.Z",
  "generated": "YYYY-MM-DDTHH:MM:SSZ",
  "findings": [
    {
      "fingerprint": "a1b2c3d4e5f67890",
      "file": "src/example.py",
      "pattern": "SC701",
      "line": 42,
      "name": "Use Context Manager"
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `version` | string | smellcheck version that generated the baseline |
| `generated` | string | ISO 8601 UTC timestamp |
| `findings[].fingerprint` | string | Line-number-resilient hash (file + pattern + normalized message) |
| `findings[].file` | string | Relative path from scan root |
| `findings[].pattern` | string | SC code |
| `findings[].line` | int | Line number (informational, not used for matching) |
| `findings[].name` | string | Rule name |

Baseline matching uses fingerprints, not line numbers, so findings survive minor edits.

## Plan JSON Schema

Generated by `--plan --format json`:

```json
{
  "strategy": "local_first",
  "phase_order": [0, 1, 2, 3, 4, 5, 6, 7, 8],
  "total_findings": 15,
  "total_rules_hit": 8,
  "phases": [
    {
      "number": 0,
      "name": "phase_name",
      "label": "Phase 1 — Label",
      "description": "What this phase covers",
      "status": "active",
      "skip_reason": null,
      "finding_count": 5,
      "rules_hit": {"SC701": 3, "SC601": 2},
      "select_cmd": "SC701,SC601",
      "execution": "per-file",
      "internal_order": [["SC701", "SC604"], ["SC403", "SC406"]],
      "gate": "zero findings in phase",
      "rescan_after": true,
      "feedback_to": [],
      "max_loops": 3
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `strategy` | string | `local_first` or `architecture_first` |
| `phase_order` | int[] | Execution order of phase indices |
| `total_findings` | int | Total findings across all phases |
| `total_rules_hit` | int | Count of distinct SC codes triggered |
| `phases[].status` | string | `active` (has findings) or `skip` (empty) |
| `phases[].select_cmd` | string | Comma-separated SC codes for `--select` |
| `phases[].execution` | string | Execution strategy for the phase |
| `phases[].rescan_after` | bool | Whether to re-scan after completing this phase |
