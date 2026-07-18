"""Loading the watcher config and the on-disk notified-state.

`config.json` and `state.json` live at the repo root (the package dir's parent) so the
GitHub Actions runner can read the config and commit the state back next to the code.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config.json"
STATE_PATH = ROOT / "state.json"


def _load_json(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def load_config():
    """Return the parsed config.json, or exit with a helpful message if it's missing."""
    cfg = _load_json(CONFIG_PATH, None)
    if cfg is None:
        raise SystemExit("config.json not found — copy config.example.json and fill it in.")
    return cfg


def load_state():
    """Return the notified-state (which seat-pairs we've already alerted on)."""
    return _load_json(STATE_PATH, {})


def save_state(state):
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True))
