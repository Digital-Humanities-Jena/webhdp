# Fast Renderer Configuration

The **Fast Renderer** is a microservice used to generate 2D previews (images) from 3D models during the ingestion pipeline.

## Enabling / Disabling the Renderer

The renderer is **enabled by default** for supported pipelines (`full_workflow`, `glb_simple`, `ingestion`).

To explicitly disable or re-enable the renderer, you must update the **System Configuration** in the database.

### Configuration Method

The configuration is stored in the `system_config` table. You can modify this via the **Admin Dashboard** (if a UI exists) or directly via SQL.

**Key:** `pipeline_config:<pipeline_id>`
**Value:** JSON Object

#### Example: Disabling the Renderer for `full_workflow`

**Key:** `pipeline_config:full_workflow`
**Value:**
```json
{
  "enabled": false
}
```

#### Example: Enabling with Custom Options

**Key:** `pipeline_config:full_workflow`
**Value:**
```json
{
  "enabled": true,
  "resolution": [1920, 1080],
  "samples": 64,
  "engine": "BLENDER_EEVEE"
}
```

## Infrastructure Requirements

For workstation-local execution, the `fast-renderer` Docker container must be running and WebHDP must be explicitly configured as a local workstation deployment:

```dotenv
WEBHDP_DEPLOYMENT_MODE=local
WEBHDP_ALLOW_LOCAL_HDP_COMPONENTS=true
COMPOSE_PROFILES=local-hdp-components
```

Server/VPS deployments should not run the renderer locally by default. When the renderer step is enabled in server mode, WebHDP expects an active HPC-Link allocation. Low-resource servers should disable the renderer step instead.

### Checking Status
```bash
docker ps | grep fast-renderer
```

### Starting the Service
Ensure the `local-hdp-components` Compose profile is enabled on a workstation-local deployment.

```bash
COMPOSE_PROFILES=local-hdp-components docker compose up -d fast-renderer
```

If the service is stopped or missing on a workstation-local deployment, WebHDP reports the renderer runtime as unavailable. On server/VPS deployments, WebHDP reports the renderer as HPC-required unless the step is disabled.
