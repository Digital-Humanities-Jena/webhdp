"""Invocation-only credentials for explicitly approved WebHDP-Link components."""
from pathlib import Path
import sys

from exceptions import FileProcessingError
from services.zenodo_credential_service import ZenodoCredentialService

COMPONENT = "link_zenodo_sandbox_draft"


def component_environment(request, user_id):
    """Return ephemeral environment only; never store secrets in pipeline JSON."""
    manifest = request.metadata.get('component_manifest') or {}
    if (manifest.get('metadata') or {}).get('name') != COMPONENT:
        return {}
    from external_code.webhdp_link_zenodo.runner import TOKEN_ENV, VERSION, checksum
    runner = Path(__file__).resolve().parents[1] / 'external_code/webhdp_link_zenodo/runner.py'
    entrypoint = request.profile.get('entrypoint') or []
    expected = [str(runner), '--expected-runner-sha256', checksum(runner)]
    if (manifest.get('metadata', {}).get('version') != VERSION or request.profile.get('adapter') != 'local_cli'
            or len(entrypoint) != 4 or entrypoint[1:] != expected
            or Path(entrypoint[0]).resolve() != Path(sys.executable).resolve()):
        raise FileProcessingError('The sandbox credential is restricted to the approved installed component version and executable.')
    service = ZenodoCredentialService()
    credential = service.get_active_credential(int(user_id), 'sandbox')
    if credential is None or credential.environment != 'sandbox':
        raise FileProcessingError('Select an accessible Zenodo Sandbox credential in this WebHDP account before using the sandbox pipeline.')
    token = service.decrypt_value(credential)
    if not token:
        raise FileProcessingError('The selected sandbox credential is unavailable.')
    return {TOKEN_ENV: token}
