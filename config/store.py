"""
Settings store: defaults < data/settings.json < environment < per-call overrides.

The store is hot-reloadable (file mtime based) so the web settings page can
change behaviour without restarting Flask, and thread-local overrides let the
backtest optimizer evaluate hundreds of parameter combinations in one process.
"""

import json
import os
import threading
import copy
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config.definition import DEFAULTS, ITEMS, Item

REPO_ROOT = Path(__file__).resolve().parent.parent

# Generic env prefix, e.g. AITRADER_ENTRY_THRESHOLD=25
ENV_PREFIX = "AITRADER_"

# Legacy env names kept working (documented in .env.example).
LEGACY_ENV = {
    "SYMBOL": "symbol",
    "EXCHANGE_ID": "exchange_id",
    "PROXY_URL": "proxy_url",
    "INITIAL_BALANCE": "initial_balance",
    "QUOTE": "quote",
}

_NUM_TYPES = ("int", "float")


# =====================================================================
# paths
# =====================================================================

def settings_file() -> Path:
    override = os.getenv("AITRADER_SETTINGS_FILE")
    if override:
        return Path(override).expanduser()
    return REPO_ROOT / "data" / "settings.json"


def resolve_path(value: str) -> Path:
    """Resolve a user-provided relative path against the repo root."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else (REPO_ROOT / path)


# =====================================================================
# coercion / validation
# =====================================================================

def _parse_number(item: Item, raw: Any) -> float:
    if isinstance(raw, bool):
        raise ValueError("expected a number")
    if isinstance(raw, (int, float)):
        value = float(raw)
    else:
        text = str(raw).strip().replace(",", "").replace("٬", "")
        if not text:
            raise ValueError("empty value")
        value = float(text)
    if item.type == "int":
        if abs(value - round(value)) > 1e-9:
            raise ValueError("must be a whole number")
        value = round(value)
    return value


def _parse_list(item: Item, raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, (list, tuple)):
        out = [str(x).strip() for x in raw]
        return [x for x in out if x]
    text = str(raw).strip()
    if not text:
        return []
    if text.startswith("["):
        data = json.loads(text)
        if not isinstance(data, list):
            raise ValueError("expected a JSON array")
        return [str(x).strip() for x in data if str(x).strip()]
    parts = [p.strip() for p in text.replace(";", "\n").replace(",", "\n").splitlines()]
    return [p for p in parts if p]


def _parse_dict(item: Item, raw: Any) -> Dict[str, Any]:
    if raw in (None, "", {}, []):
        return {}
    if isinstance(raw, dict):
        return copy.deepcopy(raw)
    text = str(raw).strip()
    if not text:
        return {}
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("expected a JSON object")
    return data


def coerce(item: Item, raw: Any) -> Any:
    """Turn a raw value (form field / JSON / env string) into a typed value."""
    if item.type == "bool":
        if isinstance(raw, bool):
            return raw
        text = str(raw).strip().lower()
        return text in ("1", "true", "yes", "on", "y", "فعال", "بله", "۱")

    if item.type in _NUM_TYPES:
        value = _parse_number(item, raw)
        if item.min is not None and value < item.min:
            raise ValueError(f"must be >= {item.min:g}")
        if item.max is not None and value > item.max:
            raise ValueError(f"must be <= {item.max:g}")
        return int(value) if item.type == "int" else float(value)

    if item.type == "int_list":
        return [int(float(x)) for x in _parse_list(item, raw)]

    if item.type == "list":
        values = _parse_list(item, raw)
        if item.min is not None and len(values) < int(item.min):
            raise ValueError(f"needs at least {int(item.min)} entries")
        return values

    if item.type == "dict":
        return _parse_dict(item, raw)

    # str / text / enum
    if raw is None:
        raw = ""
    value = str(raw).strip()
    if item.type == "enum":
        allowed = [str(c).lower() for c in item.choices]
        if value.lower() not in allowed:
            raise ValueError(f"choose one of: {', '.join(item.choices)}")
        return value.lower()
    if item.max is not None and len(value) > int(item.max):
        raise ValueError(f"too long (max {int(item.max)} chars)")
    return value


def validate(partial: Dict[str, Any], *, strict: bool = True) -> Tuple[Dict[str, Any], Dict[str, str]]:
    """Validate a mapping of raw values. Returns (clean_values, errors)."""
    clean: Dict[str, Any] = {}
    errors: Dict[str, str] = {}

    for key, raw in (partial or {}).items():
        item = ITEMS.get(key)
        if item is None:
            if strict:
                errors[key] = "unknown setting"
            continue
        try:
            clean[key] = coerce(item, raw)
        except Exception as exc:  # noqa: BLE001 - surfaced to the UI
            errors[key] = str(exc)

    # Cross-field checks that keep the analysis pipeline coherent.
    for lo, hi in (
        ("rsi_oversold", "rsi_overbought"),
        ("ema_fast", "ema_mid"),
        ("ema_mid", "ema_slow"),
        ("macd_fast", "macd_slow"),
        ("tp1_r", "tp2_r"),
        ("rsi_long_min", "rsi_long_max"),
        ("rsi_short_min", "rsi_short_max"),
        ("neutral_threshold", "entry_threshold"),
    ):
        if lo in clean and hi in clean and clean[lo] >= clean[hi]:
            errors[hi] = f"must be greater than {lo} ({clean[lo]:g})"

    if clean.get("funding_crowded") is not None and clean.get("funding_extreme") is not None:
        if clean["funding_crowded"] > clean["funding_extreme"]:
            errors["funding_extreme"] = "must be >= funding_crowded"

    return clean, errors


# =====================================================================
# layers
# =====================================================================

def _read_file(path: Path) -> Tuple[Dict[str, Any], Optional[str]]:
    if not path.exists():
        return {}, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {}, f"settings file ignored ({exc.__class__.__name__}: {exc})"
    if not isinstance(data, dict):
        return {}, "settings file must contain a JSON object"
    return data, None


def _env_layer() -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for env_name, key in LEGACY_ENV.items():
        value = os.getenv(env_name)
        if value:
            out[key] = value
    for env_name, value in os.environ.items():
        if env_name.startswith(ENV_PREFIX):
            key = env_name[len(ENV_PREFIX):].lower()
            if key in ITEMS and value != "":
                out[key] = value
    return out


class Settings:
    """Immutable snapshot of the effective configuration."""

    __slots__ = ("_values", "_errors", "_source_mtime")

    def __init__(self, values: Dict[str, Any], errors: Optional[Dict[str, str]] = None,
                 source_mtime: Optional[float] = None):
        object.__setattr__(self, "_values", values)
        object.__setattr__(self, "_errors", errors or {})
        object.__setattr__(self, "_source_mtime", source_mtime)

    # -- access ------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        return self._values.get(key, default)

    def __getattr__(self, key: str) -> Any:
        try:
            return self._values[key]
        except KeyError:  # noqa: PERF203
            raise AttributeError(key) from None

    def __getitem__(self, key: str) -> Any:
        return self._values[key]

    def __contains__(self, key: str) -> bool:
        return key in self._values

    def to_dict(self) -> Dict[str, Any]:
        return copy.deepcopy(self._values)

    # Back-compat with the old UPPER_CASE constants.
    def const(self, name: str) -> Any:
        return self._values[name.lower()]

    # -- helpers -----------------------------------------------------
    @property
    def errors(self) -> Dict[str, str]:
        return dict(self._errors)

    def timeframe_list(self) -> List[str]:
        tfs = [t.strip() for t in str(self._values["timeframes"]).replace(",", " ").split() if t.strip()]
        if len(tfs) < 3:
            tfs = ["15m", "1h", "4h"]
        return tfs[:3]

    @property
    def tf_base(self) -> str:
        return self.timeframe_list()[0]

    @property
    def tf_mid(self) -> str:
        return self.timeframe_list()[1]

    @property
    def tf_high(self) -> str:
        return self.timeframe_list()[2]

    @property
    def timeframe_labels(self) -> List[str]:
        return [tf.upper() for tf in self.timeframe_list()]

    def weights(self) -> Dict[str, float]:
        keys = {
            "trend": "weight_trend",
            "momentum": "weight_momentum",
            "volume": "weight_volume",
            "ms": "weight_structure",
            "tf": "weight_alignment",
            "vol": "weight_volatility",
            "sr": "weight_levels",
            "news": "weight_news",
            "derivatives": "weight_derivatives",
            "micro": "weight_micro",
            "cross": "weight_cross_asset",
        }
        return {name: float(self._values[cfg]) for name, cfg in keys.items()}

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Settings {len(self._values)} keys>"


# =====================================================================
# store
# =====================================================================

class SettingsStore:
    """Loads, validates and persists the settings; broadcast changes."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path
        self._lock = threading.RLock()
        self._snapshot: Optional[Settings] = None
        self._file_mtime: Optional[float] = None
        self._overrides: threading.local = threading.local()
        self._listeners: List = []

    # -- file --------------------------------------------------------
    @property
    def path(self) -> Path:
        return self._path or settings_file()

    def user_settings(self) -> Dict[str, Any]:
        data, _ = _read_file(self.path)
        return data

    # -- snapshot ----------------------------------------------------
    def current(self) -> Settings:
        overrides = getattr(self._overrides, "stack", None)
        path = self.path

        mtime = None
        if path.exists():
            try:
                mtime = path.stat().st_mtime
            except OSError:
                mtime = None

        with self._lock:
            stale = self._snapshot is None or (mtime is not None and mtime != self._file_mtime)
            if stale:
                self._snapshot = self._build(path, mtime)
            snapshot = self._snapshot

        if not overrides:
            return snapshot

        merged = snapshot.to_dict()
        clean, errors = validate(overrides[-1], strict=False)
        merged.update(clean)
        return Settings(merged, errors)

    def _build(self, path: Path, mtime: Optional[float]) -> Settings:
        file_data, file_error = _read_file(path)
        merged = dict(DEFAULTS)
        errors: Dict[str, str] = {}

        clean, errs = validate(file_data, strict=False)
        merged.update(clean)
        errors.update(errs)

        clean_env, errs_env = validate(_env_layer(), strict=False)
        merged.update(clean_env)
        errors.update(errs_env)

        # Final pass through the validators so an out-of-range hand edit can
        # never produce a broken run: clamp numbers, fall back on defaults.
        for key, item in ITEMS.items():
            if key in errors:
                merged[key] = copy.deepcopy(item.default)
                continue
            try:
                merged[key] = coerce(item, merged.get(key, item.default))
            except Exception:  # noqa: BLE001
                merged[key] = copy.deepcopy(item.default)
                errors[key] = "invalid value in settings file — default used"

        if file_error:
            errors["__file__"] = file_error

        self._file_mtime = mtime
        return Settings(merged, errors)

    def reload(self) -> Settings:
        with self._lock:
            self._snapshot = None
        snapshot = self.current()
        self._notify(snapshot)
        return snapshot

    # -- persistence -------------------------------------------------
    def save(self, partial: Dict[str, Any]) -> Tuple[Settings, Dict[str, str]]:
        """Persist user overrides. Returns (settings, errors)."""
        clean, errors = validate(partial, strict=True)
        if errors:
            return self.current(), errors

        path = self.path
        path.parent.mkdir(parents=True, exist_ok=True)

        merged_user = self.user_settings()
        merged_user.update(clean)

        # Drop entries that are identical to the default to keep the file small.
        merged_user = {
            key: value for key, value in merged_user.items()
            if key in ITEMS and value != DEFAULTS[key]
        }
        merged_user = dict(sorted(merged_user.items()))

        payload = {"_meta": {"written_by": "ai-trader settings store"}, **merged_user}
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)

        snapshot = self.reload()
        return snapshot, {}

    def update(self, partial: Dict[str, Any]) -> Dict[str, str]:
        """Save without returning the snapshot; errors dict for the API."""
        _, errors = self.save(partial)
        return errors

    def reset(self) -> Settings:
        path = self.path
        if path.exists():
            path.unlink()
        return self.reload()

    # -- overrides (optimizer) ---------------------------------------
    def push_overrides(self, values: Dict[str, Any]) -> None:
        stack = getattr(self._overrides, "stack", None)
        if stack is None:
            stack = []
            self._overrides.stack = stack
        stack.append(dict(values))

    def pop_overrides(self) -> None:
        stack = getattr(self._overrides, "stack", None)
        if stack:
            stack.pop()

    # -- listeners ----------------------------------------------------
    def add_listener(self, callback) -> None:
        with self._lock:
            if callback not in self._listeners:
                self._listeners.append(callback)

    def _notify(self, snapshot: Settings) -> None:
        for callback in list(self._listeners):
            try:
                callback(snapshot)
            except Exception:  # noqa: BLE001 - a listener must never break config
                pass


