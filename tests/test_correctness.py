"""Regression tests for verified smellcheck correctness bugs."""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from smellcheck.detector import scan_path, scan_paths

REPO_ROOT = Path(__file__).resolve().parent.parent


def _write_py(tmp_path: Path, code: str, name: str = "sample.py") -> Path:
    """Write a Python fixture, dedenting the source.

    Args:
        tmp_path: Directory that will contain the file.
        code: Source, possibly indented for nesting in the test.
        name: File name relative to *tmp_path*.

    Returns:
        Path of the written file.
    """
    path = tmp_path / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(code), encoding="utf-8")
    return path


def _run_cli(
    *args: str, cwd: Path | None = None, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    """Run the smellcheck CLI in a clean environment.

    Args:
        *args: Arguments after the module name.
        cwd: Working directory for the process.
        env: Extra environment variables.

    Returns:
        Completed process with captured text output.
    """
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("SMELLCHECK_")}
    if env:
        clean_env.update(env)
    return subprocess.run(
        [sys.executable, "-m", "smellcheck", *args],
        capture_output=True,
        text=True,
        cwd=cwd,
        env=clean_env,
    )


def _patterns(findings: list, code: str) -> list:
    return [finding for finding in findings if finding.pattern == code]


# ---------------------------------------------------------------------------
# 1. Cache file identity
# ---------------------------------------------------------------------------


def test_cache_does_not_reuse_findings_across_identical_files(tmp_path: Path) -> None:
    """Identical sources must keep the path of the file being scanned."""
    source = "def demo(items=[]):\n    return items\n"
    (tmp_path / "a.py").write_text(source, encoding="utf-8")
    (tmp_path / "b.py").write_text(source, encoding="utf-8")
    cached = _run_cli(".", "--select", "SC701", "--format", "json", cwd=tmp_path)
    fresh = _run_cli(
        ".", "--select", "SC701", "--format", "json", "--no-cache", cwd=tmp_path
    )
    assert cached.returncode == fresh.returncode == 1
    cached_names = sorted(Path(item["file"]).name for item in json.loads(cached.stdout))
    fresh_names = sorted(Path(item["file"]).name for item in json.loads(fresh.stdout))
    assert cached_names == fresh_names == ["a.py", "b.py"]


def test_cache_follows_a_renamed_file(tmp_path: Path) -> None:
    """A warm cache must not report a file that was renamed away."""
    source = "def demo(items=[]):\n    return items\n"
    original = tmp_path / "a.py"
    original.write_text(source, encoding="utf-8")
    (tmp_path / "b.py").write_text(source, encoding="utf-8")
    first = _run_cli(".", "--select", "SC701", "--format", "json", cwd=tmp_path)
    assert first.returncode == 1
    (tmp_path / "b.py").unlink()
    original.rename(tmp_path / "renamed.py")
    second = _run_cli(".", "--select", "SC701", "--format", "json", cwd=tmp_path)
    names = [Path(item["file"]).name for item in json.loads(second.stdout)]
    assert names == ["renamed.py"]
    assert "a.py" not in second.stdout


def test_cache_key_includes_file_identity() -> None:
    """Same source at two paths must not produce the same cache key."""
    from smellcheck.detector import _cache_key

    source = "x = 1\n"
    left = _cache_key(source, "cfg", "0.4.0", "/proj/a.py")
    right = _cache_key(source, "cfg", "0.4.0", "/proj/b.py")
    assert left != right


# ---------------------------------------------------------------------------
# 2. Relative per-file ignores
# ---------------------------------------------------------------------------


def _ignore_project(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        '[tool.smellcheck]\nper-file-ignores = {"tests/*" = ["SC701"]}\n',
        encoding="utf-8",
    )
    _write_py(
        tmp_path,
        "def demo(items=[]):\n    return items\n",
        name="tests/test_sample.py",
    )
    _write_py(
        tmp_path,
        "def demo(items=[]):\n    return items\n",
        name="app.py",
    )
    return tmp_path


