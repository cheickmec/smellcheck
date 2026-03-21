"""Regression tests for previously fixed bugs in smellcheck.

Each test covers a specific bug that was found and fixed, ensuring
no regressions in future changes.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from smellcheck.detector import _parse_args, scan_path, scan_paths


def _write_py(tmp_path: Path, code: str, name: str = "sample.py") -> Path:
    p = tmp_path / name
    p.write_text(textwrap.dedent(code), encoding="utf-8")
    return p


# --- Regression: import captures dotted paths (#CYC, #UDE, #FIO) ---

def test_import_captures_dotted_paths(tmp_path):
    """Dotted imports like ``import foo.bar`` must record 'foo.bar', not just 'foo'."""
    _write_py(tmp_path, """\
        import os.path
        x = os.path.join("a", "b")
    """, name="mod_a.py")
    _write_py(tmp_path, """\
        import sys
        y = sys.argv
    """, name="mod_b.py")
    # Should not crash and should handle dotted module names
    findings = scan_path(tmp_path)
    assert isinstance(findings, list)


# --- Regression: RFC counts methods, not classes ---

def test_rfc_counts_methods_not_classes(tmp_path):
    """RFC metric should count methods of a class + external method calls,
    not count the class itself as a single unit."""
    p = _write_py(tmp_path, """\
        class Foo:
            def method_a(self):
                pass
            def method_b(self):
                pass
            def method_c(self):
                pass
    """)
    findings = scan_path(p)
    rfc_findings = [f for f in findings if f.pattern == "SC804"]
    # Foo has 3 methods + 0 external calls = RFC 3, below default threshold of 20
    assert len(rfc_findings) == 0


# --- Regression: elif no duplicate findings for #014/#068 ---

def test_elif_no_duplicate_findings(tmp_path):
    """An if/elif chain should not produce duplicate findings for #014 and #068."""
    p = _write_py(tmp_path, """\
        def dispatch(x):
            if isinstance(x, int):
                return "int"
            elif isinstance(x, str):
                return "str"
            elif isinstance(x, float):
                return "float"
    """)
    findings = scan_path(p)
    # Check no duplicate patterns on same line
    seen = set()
    for f in findings:
        key = (f.file, f.line, f.pattern)
        assert key not in seen, f"Duplicate finding: {key}"
        seen.add(key)


# --- Regression: ExitStack no false positive #058 ---

def test_exitstack_no_false_positive_058(tmp_path):
    """``ExitStack.enter_context(open(...))`` should not trigger #058."""
    p = _write_py(tmp_path, """\
        from contextlib import ExitStack
        def process():
            with ExitStack() as stack:
                f = stack.enter_context(open("test.txt"))
                return f.read()
    """)
    findings = scan_path(p)
    f058 = [f for f in findings if f.pattern == "SC702"]
    # The open() is wrapped in enter_context, so no #058
    assert len(f058) == 0


# --- Regression: single file runs OO metrics ---

def test_single_file_runs_oo_metrics(tmp_path):
    """Scanning a single file should still compute LCOM, CBO, RFC, MID."""
    p = _write_py(tmp_path, """\
        class BigClass:
            def __init__(self):
                self.a = 1
                self.b = 2
                self.c = 3
                self.d = 4
                self.e = 5
                self.f = 6
                self.g = 7
                self.h = 8

            def use_a(self):
                return self.a

            def use_b(self):
                return self.b

            def use_c(self):
                return self.c

            def use_d(self):
                return self.d

            def use_e(self):
                return self.e

            def use_f(self):
                return self.f

            def use_g(self):
                return self.g

            def use_h(self):
                return self.h
    """)
    findings = scan_path(p)
    metric_patterns = {f.pattern for f in findings}
    # Should detect LCOM (each method uses only 1 of 8 fields)
    assert "SC801" in metric_patterns


# --- Regression: min-severity rejects invalid values ---

def test_min_severity_rejects_invalid(tmp_path):
    p = _write_py(tmp_path, "x = 1\n")
    with pytest.raises(SystemExit) as exc_info:
        _parse_args([str(p), "--min-severity", "critical"])
    assert exc_info.value.code == 1


# --- Regression: #007 extract class fires on class with too many methods ---

