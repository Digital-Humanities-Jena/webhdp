# Devcontainer Setup

The WebHDP devcontainer gives new contributors a ready Python 3.11, Node 22, uv, npm, Make, SQLite, and Docker-enabled development environment.

Use it with VS Code Dev Containers or GitHub Codespaces.

## What It Provides

- Python 3.11 matching `.python-version`
- Node.js 22 matching `.nvmrc` and the Vite requirement
- `uv` for Python dependency management
- an isolated container virtual environment at `/home/vscode/.venv/webhdp`
- an isolated `frontend/node_modules` volume so Linux packages do not replace host-machine packages
- `make` targets for onboarding checks
- Docker socket access for Compose workflows
- forwarded ports for Flask, Vite, Docker frontend, Redis, and the local EDM validator
- recommended VS Code extensions for Python, Vue, YAML, TOML, and Docker

## Start In VS Code

1. Install Docker Desktop.
2. Install the VS Code Dev Containers extension.
3. Open the repository folder in VS Code.
4. Run `Dev Containers: Reopen in Container`.

The container runs:

```bash
make setup
make docs-check
make api-contract-check
make golden-workflow
```

`make setup` can take a few minutes the first time because it installs Python and frontend dependencies. Python packages are installed into the container home directory, not the repository `.venv`, and frontend packages are installed into a container volume mounted at `frontend/node_modules`. Using the devcontainer does not replace a host-machine virtual environment or host-machine Node packages.

## Start In Codespaces

Create a Codespace from the repository. The same `.devcontainer/devcontainer.json` config is used.

## Common Commands

```bash
make help
make doctor
make golden-workflow
make test-backend
make test-frontend
make frontend-dev
```

For full Docker Compose validation:

```bash
make compose-check
```

## Running The App

Backend only:

```bash
WEBHDP_INLINE_TASKS=true uv run flask --app app run --debug --host 0.0.0.0
```

Frontend:

```bash
cd frontend
npm run dev -- --host 0.0.0.0
```

Open the forwarded Vite port, usually `5173`.

## Troubleshooting

- If `make setup` fails while installing Node packages, rerun `cd frontend && npm ci`.
- If Docker Compose commands fail, confirm Docker Desktop is running and the devcontainer has Docker socket access.
- If the generated OpenAPI contract is stale, run `make api-contract`.
- If the golden workflow fails, run `uv run python scripts/run_golden_workflow.py --json` for a compact failure payload.
- If VS Code cannot find the Python interpreter, run `UV_PROJECT_ENVIRONMENT=/home/vscode/.venv/webhdp uv sync --group dev` and reload the window.
