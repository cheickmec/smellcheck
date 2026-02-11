---
name: Feature request
about: Suggest a new smell check, CLI feature, or improvement
title: ''
labels: enhancement
assignees: ''
---

**What kind of feature?**
- [ ] New smell check
- [ ] New CLI option
- [ ] New output format
- [ ] Improvement to existing check
- [ ] Other

**For new smell checks: describe the code pattern**

What code should be detected?

```python
# Before (smelly code)
```

What does the refactored version look like?

```python
# After (clean code)
```

**Why is this a smell?**
Explain why this pattern is problematic. References to Fowler, Contieri, or other
refactoring literature are a plus.

**Suggested severity**
- [ ] error (always wrong, like mutable default args)
- [ ] warning (usually wrong, should be reviewed)
- [ ] info (style suggestion, may be intentional)

**Additional context**
Any other context, related patterns, or edge cases to consider.