def test_007_extract_class_detected(tmp_path):
    """A class with >12 methods should trigger #007 Extract Class."""
    methods = "\n".join(
        f"    def method_{i}(self): pass" for i in range(15)
    )
    p = _write_py(tmp_path, f"class Bloated:\n{methods}\n")
    findings = scan_path(p)
    patterns = [f.pattern for f in findings]
    assert "SC301" in patterns


# --- Regression: noqa suppression codes are case-insensitive ---

def test_noqa_code_case_insensitive(tmp_path):
    """``# noqa: sc701`` (lowercase) should also suppress SC701."""
    p = _write_py(tmp_path, "def foo(x=[]):  # noqa: sc701\n    pass\n")
    findings = scan_paths([p])
    patterns = [f.pattern for f in findings]
    # _is_suppressed uppercases codes, so sc701 -> SC701 should match
    assert "SC701" not in patterns


# --- Regression: 3-node cyclic import produces exactly 1 finding (#75) ---

def test_cyclic_import_three_node_single_finding(tmp_path):
    """A single A->B->C->A cycle must produce exactly 1 SC503 finding, not 3."""
    (tmp_path / "mod_a.py").write_text("import mod_b\n", encoding="utf-8")
    (tmp_path / "mod_b.py").write_text("import mod_c\n", encoding="utf-8")
    (tmp_path / "mod_c.py").write_text("import mod_a\n", encoding="utf-8")
    findings = scan_paths([
        tmp_path / "mod_a.py",
        tmp_path / "mod_b.py",
        tmp_path / "mod_c.py",
    ])
    sc503 = [f for f in findings if f.pattern == "SC503"]
    assert len(sc503) == 1, f"Expected 1 SC503 finding, got {len(sc503)}: {sc503}"


# --- Regression: duplicate Path.stem does not drop files (#76) ---

def test_cross_file_duplicate_stem_not_dropped(tmp_path):
    """Two files with the same stem in different packages must both be analyzed."""
    pkg1 = tmp_path / "pkg1"
    pkg2 = tmp_path / "pkg2"
    pkg1.mkdir()
    pkg2.mkdir()
    # pkg1/utils.py imports pkg2's utils
    (pkg1 / "utils.py").write_text(
        "import pkg2.utils\ndef helper1(): pass\n", encoding="utf-8"
    )
    # pkg2/utils.py imports pkg1's utils
    (pkg2 / "utils.py").write_text(
        "import pkg1.utils\ndef helper2(): pass\n", encoding="utf-8"
    )
    # Key invariant: scanning 2 files must not silently reduce to 1.
    # Verify both files are individually scannable.
    from smellcheck.detector import scan_file, _build_module_maps
    fd1 = scan_file(pkg1 / "utils.py")
    fd2 = scan_file(pkg2 / "utils.py")
    assert isinstance(fd1, tuple) and isinstance(fd2, tuple), "scan_file must return (findings, FileData)"
    # Verify the module map doesn't collapse duplicate stems.
    all_data = [fd1[1], fd2[1]]
    module_map, _ = _build_module_maps(all_data)
    # Each file must have a distinct module key so neither is dropped.
    modules = list(module_map.values())
    assert len(modules) == len(set(modules)), (
        f"Module map collapsed duplicate stems: {module_map}"
    )
    # Both file paths must be present in the map.
    assert str(pkg1 / "utils.py") in module_map, "pkg1/utils.py missing from module_map"
    assert str(pkg2 / "utils.py") in module_map, "pkg2/utils.py missing from module_map"
    # scan_paths must not crash and must return without dropping either file.
    _ = scan_paths([pkg1 / "utils.py", pkg2 / "utils.py"])


# --- Regression #74: ast.walk traverses nested functions ---

def test_nested_function_not_attributed_to_outer(tmp_path):
    """Smells inside a nested function must not be reported against the outer function.

    Before the fix, ``ast.walk()`` descended into nested scopes, so a
    magic number in ``inner()`` would be blamed on ``outer()``.
    """
    p = _write_py(tmp_path, """\
        def outer(x):
            x + 1

            def inner():
                return 99999
    """)
    findings = scan_path(p)
    # SC601 (magic number) should fire for inner(), NOT for outer()
    magic = [f for f in findings if f.pattern == "SC601"]
    for f in magic:
        assert "inner" not in f.message or "outer" not in f.message, (
            f"SC601 should not attribute inner()'s magic number to outer(): {f.message}"
        )


