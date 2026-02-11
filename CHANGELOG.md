# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-02-11

### Fixed
- Import analysis now captures full dotted paths, fixing under-reporting of #CYC, #UDE, #FIO on package-based repos
- RFC metric counts distinct external method calls (not class names), correctly measuring response set size
- elif chains no longer produce duplicate #014 and #068 findings
- #058 no longer false-positives on `ExitStack.enter_context(open(...))`
- Single-file scans now run per-class OO metrics (LCOM, CBO, RFC, MID)
- CLI docs updated with correct script path from repo root
- Corrected detection counts: 40 per-file + 10 cross-file + 5 OO metrics = 55
- Added missing #007 (extract class) to per-file detection table
- Fixed SKILL.md smell-to-file mappings (003, 005, 006, 008, MID pointed to wrong reference files)
- `--min-severity` now validates input and rejects invalid values with clear error message

## [0.1.0] - 2026-02-10

### Added
- AST-based smell detector with 55 automated checks (stdlib-only, zero dependencies)
  - 40 per-file patterns (#001-#070, #CC)
  - 10 cross-file patterns (#013, #CYC, #GOD, #FE, #SHO, #DIT, #WHI, #INT, #SPG, #UDE)
  - 5 OO metrics (#LCOM, #CBO, #FIO, #RFC, #MID)
- 82 refactoring patterns with before/after examples across 8 reference files
- Agent Skills plugin structure for Claude Code, Codex CLI, Cursor, Copilot, Gemini CLI, Roo Code
- JSON output mode for CI/CD integration
- Severity filtering (`--min-severity info|warning|error`)

[0.1.1]: https://github.com/cheickmec/pysmells/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/cheickmec/pysmells/releases/tag/v0.1.0
