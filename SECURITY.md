# Security Policy

## Scope

smellcheck is a static analysis tool that **reads** Python source files and produces
text output. It does not execute, import, or evaluate the code it analyzes. It has
zero dependencies beyond Python stdlib.

The attack surface is limited to:

- Maliciously crafted Python files that could cause excessive memory or CPU usage
  during AST parsing (handled by Python's `ast.parse` with stdlib defaults)
- Path traversal in CLI arguments (mitigated by `Path.resolve()`)

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest release | Yes |
| older releases | No -- please upgrade |

## Reporting a Vulnerability

If you discover a security issue, please **do not** open a public GitHub issue.

Instead, email **cheick@example.com** with:

1. A description of the vulnerability
2. Steps to reproduce
3. Impact assessment

You should receive an acknowledgment within 48 hours. We will work with you to
understand the issue and coordinate a fix before any public disclosure.

## Security Design Decisions

- **Zero dependencies**: No supply chain risk from third-party packages.
- **No code execution**: smellcheck uses `ast.parse()` only -- it never calls
  `exec`, `compile`, or `importlib` on analyzed code.
- **No network access**: The tool is entirely offline.
- **No file writes**: smellcheck only reads source files and writes to stdout/stderr.
