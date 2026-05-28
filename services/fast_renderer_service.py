import os
import logging
import requests
from typing import Dict, Any

logger = logging.getLogger(__name__)

class FastRendererService:
    def __init__(self):
        # Determine service URL based on environment
        # If running in Docker (backend service), we can access 'fast-renderer' by hostname
        # If running locally, we access 'localhost:5002'

        # Simple heuristic: Check if we are in a container?
        # Or just use an env var FAST_RENDERER_URL defaulting to localhost:5002
        # but in docker-compose we can set it to http://fast-renderer:5002
        self.service_url = os.environ.get("FAST_RENDERER_URL", "http://localhost:5002")

        # Paths for translation
        # HOST_SHARED_PATH is the path on the Host machine (e.g. /Users/user/hdp-shared)
        # We assume the Fast Renderer container has this mounted at /shared/sessions
        self.host_shared_path = os.environ.get("HOST_SHARED_PATH")
        self.container_mount_point = "/shared/sessions"

    def _translate_to_container_path(self, local_path: str) -> str:
        """
        Translates a path from the WebHDP perspective to the Fast Renderer Container perspective.

        Scenario 1: WebHDP in Docker. local_path starts with /shared/sessions.
                    Fast Renderer sees /shared/sessions. -> Identity.
        Scenario 2: WebHDP Local. local_path starts with /Users/... (HOST_SHARED_PATH).
                    Fast Renderer sees /shared/sessions. -> Translate.
        """
        # If we are in Docker (likely), our path starts with /shared/sessions (or whatever configured)
        # checking if local_path starts with mount point is tricky if they differ.

        # Heuristic: If path starts with HOST_SHARED_PATH, replace it.
        if self.host_shared_path and local_path.startswith(self.host_shared_path):
            # Normalizing slashes just in case
            rel_path = os.path.relpath(local_path, self.host_shared_path)
            return os.path.join(self.container_mount_point, rel_path)

        return local_path

    def render(self, input_path: str, output_dir: str, options: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Send a render request to the Fast Renderer service.
        """
        return self.render_batch([input_path], output_dir, options)

    def render_batch(self, input_paths: list[str], output_dir: str, options: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Send a batch render request to the Fast Renderer service.
        """
        options = options or {}
        engine_raw = options.get("engine")
        if isinstance(engine_raw, str):
            normalized_engine = engine_raw.strip().upper()
            if normalized_engine == "BLENDER_EEVEE_NEXT":
                options = {**options, "engine": "CYCLES"}
            elif normalized_engine and normalized_engine not in {"BLENDER_EEVEE", "BLENDER_WORKBENCH", "CYCLES"}:
                options = {**options, "engine": "CYCLES"}

        # Translate paths
        container_input_files = [self._translate_to_container_path(p) for p in input_paths]
        container_output_dir = self._translate_to_container_path(output_dir)

        # For compatibility, include the containing directory for single-file batches.
        # Older renderer code treated input_path as the scan root, so passing the file path
        # itself could break relative result mapping.
        payload = {
            "input_files": container_input_files,
            "output_dir": container_output_dir,
            **options
        }
        if len(container_input_files) == 1:
            payload["input_path"] = os.path.dirname(container_input_files[0]) or container_input_files[0]

        try:
            logger.info(f"Sending batch render request to {self.service_url}/render for {len(input_paths)} files")
            logger.info(f"Render Payload: {payload}")
            resp = requests.post(f"{self.service_url}/render", json=payload, timeout=3600) # Increased timeout for batch
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.error(f"Render request failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "status": "failed"
            }

    def check_health(self) -> bool:
        """Checks if the Fast Renderer service is reachable."""
        try:
            resp = requests.get(f"{self.service_url}/health", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False
