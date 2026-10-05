"""Explicit roots; resolved symlink boundaries; no credentials or binary data."""

import hashlib
import os
from pathlib import Path

EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".css",
    ".html",
    ".rs",
    ".go",
    ".java",
    ".c",
    ".cpp",
    ".h",
    ".sql",
    ".sh",
    ".yaml",
    ".yml",
    ".toml",
}
BLOCKED_DIRS = {
    ".git",
    ".venv",
    "node_modules",
    "__pycache__",
    ".ssh",
    ".aws",
    ".gnupg",
    "data",
    "models",
    ".secrets",
    ".config",
}
BLOCKED_NAMES = {
    "credentials",
    "secrets",
    "password",
    "token",
    "private",
    "keychain",
    "id_rsa",
    "id_ed25519",
    ".env",
}
MAX_BYTES = 512_000
MAX_FILES = 10_000


def permitted(path, root):
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()):
        return False
    if any(part in BLOCKED_DIRS for part in path.relative_to(root).parts):
        return False
    name = path.name.lower()
    if (
        any(word in name for word in BLOCKED_NAMES)
        or resolved.suffix.lower() not in EXTENSIONS
    ):
        return False
    return resolved.is_file() and resolved.stat().st_size <= MAX_BYTES


def index(store, root, cancelled=lambda: False):
    root = Path(root).resolve(strict=True)
    allowed = {
        Path(row["path"]).resolve() for row in store.all("SELECT path FROM directories")
    }
    if root not in allowed or not root.is_dir():
        raise ValueError("Directory was not explicitly selected")
    seen, changed = set(), 0
    for parent, dirs, files in os.walk(root, followlinks=False):
        dirs[:] = [
            d
            for d in dirs
            if d not in BLOCKED_DIRS and not (Path(parent) / d).is_symlink()
        ]
        for name in files:
            if cancelled():
                raise InterruptedError("Index cancelled")
            path = Path(parent) / name
            if not permitted(path, root):
                continue
            resolved = str(path.resolve())
            if len(seen) > MAX_FILES:
                raise ValueError(
                    "Directory exceeds 10000 supported files; select a smaller directory"
                )
            content = path.read_bytes()
            if b"\0" in content:
                continue
            try:
                text = content.decode("utf-8")
            except UnicodeDecodeError:
                continue
            # Exclude likely embedded credentials as well as sensitive filenames.
            import re

            if re.search(
                r'-----BEGIN .*PRIVATE KEY|(?:api[_-]?key|password|secret|access[_-]?token)\s*[:=]\s*["\x27]?[A-Za-z0-9_/-]{16,}',
                text,
                re.I,
            ):
                continue
            seen.add(resolved)
            fingerprint = hashlib.sha256(content).hexdigest()
            rows = store.all(
                "SELECT fingerprint FROM documents WHERE path=?", (resolved,)
            )
            if rows and rows[0]["fingerprint"] == fingerprint:
                continue
            with store.lock:
                store.db.execute(
                    "INSERT OR REPLACE INTO documents VALUES(?,?,?,?)",
                    (resolved, str(root), fingerprint, text),
                )
                store.db.execute("DELETE FROM document_fts WHERE path=?", (resolved,))
                store.db.execute(
                    "INSERT INTO document_fts VALUES(?,?)", (resolved, text)
                )
                store.db.commit()
            changed += 1
    for row in store.all("SELECT path FROM documents WHERE root=?", (str(root),)):
        if row["path"] not in seen:
            store.run("DELETE FROM documents WHERE path=?", (row["path"],))
            store.run("DELETE FROM document_fts WHERE path=?", (row["path"],))
    return {"changed": changed, "files": len(seen), "root": str(root)}
