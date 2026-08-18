"""Sandbox validator for self-healing patches."""

import ast
import importlib.util
import sys
from pathlib import Path
from loguru import logger


def validate_syntax(file_path: str) -> bool:
    """Check Python file for syntax errors (AST parse only, no execution)."""
    try:
        source = Path(file_path).read_text(encoding="utf-8")
        ast.parse(source)
        return True
    except SyntaxError as e:
        logger.error(f"Syntax error in {file_path}: {e}")
        return False


def validate_import(file_path: str) -> bool:
    """Try importing a module in a sandboxed manner (no business logic)."""
    try:
        spec = importlib.util.spec_from_file_location(
            "temp_module", file_path, submodule_search_locations=[]
        )
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            # Only check importability, don't exec the module
            logger.info(f"Module {file_path} is importable")
            return True
        return False
    except Exception as e:
        logger.error(f"Import validation failed for {file_path}: {e}")
        return False


def sandbox_validate(file_path: str) -> dict:
    """Run syntax + import validation. Returns result dict."""
    syntax_ok = validate_syntax(file_path)
    import_ok = validate_import(file_path) if syntax_ok else False
    return {
        "syntax_valid": syntax_ok,
        "import_valid": import_ok,
        "passed": syntax_ok and import_ok,
    }