def test_relative_per_file_ignore_matches_directory_argument(tmp_path: Path) -> None:
    """``tests/*`` matches files under tests when the CLI is given that directory."""
    root = _ignore_project(tmp_path)
    result = _run_cli(
        "tests", "--no-cache", "--select", "SC701", "--format", "json", cwd=root
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == []


def test_relative_per_file_ignore_matches_absolute_path_from_elsewhere(
    tmp_path: Path,
) -> None:
    """Absolute arguments and a foreign cwd still use the config root."""
    root = _ignore_project(tmp_path)
    result = _run_cli(
        str(root / "tests"),
        "--no-cache",
        "--select",
        "SC701",
        "--format",
        "json",
        cwd=root.parent,
    )
    assert result.returncode == 0
    assert json.loads(result.stdout) == []


def test_per_file_ignore_leaves_unmatched_files(tmp_path: Path) -> None:
    """A file outside the glob is still reported."""
    root = _ignore_project(tmp_path)
    result = _run_cli(
        "app.py", "--no-cache", "--select", "SC701", "--format", "json", cwd=root
    )
    assert result.returncode == 1
    assert json.loads(result.stdout)[0]["pattern"] == "SC701"


# ---------------------------------------------------------------------------
# 3. Single-file indirect blocking
# ---------------------------------------------------------------------------


_BLOCKING = """\
import time

def helper():
    time.sleep(1)

async def run():
    helper()
"""


def test_cli_single_file_detects_indirect_blocking(tmp_path: Path) -> None:
    """The CLI single-file path must trace ``run -> helper -> time.sleep``."""
    _write_py(tmp_path, _BLOCKING, name="sample.py")
    result = _run_cli(
        "sample.py", "--no-cache", "--select", "SC703", "--format", "json", cwd=tmp_path
    )
    findings = json.loads(result.stdout)
    assert findings
    assert "run -> helper -> time.sleep" in findings[0]["message"]
    library = _patterns(scan_path(tmp_path / "sample.py"), "SC703")
    assert library


def test_single_file_indirect_blocking_cache_matches_uncached(tmp_path: Path) -> None:
    """A warm single-file cache still reports the indirect chain."""
    _write_py(tmp_path, _BLOCKING, name="sample.py")
    fresh = _run_cli(
        "sample.py", "--no-cache", "--select", "SC703", "--format", "json", cwd=tmp_path
    )
    _run_cli("sample.py", "--select", "SC703", "--format", "json", cwd=tmp_path)
    cached = _run_cli(
        "sample.py", "--select", "SC703", "--format", "json", cwd=tmp_path
    )
    assert json.loads(cached.stdout) == json.loads(fresh.stdout)


def test_to_thread_offload_is_not_indirect_blocking(tmp_path: Path) -> None:
    """Passing a helper to ``asyncio.to_thread`` is not an indirect SC703."""
    _write_py(
        tmp_path,
        """\
        import asyncio
        import time

        def helper():
            time.sleep(1)

        async def run():
            await asyncio.to_thread(helper)
        """,
        name="sample.py",
    )
    findings = scan_paths([tmp_path / "sample.py"], use_cache=False)
    indirect = [
        finding
        for finding in findings
        if finding.pattern == "SC703" and "Indirect blocking" in finding.message
    ]
    assert indirect == []


# ---------------------------------------------------------------------------
# 4. Async classification is binding-sensitive
# ---------------------------------------------------------------------------


def test_unrelated_async_function_does_not_hide_blocking(tmp_path: Path) -> None:
    """A same-named async function in another file does not bind ``a.fetch``."""
    _write_py(
        tmp_path,
        """\
        import time

        def fetch():
            time.sleep(1)

        async def job():
            fetch()
        """,
        name="a.py",
    )
    _write_py(tmp_path, "async def unrelated():\n    return 1\n", name="b.py")
    before = scan_paths(
        [tmp_path / "a.py", tmp_path / "b.py"], use_cache=False
    )
    (tmp_path / "b.py").write_text("async def fetch():\n    return 1\n", encoding="utf-8")
    after = scan_paths([tmp_path / "a.py", tmp_path / "b.py"], use_cache=False)
    for findings in (before, after):
        indirect = [
            finding
            for finding in findings
            if finding.pattern == "SC703" and "job -> fetch -> time.sleep" in finding.message
        ]
        assert len(indirect) == 1
        assert indirect[0].file.endswith("a.py")


def test_unrelated_sync_function_does_not_create_blocking(tmp_path: Path) -> None:
    """A blocking ``fetch`` that this module does not call is not a finding."""
    _write_py(
        tmp_path,
        """\
        def fetch():
            return 1

        async def job():
            fetch()
        """,
        name="a.py",
    )
    _write_py(
        tmp_path,
        """\
        import time

        def fetch():
            time.sleep(1)
        """,
        name="b.py",
    )
    findings = scan_paths([tmp_path / "a.py", tmp_path / "b.py"], use_cache=False)
    indirect = [
        finding
        for finding in findings
        if finding.pattern == "SC703" and "Indirect blocking" in finding.message
    ]
    assert indirect == []


def test_imported_alias_blocking_chain(tmp_path: Path) -> None:
    """``from b import fetch as get_data`` resolves to ``b.fetch``."""
    _write_py(
        tmp_path,
        """\
        import time

        def fetch():
            time.sleep(1)
        """,
        name="b.py",
    )
    _write_py(
        tmp_path,
        """\
        from b import fetch as get_data

        async def job():
            get_data()
        """,
        name="a.py",
    )
    findings = scan_paths([tmp_path / "a.py", tmp_path / "b.py"], use_cache=False)
    messages = [
        finding.message
        for finding in findings
        if finding.pattern == "SC703" and "Indirect blocking" in finding.message
    ]
    assert any("job -> fetch -> time.sleep" in message for message in messages)


def test_method_blocking_is_not_hidden_by_unrelated_async(tmp_path: Path) -> None:
    """``self.fetch`` binds to the method, not a global async ``fetch``."""
    _write_py(
        tmp_path,
        """\
        import time

        class Box:
            def fetch(self):
                time.sleep(1)

            async def run(self):
                self.fetch()
        """,
        name="a.py",
    )
    _write_py(tmp_path, "async def fetch():\n    return 1\n", name="b.py")
    findings = scan_paths([tmp_path / "a.py", tmp_path / "b.py"], use_cache=False)
    indirect = [
        finding
        for finding in findings
        if finding.pattern == "SC703" and "Indirect blocking" in finding.message
    ]
    assert len(indirect) == 1
    assert "run -> fetch -> time.sleep" in indirect[0].message


def test_async_method_is_not_treated_as_blocking(tmp_path: Path) -> None:
    """An async method is not an indirect blocking callee."""
    _write_py(
        tmp_path,
        """\
        class Box:
            async def fetch(self):
                return 1

            async def run(self):
                self.fetch()
        """,
    )
    findings = scan_path(tmp_path / "sample.py")
    indirect = [
        finding
        for finding in findings
        if finding.pattern == "SC703" and "Indirect blocking" in finding.message
    ]
    assert indirect == []


def test_transitive_imported_helper_chain(tmp_path: Path) -> None:
    """Async -> imported helper -> imported blocker is reported."""
    _write_py(
        tmp_path,
        """\
        import time

        def deep():
            time.sleep(1)
        """,
        name="c.py",
    )
    _write_py(
        tmp_path,
        """\
        from c import deep

        def middle():
            deep()
        """,
        name="b.py",
    )
    _write_py(
        tmp_path,
        """\
        from b import middle

        async def job():
            middle()
        """,
        name="a.py",
    )
    findings = scan_paths(
        [tmp_path / "a.py", tmp_path / "b.py", tmp_path / "c.py"], use_cache=False
    )
    messages = [finding.message for finding in findings if finding.pattern == "SC703"]
    assert any("job -> middle -> deep -> time.sleep" in message for message in messages)


# ---------------------------------------------------------------------------
# 5. Package import cycles
# ---------------------------------------------------------------------------


def _sc503(paths: list[Path]) -> list:
    findings = scan_paths(paths, use_cache=False)
    return [finding for finding in findings if finding.pattern == "SC503"]


def test_relative_package_cycle(tmp_path: Path) -> None:
    """``from . import`` inside a package is a real cycle."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "a.py").write_text("from . import b\n", encoding="utf-8")
    (pkg / "b.py").write_text("from . import a\n", encoding="utf-8")
    findings = _sc503([pkg])
    assert len(findings) == 1
    assert "pkg.a" in findings[0].message
    assert "pkg.b" in findings[0].message


def test_qualified_import_ignores_unrelated_basename(tmp_path: Path) -> None:
    """``import pkg_b.utils`` must not resolve to ``pkg_a.utils``."""
    (tmp_path / "pkg_a").mkdir()
    (tmp_path / "pkg_b").mkdir()
    (tmp_path / "pkg_a" / "mod.py").write_text("import pkg_b.utils\n", encoding="utf-8")
    (tmp_path / "pkg_b" / "utils.py").write_text("import pkg_a.mod\n", encoding="utf-8")
    (tmp_path / "pkg_a" / "utils.py").write_text(
        "def unrelated():\n    return 1\n", encoding="utf-8"
    )
    findings = _sc503([tmp_path])
    assert len(findings) == 1
    assert "pkg_a.mod" in findings[0].message
    assert "pkg_b.utils" in findings[0].message
    assert "pkg_a.utils" not in findings[0].message


def test_nested_relative_cycle(tmp_path: Path) -> None:
    """A parent import and a child import form one cycle."""
    pkg = tmp_path / "pkg"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "sub" / "a.py").write_text("from .. import b\n", encoding="utf-8")
    (pkg / "b.py").write_text("from .sub import a\n", encoding="utf-8")
    findings = _sc503([pkg])
    assert len(findings) == 1
    assert "pkg.b" in findings[0].message
    assert "pkg.sub.a" in findings[0].message


def test_legitimate_package_import_is_not_a_cycle(tmp_path: Path) -> None:
    """Importing a sibling once, with no edge back, is not SC503."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "a.py").write_text("import pkg.b\n", encoding="utf-8")
    (pkg / "b.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
    assert _sc503([pkg]) == []


def test_repeated_basenames_without_a_cycle(tmp_path: Path) -> None:
    """A one-way qualified import does not attach to the other basename."""
    (tmp_path / "pkg_a").mkdir()
    (tmp_path / "pkg_b").mkdir()
    (tmp_path / "pkg_a" / "utils.py").write_text(
        "import pkg_b.helpers\n", encoding="utf-8"
    )
    (tmp_path / "pkg_b" / "helpers.py").write_text(
        "def f():\n    return 1\n", encoding="utf-8"
    )
    (tmp_path / "pkg_b" / "utils.py").write_text(
        "def g():\n    return 2\n", encoding="utf-8"
    )
    assert _sc503([tmp_path]) == []


# ---------------------------------------------------------------------------
# 6. Closure-captured parameters
# ---------------------------------------------------------------------------


def test_closure_captured_parameter_is_used(tmp_path: Path) -> None:
    """A parameter read by a returned nested function is not unused."""
    path = _write_py(
        tmp_path,
        """\
        def make_adder(offset):
            def add(value):
                return value + offset
            return add
        """,
    )
    assert _patterns(scan_path(path), "SC208") == []


def test_genuinely_unused_parameter_is_reported(tmp_path: Path) -> None:
    """A parameter that nobody reads is still SC208."""
    path = _write_py(
        tmp_path,
        """\
        def process(a, b, c):
            return a + b
        """,
    )
    findings = _patterns(scan_path(path), "SC208")
    assert findings
    assert "c" in findings[0].message


def test_nested_parameter_shadows_outer_parameter(tmp_path: Path) -> None:
    """A nested parameter of the same name does not count as a use."""
    path = _write_py(
        tmp_path,
        """\
        def make(offset):
            def add(offset):
                return offset
            return add
        """,
    )
    findings = _patterns(scan_path(path), "SC208")
    assert any("make" in finding.message and "offset" in finding.message for finding in findings)


def test_lambda_capture_and_shadow(tmp_path: Path) -> None:
    """Lambdas capture free names and shadow their own parameters."""
    captured = _write_py(
        tmp_path,
        """\
        def make(offset):
            return lambda value: value + offset
        """,
        name="captured.py",
    )
    shadowed = _write_py(
        tmp_path,
        """\
        def make(offset):
            return lambda offset: offset
        """,
        name="shadowed.py",
    )
    assert _patterns(scan_path(captured), "SC208") == []
    findings = _patterns(scan_path(shadowed), "SC208")
    assert findings
    assert "offset" in findings[0].message


def test_deep_closure_capture(tmp_path: Path) -> None:
    """A name captured two function levels down is used."""
    path = _write_py(
        tmp_path,
        """\
        def make(offset):
            def mid(value):
                def inner():
                    return offset + value
                return inner
            return mid
        """,
    )
    assert _patterns(scan_path(path), "SC208") == []


# ---------------------------------------------------------------------------
# 7. Suppression tokens, not raw text
# ---------------------------------------------------------------------------


def test_noqa_inside_string_does_not_suppress(tmp_path: Path) -> None:
    """A mutable default is still reported when ``# noqa`` is string data."""
    path = _write_py(
        tmp_path,
        """\
        def remember(items=[], label="# noqa"):
            return items, label
        """,
    )
    result = _run_cli(str(path), "--no-cache", "--select", "SC701", "--format", "json")
    assert result.returncode == 1
    assert json.loads(result.stdout)[0]["pattern"] == "SC701"


def test_disable_file_inside_docstring_does_not_suppress(tmp_path: Path) -> None:
    """A docstring that mentions a directive is not a directive."""
    path = _write_py(
        tmp_path,
        '''\
        """Example: # smellcheck: disable-file"""

        def remember(items=[]):
            return items
        ''',
    )
    result = _run_cli(str(path), "--no-cache", "--select", "SC701", "--format", "json")
    assert result.returncode == 1
    assert json.loads(result.stdout)


def test_escaped_quote_does_not_end_string_before_noqa(tmp_path: Path) -> None:
    """``# noqa`` after an escaped quote stays inside the string."""
    path = _write_py(
        tmp_path,
        """\
        def remember(items=[], label="foo \\" # noqa"):
            return items
        """,
    )
    findings = _patterns(scan_paths([path], use_cache=False), "SC701")
    assert findings


def test_trailing_comment_after_string_still_suppresses(tmp_path: Path) -> None:
    """A real comment after a string literal still suppresses that line."""
    path = _write_py(
        tmp_path,
        """\
        def remember(items=[], label="ok"):  # noqa: SC701
            return items, label
        """,
    )
    assert _patterns(scan_paths([path], use_cache=False), "SC701") == []


def test_real_block_directive_still_suppresses(tmp_path: Path) -> None:
    """Comment directives continue to suppress the enclosed range."""
    path = _write_py(
        tmp_path,
        """\
        # smellcheck: disable SC701
        def remember(items=[]):
            return items
        # smellcheck: enable SC701
        def other(items=[]):
            return items
        """,
    )
    findings = _patterns(scan_paths([path], use_cache=False), "SC701")
    assert len(findings) == 1
    assert findings[0].line == 5


# ---------------------------------------------------------------------------
# 8. Analysis failures
# ---------------------------------------------------------------------------


def test_syntax_error_is_not_a_clean_scan(tmp_path: Path) -> None:
    """A syntax error exits 2, keeps JSON as a list, and names the file."""
    path = tmp_path / "syntax.py"
    path.write_text("def broken(:\n    pass\n", encoding="utf-8")
    for extra in ([], ["--no-cache"]):
        result = _run_cli(str(path), "--format", "json", *extra)
        assert result.returncode == 2
        assert json.loads(result.stdout) == []
        assert "syntax.py" in result.stderr
        assert "syntax error" in result.stderr


def test_undecodable_file_is_an_analysis_error(tmp_path: Path) -> None:
    """Bytes that are not UTF-8 are reported instead of ignored."""
    path = tmp_path / "bad.py"
    path.write_bytes(b"\xff\xfe not utf-8")
    result = _run_cli(str(path), "--format", "json", "--no-cache")
    assert result.returncode == 2
    assert json.loads(result.stdout) == []
    assert "bad.py" in result.stderr
    assert "decode" in result.stderr


def test_permission_error_is_an_analysis_error(tmp_path: Path) -> None:
    """An unreadable file is reported when the OS enforces the mode."""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root can read mode 0 files")
    path = tmp_path / "secret.py"
    path.write_text("x = 1\n", encoding="utf-8")
    path.chmod(0)
    try:
        result = _run_cli(str(path), "--format", "json", "--no-cache")
    finally:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    if result.returncode == 0:
        pytest.skip("platform allowed the owner to read a mode 0 file")
    assert result.returncode == 2
    assert "secret.py" in result.stderr
    assert "permission denied" in result.stderr


def test_mixed_valid_and_invalid_files(tmp_path: Path) -> None:
    """Good files still report smells, and the bad file forces exit 2."""
    good = _write_py(tmp_path, "def demo(items=[]):\n    return items\n", name="ok.py")
    bad = tmp_path / "syntax.py"
    bad.write_text("def broken(:\n    pass\n", encoding="utf-8")
    result = _run_cli(
        str(good), str(bad), "--format", "json", "--select", "SC701", "--no-cache"
    )
    assert result.returncode == 2
    findings = json.loads(result.stdout)
    assert len(findings) == 1
    assert findings[0]["pattern"] == "SC701"
    assert "syntax.py" in result.stderr


def test_findings_alone_still_exit_1(tmp_path: Path) -> None:
    """Exit 1 remains the status for findings at the fail-on severity."""
    path = _write_py(tmp_path, "def demo(items=[]):\n    return items\n")
    result = _run_cli(str(path), "--format", "json", "--select", "SC701", "--no-cache")
    assert result.returncode == 1
    assert result.stderr == ""
    assert json.loads(result.stdout)[0]["pattern"] == "SC701"


def test_failed_parse_is_not_cached_as_success(tmp_path: Path) -> None:
    """A second cached scan still reports the syntax error."""
    path = tmp_path / "syntax.py"
    path.write_text("def broken(:\n    pass\n", encoding="utf-8")
    cache = tmp_path / "cache"
    first = _run_cli(str(path), "--format", "json", "--cache-dir", str(cache))
    second = _run_cli(str(path), "--format", "json", "--cache-dir", str(cache))
    assert first.returncode == second.returncode == 2
    assert "syntax.py" in second.stderr
    assert list(cache.glob("*.json")) == []


# ---------------------------------------------------------------------------
# 9. Serial pre-commit hook
# ---------------------------------------------------------------------------


def test_precommit_hook_requires_serial() -> None:
    """The published hook must not batch files before cross-file analysis."""
    text = (REPO_ROOT / ".pre-commit-hooks.yaml").read_text(encoding="utf-8")
    assert "id: smellcheck" in text
    assert "require_serial: true" in text
    assert "require_serial: false" not in text


def _precommit_python() -> Path | None:
    binary = shutil.which("pre-commit")
    if binary is None:
        return None
    first = Path(binary).read_text(encoding="utf-8").splitlines()[0]
    if not first.startswith("#!"):
        return None
    python = Path(first[2:].strip())
    return python if python.is_file() else None


def test_precommit_serial_batch_sees_cycle_across_old_boundary(tmp_path: Path) -> None:
    """pre-commit's batcher, run serially, sees a cycle that splits at 4 files."""
    python = _precommit_python()
    if python is None:
        pytest.skip("pre-commit is not installed")
    files: list[Path] = []
    for index in range(8):
        path = tmp_path / f"f{index}.py"
        if index == 0:
            path.write_text("import f4\n", encoding="utf-8")
        elif index == 4:
            path.write_text("import f0\n", encoding="utf-8")
        else:
            path.write_text(f"x = {index}\n", encoding="utf-8")
        files.append(path)
    direct = _run_cli(
        *(str(path) for path in files),
        "--select",
        "SC503",
        "--fail-on",
        "warning",
        "--format",
        "json",
        "--no-cache",
    )
    assert direct.returncode == 1
    script = tmp_path / "batch.py"
    script.write_text(
        textwrap.dedent(
            """\
            import sys
            from pre_commit.clientlib import load_manifest
            from pre_commit.lang_base import run_xargs
            from pre_commit.xargs import xargs

            manifest, project_python, *files = sys.argv[1:]
            hooks = load_manifest(manifest)
            hook = next(item for item in hooks if item["id"] == "smellcheck")
            if hook["require_serial"] is not True:
                raise SystemExit("manifest is not serial")
            cmd = (
                project_python, "-m", "smellcheck",
                "--select", "SC503", "--fail-on", "warning",
                "--format", "json", "--no-cache",
            )
            serial_rc, _serial_out = run_xargs(
                cmd, files, require_serial=True, color=False,
            )
            # The unshuffled partition size is max(4, ceil(n / workers)).
            # f0 and f4 sit on opposite sides of that boundary.
            parallel_rc, _parallel_out = xargs(
                cmd, files, target_concurrency=2, color=False,
            )
            print(f"{serial_rc} {parallel_rc}")
            """
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src")
    completed = subprocess.run(
        [
            str(python),
            str(script),
            str(REPO_ROOT / ".pre-commit-hooks.yaml"),
            sys.executable,
            *(str(path) for path in files),
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=tmp_path,
    )
    assert completed.returncode == 0, completed.stderr
    serial_rc, parallel_rc = completed.stdout.strip().split()
    assert serial_rc == "1"
    assert parallel_rc == "0"


# ---------------------------------------------------------------------------
# 11. Parent-package edges are not cycles
# ---------------------------------------------------------------------------


def test_package_reexport_is_not_a_cycle(tmp_path: Path) -> None:
    """Re-exporting a submodule must not fake a ``pkg -> pkg.a -> pkg`` cycle."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("from .a import X\n", encoding="utf-8")
    (pkg / "a.py").write_text("from .b import Y\nX = 1\n", encoding="utf-8")
    (pkg / "b.py").write_text("Y = 2\n", encoding="utf-8")
    assert _sc503([pkg]) == []


def test_module_identity_ignores_unrelated_files(tmp_path: Path) -> None:
    """An unrelated file must not rename modules or hide a real cycle."""
    pkg = tmp_path / "src" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "a.py").write_text("from pkg.b import Y\nX = 1\n", encoding="utf-8")
    (pkg / "b.py").write_text("from pkg.a import X\nY = 2\n", encoding="utf-8")
    before = _sc503([pkg])
    assert len(before) == 1
    assert "pkg.a" in before[0].message

    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_other.py").write_text("def t():\n    return 1\n", encoding="utf-8")
    after = _sc503([pkg, tests])
    assert len(after) == 1
    assert after[0].message == before[0].message


# ---------------------------------------------------------------------------
# 12. Submodule receivers resolve for SC703
# ---------------------------------------------------------------------------


def test_from_import_submodule_is_indirect_blocking(tmp_path: Path) -> None:
    """``from pkg import b`` then ``b.fetch()`` traces into ``pkg.b``."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "b.py").write_text(
        "import time\n\ndef fetch():\n    time.sleep(1)\n", encoding="utf-8"
    )
    (tmp_path / "app.py").write_text(
        "import asyncio\nfrom pkg import b\n\nasync def run():\n    b.fetch()\n",
        encoding="utf-8",
    )
    findings = scan_paths([pkg, tmp_path / "app.py"], use_cache=False)
    messages = [f.message for f in findings if f.pattern == "SC703"]
    assert any("run -> fetch -> time.sleep" in message for message in messages)


def test_dotted_receiver_is_indirect_blocking(tmp_path: Path) -> None:
    """``import pkg.helpers`` then ``pkg.helpers.fetch()`` traces the helper."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "helpers.py").write_text(
        "import time\n\ndef fetch():\n    time.sleep(1)\n", encoding="utf-8"
    )
    (tmp_path / "app.py").write_text(
        "import asyncio\nimport pkg.helpers\n\nasync def run():\n    pkg.helpers.fetch()\n",
        encoding="utf-8",
    )
    findings = scan_paths([pkg, tmp_path / "app.py"], use_cache=False)
    messages = [f.message for f in findings if f.pattern == "SC703"]
    assert any("run -> fetch -> time.sleep" in message for message in messages)



# ---------------------------------------------------------------------------
# 13. Function-local imports win over module-level bindings
# ---------------------------------------------------------------------------


def test_function_local_import_is_not_shadowed_by_module_definition(
    tmp_path: Path,
) -> None:
    """A local ``from b import fetch`` wins over a global blocking ``def fetch``."""
    (tmp_path / "b.py").write_text("async def fetch():\n    return 1\n", encoding="utf-8")
    (tmp_path / "a.py").write_text(
        "import time\n\n"
        "def fetch():\n    time.sleep(1)\n\n"
        "async def run():\n"
        "    from b import fetch\n"
        "    await fetch()\n",
        encoding="utf-8",
    )
    findings = scan_paths([tmp_path / "a.py", tmp_path / "b.py"], use_cache=False)
    indirect = [
        f for f in findings if f.pattern == "SC703" and "Indirect blocking" in f.message
    ]
    assert indirect == []


def test_function_local_import_overrides_module_import(tmp_path: Path) -> None:
    """A local ``from blocking import fetch`` wins over ``from safe import fetch``."""
    (tmp_path / "safe.py").write_text("async def fetch():\n    return 1\n", encoding="utf-8")
    (tmp_path / "blocking.py").write_text(
        "import time\n\ndef fetch():\n    time.sleep(1)\n", encoding="utf-8"
    )
    (tmp_path / "a.py").write_text(
        "from safe import fetch\n\n"
        "async def run():\n"
        "    from blocking import fetch\n"
        "    fetch()\n",
        encoding="utf-8",
    )
    findings = scan_paths(
        [tmp_path / "a.py", tmp_path / "safe.py", tmp_path / "blocking.py"],
        use_cache=False,
    )
    messages = [
        f.message
        for f in findings
        if f.pattern == "SC703" and "Indirect blocking" in f.message
    ]
    assert any("run -> fetch -> time.sleep" in message for message in messages)


# ---------------------------------------------------------------------------
# 14. Closure captures ignore nested definitions and globals
# ---------------------------------------------------------------------------


def test_nested_definition_shadows_outer_parameter(tmp_path: Path) -> None:
    """A nested ``def`` of the same name is not a capture of the parameter."""
    path = _write_py(
        tmp_path,
        """\
        def make(offset):
            def middle():
                def offset():
                    return 1
                return offset
            return middle
        """,
    )
    findings = _patterns(scan_path(path), "SC208")
    assert any("make" in f.message and "offset" in f.message for f in findings)


def test_global_read_is_not_a_parameter_capture(tmp_path: Path) -> None:
    """A ``global`` read resolves to the module namespace, not the parameter."""
    path = _write_py(
        tmp_path,
        """\
        offset = 0

        def make(offset):
            def middle():
                global offset
                return offset
            return middle
        """,
    )
    findings = _patterns(scan_path(path), "SC208")
    assert any("make" in f.message and "offset" in f.message for f in findings)


# ---------------------------------------------------------------------------
# 15. Suppression reuses one comment map per file
# ---------------------------------------------------------------------------


def test_comment_map_is_built_once_per_file(tmp_path: Path, monkeypatch) -> None:
    """Suppression filtering must not re-tokenize a file once per finding."""
    from smellcheck import detector

    source = "".join(f"def f{index}(a=[]):\n    return a\n\n" for index in range(50))
    path = tmp_path / "many.py"
    path.write_text(source, encoding="utf-8")

    calls = {"count": 0}
    real_comment_map = detector._comment_map

    def counting_comment_map(source_lines):
        calls["count"] += 1
        return real_comment_map(source_lines)

    monkeypatch.setattr(detector, "_comment_map", counting_comment_map)
    findings = scan_paths([path], use_cache=False)
    assert _patterns(findings, "SC701")
    assert calls["count"] <= 2


def test_scoped_import_bindings_survive_the_cache(tmp_path: Path) -> None:
    """A warm cache keeps the function-local import binding used by SC703."""
    (tmp_path / "b.py").write_text("async def fetch():\n    return 1\n", encoding="utf-8")
    (tmp_path / "a.py").write_text(
        "import time\n\n"
        "def fetch():\n    time.sleep(1)\n\n"
        "async def run():\n"
        "    from b import fetch\n"
        "    await fetch()\n",
        encoding="utf-8",
    )
    targets = [tmp_path / "a.py", tmp_path / "b.py"]
    cache_dir = tmp_path / "cache"
    fresh = [(f.pattern, f.message) for f in scan_paths(targets, use_cache=False)]
    scan_paths(targets, cache_dir=cache_dir)  # populate the cache
    cached = [(f.pattern, f.message) for f in scan_paths(targets, cache_dir=cache_dir)]
    assert cached == fresh

# ---------------------------------------------------------------------------
# 16. Module identity and eager class-body imports
# ---------------------------------------------------------------------------


def test_package_identity_is_independent_of_other_packages(tmp_path: Path) -> None:
    """A second package in the scan must not rename ``pkg`` or hide a cycle."""
    pkg = tmp_path / "src" / "pkg"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "a.py").write_text("from pkg.b import Y\nX = 1\n", encoding="utf-8")
    (pkg / "b.py").write_text("from pkg.a import X\nY = 2\n", encoding="utf-8")
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("", encoding="utf-8")
    (tests / "test_x.py").write_text("def t():\n    return 1\n", encoding="utf-8")
    findings = _sc503([pkg, tests])
    assert len(findings) == 1
    assert "pkg.a" in findings[0].message
    assert "pkg.b" in findings[0].message


def test_relative_from_import_submodule_is_indirect_blocking(tmp_path: Path) -> None:
    """``from . import b`` then ``b.fetch()`` traces into the sibling module."""
    sub = tmp_path / "pkg" / "sub"
    sub.mkdir(parents=True)
    (tmp_path / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (sub / "__init__.py").write_text("", encoding="utf-8")
    (sub / "b.py").write_text(
        "import time\n\ndef fetch():\n    time.sleep(1)\n", encoding="utf-8"
    )
    (sub / "a.py").write_text(
        "import asyncio\nfrom . import b\n\nasync def run():\n    b.fetch()\n",
        encoding="utf-8",
    )
    findings = scan_paths([tmp_path / "pkg"], use_cache=False)
    messages = [f.message for f in findings if f.pattern == "SC703"]
    assert any("run -> fetch -> time.sleep" in message for message in messages)


def test_class_body_import_is_a_dependency(tmp_path: Path) -> None:
    """An import in a class body runs at import time, so it counts for SC503."""
    (tmp_path / "a.py").write_text("class A:\n    import b\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("import a\n", encoding="utf-8")
    findings = _sc503([tmp_path / "a.py", tmp_path / "b.py"])
    assert len(findings) == 1
    assert "a" in findings[0].message
    assert "b" in findings[0].message


def test_function_body_import_is_not_a_module_dependency(tmp_path: Path) -> None:
    """An import inside a function body is deferred, so it is not a cycle edge."""
    (tmp_path / "a.py").write_text("def f():\n    import b\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("import a\n", encoding="utf-8")
    assert _sc503([tmp_path / "a.py", tmp_path / "b.py"]) == []

# ---------------------------------------------------------------------------
# 17. Import bindings do not leak across scopes
# ---------------------------------------------------------------------------


def test_function_local_import_does_not_leak_to_other_functions(tmp_path: Path) -> None:
    """An import inside one function must not rebind a name in another."""
    (tmp_path / "b.py").write_text(
        "import time\n\ndef fetch():\n    time.sleep(1)\n", encoding="utf-8"
    )
    (tmp_path / "a.py").write_text(
        "async def fetch():\n    return 1\n\n"
        "def other():\n    from b import fetch\n    return fetch\n\n"
        "async def run():\n    await fetch()\n",
        encoding="utf-8",
    )
    findings = scan_paths([tmp_path / "a.py", tmp_path / "b.py"], use_cache=False)
    indirect = [
        f for f in findings if f.pattern == "SC703" and "Indirect blocking" in f.message
    ]
    assert indirect == []


def test_relative_submodule_resolves_without_scanned_initializer(
    tmp_path: Path,
) -> None:
    """``from . import b`` resolves even when ``pkg/__init__.py`` is not scanned."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "b.py").write_text(
        "import time\n\ndef fetch():\n    time.sleep(1)\n", encoding="utf-8"
    )
    (pkg / "a.py").write_text(
        "import asyncio\nfrom . import b\n\nasync def run():\n    b.fetch()\n",
        encoding="utf-8",
    )
    # An explicit file list omits the package initializer.
    findings = scan_paths([pkg / "a.py", pkg / "b.py"], use_cache=False)
    messages = [f.message for f in findings if f.pattern == "SC703"]
    assert any("run -> fetch -> time.sleep" in message for message in messages)

# ---------------------------------------------------------------------------
# 18. Method-local bindings and absolute submodule resolution
# ---------------------------------------------------------------------------


def test_method_local_import_is_scoped(tmp_path: Path) -> None:
    """An import inside an async method must not fall back to a module def."""
    (tmp_path / "b.py").write_text("async def fetch():\n    return 1\n", encoding="utf-8")
    (tmp_path / "a.py").write_text(
        "import time\n\n"
        "def fetch():\n    time.sleep(1)\n\n"
        "class A:\n"
        "    async def run(self):\n"
        "        from b import fetch\n"
        "        await fetch()\n",
        encoding="utf-8",
    )
    findings = scan_paths([tmp_path / "a.py", tmp_path / "b.py"], use_cache=False)
    indirect = [
        f for f in findings if f.pattern == "SC703" and "Indirect blocking" in f.message
    ]
    assert indirect == []


def test_absolute_submodule_resolves_without_scanned_initializer(
    tmp_path: Path,
) -> None:
    """``from pkg import b`` resolves even when ``pkg/__init__.py`` is not scanned."""
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "b.py").write_text(
        "import time\n\ndef fetch():\n    time.sleep(1)\n", encoding="utf-8"
    )
    (pkg / "a.py").write_text(
        "import asyncio\nfrom pkg import b\n\nasync def run():\n    b.fetch()\n",
        encoding="utf-8",
    )
    # An explicit file list omits the package initializer.
    findings = scan_paths([pkg / "a.py", pkg / "b.py"], use_cache=False)
    messages = [f.message for f in findings if f.pattern == "SC703"]
    assert any("run -> fetch -> time.sleep" in message for message in messages)

# ---------------------------------------------------------------------------
# 19. Module-scope precedence and exact binding modules
# ---------------------------------------------------------------------------


def test_module_definition_replaces_import(tmp_path: Path) -> None:
    """A module-level def after an import wins at runtime, so no false SC703."""
    (tmp_path / "b.py").write_text(
        "import time\n\ndef fetch():\n    time.sleep(1)\n", encoding="utf-8"
    )
    (tmp_path / "a.py").write_text(
        "from b import fetch\n\n"
        "async def fetch():\n    return 1\n\n"
        "async def run():\n    await fetch()\n",
        encoding="utf-8",
    )
    findings = scan_paths([tmp_path / "a.py", tmp_path / "b.py"], use_cache=False)
    indirect = [
        f for f in findings if f.pattern == "SC703" and "Indirect blocking" in f.message
    ]
    assert indirect == []


def test_relative_submodule_uses_exact_module_not_ancestor(tmp_path: Path) -> None:
    """``from .sub import b`` resolves ``pkg.sub.b``, not the scanned ancestor."""
    pkg = tmp_path / "pkg"
    (pkg / "sub").mkdir(parents=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "sub" / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "sub" / "b.py").write_text(
        "import time\n\ndef fetch():\n    time.sleep(1)\n", encoding="utf-8"
    )
    (pkg / "a.py").write_text(
        "import asyncio\nfrom .sub import b\n\nasync def run():\n    b.fetch()\n",
        encoding="utf-8",
    )
    # Explicit file list omits pkg/sub/__init__.py.
    findings = scan_paths(
        [pkg / "__init__.py", pkg / "a.py", pkg / "sub" / "b.py"], use_cache=False
    )
    messages = [f.message for f in findings if f.pattern == "SC703"]
    assert any("run -> fetch -> time.sleep" in message for message in messages)

