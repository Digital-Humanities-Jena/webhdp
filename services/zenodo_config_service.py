import json
from typing import Any, Dict

from database.database import db
from database.models import SystemConfig


class ZenodoConfigService:
    CONFIG_KEY = "zenodo_community_override"
    DEFAULT_ENABLED = False
    DEFAULT_COMMUNITY = "3dbigdataspace"

    @classmethod
    def _normalize(cls, raw: Any) -> Dict[str, Any]:
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                raw = {}
        if not isinstance(raw, dict):
            raw = {}

        enabled = raw.get("enabled", cls.DEFAULT_ENABLED)
        community = str(raw.get("community", cls.DEFAULT_COMMUNITY) or cls.DEFAULT_COMMUNITY).strip()
        if not community:
            community = cls.DEFAULT_COMMUNITY

        return {
            "enabled": bool(enabled),
            "community": community,
        }

    @classmethod
    def get_community_override_config(cls) -> Dict[str, Any]:
        config_entry = db.session.get(SystemConfig, cls.CONFIG_KEY)
        if not config_entry or not config_entry.value:
            return cls._normalize({})
        return cls._normalize(config_entry.value)

    @classmethod
    def save_community_override_config(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        normalized = cls._normalize(data)
        config_entry = db.session.get(SystemConfig, cls.CONFIG_KEY)
        if not config_entry:
            config_entry = SystemConfig(key=cls.CONFIG_KEY)
            db.session.add(config_entry)
        config_entry.value = json.dumps(normalized)
        db.session.commit()
        return normalized

    @classmethod
    def apply_community_override(cls, metadata: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(metadata or {})
        config = cls.get_community_override_config()
        if config.get("enabled"):
            result["communities"] = [{"identifier": config["community"]}]
        return result
