"""Deployment files live outside the installed Python package.

Editable checkouts default to the repository root. Wheel deployments default
to the working directory and should set APP_ROOT (the image uses /app).
Individual paths can also be set explicitly; relative paths use APP_ROOT.
"""

import os
from pathlib import Path


def deployment_root() -> Path:
    checkout = Path(__file__).resolve().parents[2]
    default = checkout if (checkout / "pyproject.toml").is_file() else Path.cwd()
    return Path(os.getenv("APP_ROOT", str(default))).expanduser().resolve()


def deployment_path(setting: str, default: str) -> Path:
    path = Path(os.getenv(setting, default)).expanduser()
    return (deployment_root() / path).resolve()
