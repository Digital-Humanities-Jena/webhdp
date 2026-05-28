import json
from typing import Any, Dict

from database.database import db
from database.models import SystemConfig


class VersionDetectionPolicyService:
    CONFIG_KEY = "version_detection_policy"
    DEFAULT_PRESET = "balanced"
    VALID_PRESETS = {"strict", "balanced", "permissive"}
    DEFAULT_ALLOW_FORCE_CREATE_FRESH = True
    DEFAULT_ENABLED_SIGNALS = {
        "hash_matching": True,
        "metadata_similarity": True,
    }
    DEFAULT_HASH_COLLISION_POLICY = {
        "enabled": True,
        "min_size_bytes": 1024 * 1024,
        "excluded_extensions": [".csv", ".json", ".log", ".md", ".text", ".tsv", ".txt", ".xml"],
        "exclude_generated_renders": True,
    }
    PRESET_THRESHOLDS = {
        "strict": {
            "version_recommendation_score": 0.95,
            "warning_score": 0.45,
        },
        "balanced": {
            "version_recommendation_score": 0.90,
            "warning_score": 0.35,
        },
        "permissive": {
            "version_recommendation_score": 0.80,
            "warning_score": 0.25,
        },
    }

    @classmethod
    def _normalize_preset(cls, raw_value: Any) -> str:
        preset = str(raw_value or cls.DEFAULT_PRESET).strip().lower()
        return preset if preset in cls.VALID_PRESETS else cls.DEFAULT_PRESET

    @classmethod
    def _normalize_signals(cls, raw_value: Any) -> Dict[str, bool]:
        value = raw_value if isinstance(raw_value, dict) else {}
        return {
            "hash_matching": bool(value.get("hash_matching", cls.DEFAULT_ENABLED_SIGNALS["hash_matching"])),
            "metadata_similarity": bool(
                value.get("metadata_similarity", cls.DEFAULT_ENABLED_SIGNALS["metadata_similarity"])
            ),
        }

    @classmethod
    def _normalize_extension(cls, raw_value: Any) -> str | None:
        extension = str(raw_value or "").strip().lower()
        if not extension:
            return None
        if not extension.startswith("."):
            extension = f".{extension}"
        return extension if len(extension) > 1 else None

    @classmethod
    def _normalize_hash_collision_policy(cls, raw_value: Any) -> Dict[str, Any]:
        value = raw_value if isinstance(raw_value, dict) else {}
        defaults = cls.DEFAULT_HASH_COLLISION_POLICY

        try:
            min_size_bytes = int(value.get("min_size_bytes", defaults["min_size_bytes"]))
        except (TypeError, ValueError):
            min_size_bytes = int(defaults["min_size_bytes"])

        raw_extensions = value.get("excluded_extensions", defaults["excluded_extensions"])
        if isinstance(raw_extensions, str):
            raw_extensions = [item.strip() for item in raw_extensions.split(",")]
        if not isinstance(raw_extensions, list):
            raw_extensions = defaults["excluded_extensions"]
        excluded_extensions = sorted(
            {
                extension
                for extension in (cls._normalize_extension(item) for item in raw_extensions)
                if extension
            }
        )

        return {
            "enabled": bool(value.get("enabled", defaults["enabled"])),
            "min_size_bytes": max(min_size_bytes, 0),
            "excluded_extensions": excluded_extensions,
            "exclude_generated_renders": bool(
                value.get("exclude_generated_renders", defaults["exclude_generated_renders"])
            ),
        }

    @classmethod
    def _normalize(cls, raw: Any) -> Dict[str, Any]:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = {}
        if not isinstance(raw, dict):
            raw = {}

        preset = cls._normalize_preset(raw.get("preset"))
        thresholds = dict(cls.PRESET_THRESHOLDS[preset])
        enabled_signals = cls._normalize_signals(raw.get("enabled_signals"))

        return {
            "preset": preset,
            "thresholds": thresholds,
            "allow_force_create_fresh": bool(
                raw.get("allow_force_create_fresh", cls.DEFAULT_ALLOW_FORCE_CREATE_FRESH)
            ),
            "enabled_signals": enabled_signals,
            "hash_collision_policy": cls._normalize_hash_collision_policy(raw.get("hash_collision_policy")),
        }

    @classmethod
    def get_config(cls) -> Dict[str, Any]:
        config_entry = db.session.get(SystemConfig, cls.CONFIG_KEY)
        if not config_entry or not config_entry.value:
            return cls._normalize({})
        return cls._normalize(config_entry.value)

    @classmethod
    def save_config(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        normalized = cls._normalize(data)
        config_entry = db.session.get(SystemConfig, cls.CONFIG_KEY)
        if not config_entry:
            config_entry = SystemConfig(key=cls.CONFIG_KEY)
            db.session.add(config_entry)
        config_entry.value = json.dumps(normalized)
        db.session.commit()
        return normalized

    @classmethod
    def get_effective_config(cls, preset_override: Any = None) -> Dict[str, Any]:
        config = cls.get_config()
        if preset_override is None:
            return config
        preset = cls._normalize_preset(preset_override)
        config["preset"] = preset
        config["thresholds"] = dict(cls.PRESET_THRESHOLDS[preset])
        return config
