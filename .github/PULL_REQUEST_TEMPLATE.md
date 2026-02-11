## What does this PR do?

Brief description of the change.

## Type of change

- [ ] New smell check (add pattern number, e.g. `#071`)
- [ ] Bug fix (false positive, false negative, crash)
- [ ] CLI / output improvement
- [ ] Documentation
- [ ] CI / tooling
- [ ] Other

## Checklist

- [ ] `pytest tests/ -v` passes (all tests, including version parity)
- [ ] New check has a test in `tests/test_detector.py`
- [ ] `smellcheck src/smellcheck/` self-check runs clean (or new findings are intentional)
- [ ] No dependencies added (stdlib only)
- [ ] Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/)

## For new smell checks

- **Pattern number**: `#___`
- **Severity**: error / warning / info
- **Category**: functions / classes / complexity / imports / ...
- **Before** (smelly code):

```python
# paste example
```

- **After** (clean code):

```python
# paste example
```

## Additional context

Any other context, edge cases, or related issues.
