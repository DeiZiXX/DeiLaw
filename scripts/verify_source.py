from __future__ import annotations

import ast
import os
import py_compile
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED = [
    "main.py",
    "app_version.py",
    "ui/main_window.py",
    "database.py",
    "parser.py",
    "article_parser.py",
    "update_worker.py",
    "community_client.py",
    "ai_core/cloud.py",
    "ai_core/engine.py",
    "ai_core/retrieval.py",
    "supabase/functions/deilaw-ai/index.ts",
    "README.md",
]

# Never scan installed dependencies or transient build products as project code.
# They routinely contain SPDX snippets such as "sk-..." and PEM examples.
IGNORED_DIRS = {".git", ".venv", "venv", "build", "dist", "__pycache__", ".pytest_cache", ".mypy_cache"}
SOURCE_EXTENSIONS = {".py", ".ts", ".sql", ".json", ".md", ".txt", ".yml", ".yaml", ".toml", ".ps1", ".bat", ".iss", ".nsi", ".ini", ".env"}

def project_files():
    for folder, dirs, files in os.walk(ROOT):
        dirs[:] = [name for name in dirs if name not in IGNORED_DIRS]
        for name in files:
            file = Path(folder) / name
            if file.suffix.lower() in SOURCE_EXTENSIONS or file.name in (".env", ".gitignore"):
                yield file

SECRET_PATTERNS = {
    "OpenAI API key": re.compile(r"sk-[A-Za-z0-9_-]{20,}"),
    "GitHub token": re.compile(r"gh[pousr]_[A-Za-z0-9_]{20,}"),
    "Private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def check_required(errors: list[str]) -> None:
    for name in REQUIRED:
        if not (ROOT / name).is_file():
            errors.append(f"Missing required file: {name}")


def check_python(errors: list[str]) -> None:
    for path in project_files():
        if path.suffix != ".py":
            continue
        try:
            source = path.read_text(encoding="utf-8")
            ast.parse(source, filename=str(path))
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:
            errors.append(f"Python error in {rel(path)}: {exc}")


def check_secrets(errors: list[str]) -> None:
    for path in project_files():
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                errors.append(f"Possible {label} in {rel(path)}")


def main() -> int:
    errors: list[str] = []
    check_required(errors)
    check_python(errors)
    check_secrets(errors)

    version = "unknown"
    version_file = ROOT / "app_version.py"
    if version_file.exists():
        match = re.search(r"APP_VERSION\s*=\s*[\'\"]([^\'\"]+)", version_file.read_text(encoding="utf-8"))
        if match:
            version = match.group(1)

    if errors:
        print(f"DeiLaw source verification FAILED (version {version})")
        for item in errors:
            print(f"[ERROR] {item}")
        return 1

    py_count = sum(1 for path in project_files() if path.suffix == ".py")
    print(f"DeiLaw source verification OK (version {version})")
    print(f"Python files checked: {py_count}")
    print("Required source tree: OK")
    print("Python syntax/compile: OK")
    print("Common secret patterns: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
