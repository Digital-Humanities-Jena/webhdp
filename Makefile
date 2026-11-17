.PHONY: help setup doctor test test-backend test-frontend frontend-build frontend-dev hpc-link-test hpc-link-frontend local-edm-validator-setup local-edm-validator-verify hdp-components-check compose-check devcontainer-check docs-check release-assets-check api-contract api-contract-check golden-workflow verify-onboarding

help:
	@echo "WebHDP developer commands"
	@echo ""
	@echo "  make setup              Install root and frontend dependencies"
	@echo "  make doctor             Run a contributor environment health report"
	@echo "  make test               Run backend and frontend unit checks"
	@echo "  make test-backend       Run Python backend tests"
	@echo "  make test-frontend      Run Vue/Vitest tests"
	@echo "  make frontend-build     Build the Vue frontend"
	@echo "  make frontend-dev       Start the Vue dev server"
	@echo "  make hpc-link-test      Run HPC Link backend tests"
	@echo "  make hpc-link-frontend  Lint and build the HPC Link frontend"
	@echo "  make local-edm-validator-setup  Clone/pin local EDM validator source"
	@echo "  make local-edm-validator-verify Verify pinned local EDM validator source"
	@echo "  make hdp-components-check Validate local HDP Component manifests"
	@echo "  make compose-check      Validate development and production Compose files"
	@echo "  make devcontainer-check Build the Devcontainer image with configured features"
	@echo "  make docs-check         Validate developer docs and docs catalog"
	@echo "  make release-assets-check Validate curated release media/assets"
	@echo "  make api-contract       Regenerate WebHDP and WebHDP-Link API specs"
	@echo "  make api-contract-check Fail if either API spec is stale"
	@echo "  make golden-workflow    Run the local fixture-backed onboarding workflow"
	@echo "  make verify-onboarding  Run onboarding-oriented validation checks"

setup:
	uv sync --group dev
	cd frontend && npm ci

doctor:
	uv run python scripts/doctor.py

test: hdp-components-check test-backend test-frontend

test-backend:
	uv run pytest

test-frontend:
	cd frontend && npm run test:unit

frontend-build:
	cd frontend && npm run build

frontend-dev:
	cd frontend && npm run dev

hpc-link-test:
	cd hpc-link && uv run --with pytest --with pytest-asyncio --with-requirements requirements.lock python -m pytest

hpc-link-frontend:
	cd hpc-link/frontend && npm run lint && npm run build && npm audit --omit=dev --audit-level=moderate

local-edm-validator-setup:
	bash scripts/setup_local_edm_validator.sh

local-edm-validator-verify:
	bash scripts/setup_local_edm_validator.sh --verify-only

hdp-components-check:
	uv run python scripts/validate_hdp_components.py

compose-check:
	@created_env=0; \
	if [ ! -e .env ]; then cp .env.example .env; created_env=1; fi; \
	trap 'if [ "$$created_env" -eq 1 ]; then rm -f .env; fi' EXIT; \
	docker compose config --quiet; \
	docker compose -f docker-compose.prod.yml config --quiet

devcontainer-check:
	node -e "JSON.parse(require('fs').readFileSync('.devcontainer/devcontainer.json', 'utf8'))"
	docker build -f .devcontainer/Dockerfile .devcontainer
	npx --yes @devcontainers/cli build --workspace-folder .

docs-check:
	uv run python scripts/check_developer_docs.py

release-assets-check:
	uv run python scripts/check_release_assets.py

api-contract:
	uv run python scripts/generate_openapi.py

api-contract-check:
	uv run python scripts/check_openapi_fresh.py

golden-workflow:
	uv run python scripts/run_golden_workflow.py

verify-onboarding: docs-check release-assets-check api-contract-check hdp-components-check golden-workflow
	git diff --check
