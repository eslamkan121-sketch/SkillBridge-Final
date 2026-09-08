"""Path discovery helpers for tests that inspect frontend sources.

The project can be checked out as a normal ``backend/`` + ``frontend/`` pair or
inside transferred/nested workspace copies. These helpers find the real source
roots by walking upward from this file instead of assuming one fixed depth.
"""
import os
from pathlib import Path


def _ancestors(start):
    path = Path(start).resolve()
    if path.is_file():
        path = path.parent
    yield path
    yield from path.parents


def _is_frontend_root(path):
    return (
        (path / "package.json").is_file()
        and (path / "src").is_dir()
        and (path / "scripts").is_dir()
    )


def _is_backend_root(path):
    return (path / "app" / "main.py").is_file() and (path / "tests").is_dir()


def find_frontend_root(start=__file__):
    for base in _ancestors(start):
        if _is_frontend_root(base):
            return base
        candidate = base / "frontend"
        if _is_frontend_root(candidate):
            return candidate
    raise AssertionError("Could not locate frontend root containing frontend/package.json")


def find_backend_root(start=__file__):
    for base in _ancestors(start):
        if _is_backend_root(base):
            return base
        candidate = base / "backend"
        if _is_backend_root(candidate):
            return candidate
    raise AssertionError("Could not locate backend root containing backend/app/main.py")


FRONTEND_ROOT = find_frontend_root()
BACKEND_ROOT = find_backend_root()
WORKSPACE_ROOT = Path(os.path.commonpath([str(FRONTEND_ROOT), str(BACKEND_ROOT)]))


def node_env():
    env = os.environ.copy()
    env["SKILLBRIDGE_FRONTEND_ROOT"] = str(FRONTEND_ROOT)
    env["SKILLBRIDGE_BACKEND_ROOT"] = str(BACKEND_ROOT)
    return env


def checker_script(name):
    return FRONTEND_ROOT / "scripts" / name