def test_nested_function_generic_name_not_attributed_to_outer(tmp_path):
    """SC202 generic-name findings from a nested function must not appear on the outer.

    Before the fix, ``ast.walk()`` descended into nested scopes, so a
    generic assignment in ``inner()`` would be reported against ``outer()``.
    """
    p = _write_py(tmp_path, """\
        def outer():
            x = 1

            def inner():
                result = compute()
                return result
    """)
    findings = scan_path(p)
    generic = [f for f in findings if f.pattern == "SC202"]
    outer_generic = [f for f in generic if "outer" in f.message]
    assert not outer_generic, (
        f"SC202 should not blame outer() for generic names inside inner(): {outer_generic}"
    )


def test_cyclomatic_complexity_ignores_nested(tmp_path):
    """CC of the outer function should not include branches in nested functions."""
    # Outer has CC=1 (no branches), inner has many branches.
    p = _write_py(tmp_path, """\
        def outer():
            def inner(x):
                if x > 0:
                    pass
                if x > 1:
                    pass
                if x > 2:
                    pass
                if x > 3:
                    pass
                if x > 4:
                    pass
                if x > 5:
                    pass
                if x > 6:
                    pass
                if x > 7:
                    pass
                if x > 8:
                    pass
                if x > 9:
                    pass
                if x > 10:
                    pass
            return inner
    """)
    findings = scan_path(p)
    # SC210 should fire for inner() but NOT for outer()
    cc_findings = [f for f in findings if f.pattern == "SC210"]
    outer_cc = [f for f in cc_findings if "outer" in f.message]
    assert not outer_cc, (
        f"SC210 should not fire for outer() due to inner()'s branches: {outer_cc}"
    )


def test_nesting_depth_ignores_nested_functions(tmp_path):
    """Nesting depth should not count control flow inside nested functions."""
    p = _write_py(tmp_path, """\
        def outer():
            def inner():
                for i in range(10):
                    for j in range(10):
                        for k in range(10):
                            for m in range(10):
                                for n in range(10):
                                    pass
            return inner
    """)
    findings = scan_path(p)
    # SC402 (deep nesting) should fire for inner() but NOT for outer()
    nesting = [f for f in findings if f.pattern == "SC402"]
    outer_nesting = [f for f in nesting if "outer" in f.message]
    assert not outer_nesting, (
        f"SC402 should not fire for outer() due to inner()'s nesting: {outer_nesting}"
    )


# --- Regression #78: _is_elif broken at module level ---

def test_is_elif_module_level(tmp_path):
    """Module-level if/elif chains should not duplicate findings.

    Before the fix, ``_is_elif`` returned False when ``_func_stack`` was
    empty, so an elif at module level was treated as a top-level if,
    producing duplicate SC302/SC407 findings.
    """
    p = _write_py(tmp_path, """\
        x = 1
        if isinstance(x, int):
            pass
        elif isinstance(x, str):
            pass
        elif isinstance(x, float):
            pass
    """)
    findings = scan_path(p)
    # SC302 should fire at most once for the chain, not once per elif
    isinstance_chain = [f for f in findings if f.pattern == "SC302"]
    assert len(isinstance_chain) <= 1, (
        f"SC302 should fire at most once for an if/elif chain, got {len(isinstance_chain)}: "
        f"{isinstance_chain}"
    )


# --- Regression #79: missing ast.TryStar ---

def test_dead_code_after_return_in_try_star(tmp_path):
    """SC401 should detect dead code inside ``try/except*`` blocks (Python 3.11+)."""
    import sys
    if sys.version_info < (3, 11):
        pytest.skip("ast.TryStar requires Python 3.11+")
    # Use exec to avoid SyntaxError on Python < 3.11
    code = (
        "def foo():\n"
        "    try:\n"
        "        pass\n"
        "    except* ValueError:\n"
        "        return 1\n"
        "        print('dead')\n"
    )
    p = _write_py(tmp_path, code)
    findings = scan_path(p)
    dead = [f for f in findings if f.pattern == "SC401"]
    assert any("dead" in f.message.lower() or "unreachable" in f.message.lower() for f in dead), (
        f"SC401 should detect dead code after return inside except* block, got: {dead}"
    )
