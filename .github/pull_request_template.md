## Summary

- What changed:
- Why it changed:

## Surfaces Changed

- [ ] Backend API/routes
- [ ] Backend services/tasks
- [ ] Database models/migrations
- [ ] Frontend services/stores/views
- [ ] HPC Link
- [ ] Docker/deployment/config
- [ ] Documentation only

## Verification

- [ ] Backend tests: `uv run pytest`
- [ ] Frontend unit tests: `cd frontend && npm run test:unit`
- [ ] Frontend build: `cd frontend && npm run build`
- [ ] Frontend e2e tests: `cd frontend && npm run test:e2e`
- [ ] HPC Link backend tests: `cd hpc-link && python -m pytest`
- [ ] HPC Link frontend checks: `cd hpc-link/frontend && npm run lint && npm run build`
- [ ] Compose validation: `docker compose config --quiet`
- [ ] Not applicable; explain below

## Notes For Reviewers

- Migrations, environment variables, feature flags, or deployment steps:
- Security/privacy considerations:
- ADR needed or updated for workflow, persistence, auth, deployment, or API contract changes:
- Generated API contract updated or confirmed fresh with `make api-contract-check`:
- Known follow-up work:
