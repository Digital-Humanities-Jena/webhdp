"""
Backward-compatible imports for the legacy METIS Sandbox client name.

WebHDP now targets local-edm-validator by default. The endpoint contract is
compatible with METIS Sandbox `/record/validation`, so the old class names stay
available for scripts that still import them.
"""
from services.local_edm_validator_client import (
    LocalEdmValidatorClient,
    LocalEdmValidatorClientError,
)

MetisSandboxClientError = LocalEdmValidatorClientError


class MetisSandboxClient(LocalEdmValidatorClient):
    """Compatibility alias for older code paths."""
