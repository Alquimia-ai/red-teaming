"""Production imports must work at runtime without optional model providers."""

import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def production_files() -> list[Path]:
    return [p for parent in ("packages", "apps") for p in (ROOT / parent).glob("*/src/**/*.py")]


def test_no_type_checking_guards_or_imports_remain() -> None:
    violations = []
    for path in production_files():
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (
                (isinstance(node, ast.Name) and node.id == "TYPE_CHECKING")
                or (isinstance(node, ast.Attribute) and node.attr == "TYPE_CHECKING")
                or (
                    isinstance(node, ast.ImportFrom)
                    and node.module in {"typing", "typing_extensions"}
                    and any(name.name == "TYPE_CHECKING" for name in node.names)
                )
            ):
                violations.append(str(path.relative_to(ROOT)))
    assert not violations, violations


def test_all_modules_import_without_optional_model_providers() -> None:
    modules = []
    for path in production_files():
        relative = path.relative_to(next(p for p in path.parents if p.name == "src"))
        parts = list(relative.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        modules.append(".".join(parts))
    source = """
import importlib
import importlib.abc
import sys

class NoOptionalProviders(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"langchain_openai", "langchain_openrouter"}:
            raise ModuleNotFoundError("optional provider intentionally unavailable: " + fullname)
        return None

sys.meta_path.insert(0, NoOptionalProviders())
for module in sys.argv[1:]:
    importlib.import_module(module)
"""
    result = subprocess.run(
        [sys.executable, "-c", source, *sorted(set(modules))],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
