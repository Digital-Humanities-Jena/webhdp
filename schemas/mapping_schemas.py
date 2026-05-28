from pydantic import BaseModel, ConfigDict, model_validator
from typing import Dict, Literal, Optional

class MappingItem(BaseModel):
    source: Literal['msf', 'zenodo', 'static', 'options', 'skip']
    field: Optional[str] = ""
    value: Optional[str] = ""

    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="after")
    def validate_source_specific_requirements(self):
        source = str(self.source or "").strip().lower()
        field = str(self.field or "").strip()
        value = str(self.value or "").strip()

        if source in {"msf", "zenodo"} and not field:
            raise ValueError(f"Mapping source '{source}' requires a non-empty 'field'.")
        if source in {"static", "options"} and not value:
            raise ValueError(f"Mapping source '{source}' requires a non-empty 'value'.")
        return self

# Structure: { std_id: { modality_id: { tag_id: MappingItem } } }
# But keys are dynamic (tag_id, modality_id)

class ModalityMapping(BaseModel):
    # Keys are tag IDs (e.g., 'dc:title', 'edm:type')
    # Use root_validator or just Dict[str, MappingItem]
    # Since we can't fully predict all tag IDs in schema without duplication, Dict is flexible.
    # However, we can enforce that values are MappingItems.
    pass

# Using Dict for flexibility as the tag names are extensive
MappingConfig = Dict[str, Dict[str, Dict[str, MappingItem]]]

class MappingExportRequest(BaseModel):
    mapping: MappingConfig

class MappingImportResponse(BaseModel):
    valid: bool
    mapping: Optional[MappingConfig] = None
    errors: Optional[list] = None
