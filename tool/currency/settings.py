import shutil
from pathlib import Path

import yaml

from route import PATHS
from tool import EXTRA

EXIT_PLANES = (1, 2, 3)
DEFAULT_EXIT_PLANE = 1
DEFAULT_EXIT_IF_NO_PRIOR = False
DEFAULT_PRIOR_EXIT_PLANE = None

CONFIG_PATH = Path(PATHS["root"]) / "config" / "config" / "currency_config.yml"
EXAMPLE_PATH = CONFIG_PATH.with_name("currency_config_example.yml")


def normalize_currency_settings(values=None):
    """Validate currency-war settings and return serializable values."""
    values = values if isinstance(values, dict) else {}
    try:
        exit_plane = int(values.get("exit_after_plane", DEFAULT_EXIT_PLANE))
    except (TypeError, ValueError):
        exit_plane = DEFAULT_EXIT_PLANE
    if exit_plane not in EXIT_PLANES:
        exit_plane = DEFAULT_EXIT_PLANE

    exit_if_no_prior = values.get(
        "exit_if_no_prior",
        DEFAULT_EXIT_IF_NO_PRIOR,
    )
    if not isinstance(exit_if_no_prior, bool):
        exit_if_no_prior = DEFAULT_EXIT_IF_NO_PRIOR

    prior_exit_plane = values.get(
        "prior_exit_plane",
        DEFAULT_PRIOR_EXIT_PLANE,
    )
    if prior_exit_plane is not None:
        try:
            prior_exit_plane = int(prior_exit_plane)
        except (TypeError, ValueError):
            prior_exit_plane = DEFAULT_PRIOR_EXIT_PLANE

        if prior_exit_plane not in EXIT_PLANES:
            prior_exit_plane = DEFAULT_PRIOR_EXIT_PLANE

    return {
        "exit_after_plane": exit_plane,
        "exit_if_no_prior": exit_if_no_prior,
        "prior_exit_plane": prior_exit_plane,
    }


def load_currency_settings(path=CONFIG_PATH):
    """Load the currency-war settings, falling back to safe defaults."""
    path = Path(path)
    if not path.exists() and path == CONFIG_PATH and EXAMPLE_PATH.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(EXAMPLE_PATH, path)
    if not path.exists():
        return normalize_currency_settings()

    with EXTRA.FILE_LOCK:
        try:
            with path.open(encoding="utf-8") as config_file:
                values = yaml.safe_load(config_file) or {}
        except (OSError, yaml.YAMLError):
            values = {}
    return normalize_currency_settings(values)


def save_currency_settings(values, path=CONFIG_PATH):
    """Update currency-war settings while preserving future config fields."""
    path = Path(path)
    normalized = normalize_currency_settings(values)
    with EXTRA.FILE_LOCK:
        try:
            current = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            current = {}
        if not isinstance(current, dict):
            current = {}
        current.update(normalized)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            yaml.safe_dump(current, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
    return normalized