STORE = SettingsStore()


def get_settings() -> Settings:
    return STORE.current()


def reload_settings() -> Settings:
    return STORE.reload()


def save_settings(partial: Dict[str, Any]) -> Tuple[Settings, Dict[str, str]]:
    return STORE.save(partial)


def reset_settings() -> Settings:
    return STORE.reset()


class override_settings:
    """Context manager applying temporary settings (used by the optimizer).

    >>> with override_settings(entry_threshold=25):
    ...     ...
    """

    def __init__(self, **values: Any):
        self._values = values

    def __enter__(self) -> Settings:
        STORE.push_overrides(self._values)
        return get_settings()

    def __exit__(self, exc_type, exc, tb) -> bool:
        STORE.pop_overrides()
        return False


# =====================================================================
# schema for the web UI
# =====================================================================

def schema_payload() -> Dict[str, Any]:
    from config.definition import ui_groups

    settings = get_settings()
    groups = ui_groups()
    for group in groups:
        for item in group["items"]:
            key = item["key"]
            value = settings.get(key)
            item["value"] = value
            item["default"] = DEFAULTS[key]
            item["is_default"] = value == DEFAULTS[key]
            if isinstance(value, (list, dict)):
                item["text"] = json.dumps(value, indent=2, ensure_ascii=False)
            elif isinstance(value, bool):
                item["text"] = "1" if value else "0"
            elif value is None:
                item["text"] = ""
            else:
                item["text"] = str(value)

            # what the rendered widget holds, so the UI can diff against it
            if item["type"] == "list":
                item["widget"] = "\n".join(str(entry) for entry in (value or []))
            elif item["type"] == "dict":
                item["widget"] = json.dumps(value, indent=2, ensure_ascii=False) if value else ""
            elif item["type"] == "bool":
                item["widget"] = bool(value)
            else:
                item["widget"] = "" if value is None else value
            item["error"] = settings.errors.get(key)
    widgets = {}
    for group in groups:
        for item in group["items"]:
            widgets[item["key"]] = item.get("widget", item.get("value"))

    return {
        "widgets": widgets,
        "groups": groups,
        "errors": {k: v for k, v in settings.errors.items() if k != "__file__"},
        "file_error": settings.errors.get("__file__"),
        "file": str(STORE.path),
        "file_exists": STORE.path.exists(),
    }


def export_settings() -> str:
    return json.dumps(get_settings().to_dict(), indent=2, ensure_ascii=False)


__all__ = [
    "STORE", "Settings", "SettingsStore", "coerce", "export_settings", "get_settings",
    "override_settings", "reload_settings", "reset_settings", "resolve_path",
    "save_settings", "schema_payload", "settings_file", "validate",
]
