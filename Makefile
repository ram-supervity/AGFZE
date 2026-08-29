COMPOSE ?= docker compose
TEST_DATABASE_URL ?= postgresql+asyncpg://agfze:agfze@postgres:5432/agfze_test

# The backend image runs as its own unprivileged uid, which owns /app/var but not the host source
# tree. Targets that write generated files or tool caches back into the bind mount therefore run
# as the host owner instead.
HOST_USER := --user $(shell id -u):$(shell id -g)

.DEFAULT_GOAL := help

help: ## Show this help
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "} {printf "  %-15s %s\n", $$1, $$2}'

setup: ## First run: env files, images, infrastructure, schema, seeded logins
	@[ -f backend/.env ] || cp backend/.env.example backend/.env
	@[ -f frontend/.env ] || cp frontend/.env.example frontend/.env
	$(COMPOSE) build
	$(COMPOSE) up -d postgres keycloak
	@printf 'waiting for postgres'
	@i=0; until [ "$$(docker inspect -f '{{.State.Health.Status}}' agfze-postgres 2>/dev/null)" = healthy ]; do \
		i=$$((i+1)); \
		[ $$i -lt 60 ] || { printf ' timed out\n'; exit 1; }; \
		printf '.'; sleep 2; \
	done; printf ' ready\n'
	@$(MAKE) --no-print-directory migrate
	@echo ''
	@echo 'Seeded Keycloak logins - local development only, password Passw0rd!'
	@echo ''
	@echo '  username        email                         roles'
	@echo '  --------------  ----------------------------  ---------------------------'
	@echo '  hod.approver    hod.approver@agfze.local      approver_hod'
	@echo '  purchase.user   purchase.user@agfze.local     purchase_user'
	@echo '  sales.user      sales.user@agfze.local        sales_user'
	@echo '  fa.user         fa.user@agfze.local           fa_user'
	@echo '  logistics.user  logistics.user@agfze.local    logistics_user'
	@echo '  finance.user    finance.user@agfze.local      finance_user'
	@echo '  admin.user      admin.user@agfze.local        admin'
	@echo '  auditor.user    auditor.user@agfze.local      auditor'
	@echo '  dual.user       dual.user@agfze.local         purchase_user, approver_hod'
	@echo ''
	@echo 'The realm also seeds the agfze-admin-api service-account client the /admin/users role'
	@echo 'override calls. It has no interactive login and one grant - realm-management:'
	@echo 'manage-users - so the override is genuinely testable against a real local Keycloak.'
	@echo ''
	@echo 'Next: make dev'

dev: ## Start the full stack in the foreground
	$(COMPOSE) up

down: ## Stop the stack and remove its containers
	$(COMPOSE) down

logs: ## Follow logs for every service
	$(COMPOSE) logs -f --tail=100

migrate: ## Apply all Alembic migrations
	$(COMPOSE) run --rm backend alembic upgrade head

seed-demo: ## Write local sample data for the sales workflow (never runs in production)
	$(COMPOSE) run --rm backend python -m scripts.seed_sales_demo

mail: ## Start the local SMTP catcher and print where to read what was "sent"
	$(COMPOSE) up -d mailhog
	@echo 'MailHog is up. Every notification email this platform sends locally lands at'
	@echo '  http://localhost:8025'
	@echo 'and nothing leaves your machine. Never point SMTP_HOST at a real relay in development.'

vapid-keys: ## Print a fresh VAPID key pair to paste into backend/.env (generate once, then keep it)
	@$(COMPOSE) run --rm --no-deps -T backend python -m scripts.generate_vapid_keys
	@echo ''
	@echo 'Paste both lines into backend/.env, and the PUBLIC one into frontend/.env as'
	@echo 'NEXT_PUBLIC_VAPID_PUBLIC_KEY. Regenerating this pair invalidates every push'
	@echo 'subscription every browser has ever taken, so generate it once per environment.'

icons: ## Regenerate the PWA icon set from the brand mark
	cd frontend && node scripts/generate-icons.mjs

rebuild-graph: ## Rebuild the Neo4j traceability projection from the relational store
	# Always safe: the projection is derived and nothing on the platform reads it, so it can be
	# thrown away and rebuilt at any time. Refuses to run when no store is configured.
	$(COMPOSE) run --rm backend python -m scripts.rebuild_graph

templates: ## Rebuild the shipped sales DOCX templates from their declaration
	$(COMPOSE) run --rm $(HOST_USER) backend python -m app.services.templates.sales_templates

migration: ## Autogenerate a migration: make migration m="add shipments table"
	@[ -n "$(m)" ] || { echo 'usage: make migration m="short description"'; exit 1; }
	$(COMPOSE) run --rm $(HOST_USER) backend alembic revision --autogenerate -m "$(m)"

test: test-backend test-frontend ## Run every test suite

test-backend: ## Run pytest against the agfze_test database
	$(COMPOSE) up -d postgres
	$(COMPOSE) run --rm $(HOST_USER) -e ENV=testing -e TEST_DATABASE_URL=$(TEST_DATABASE_URL) backend sh -c "pytest -q"

test-frontend: ## Run the vitest suite (needs Node 22 and frontend/node_modules)
	cd frontend && npm run test

verify-sw: ## Check the built service worker's precache manifest against the current build
	cd frontend && npm run verify:sw

verify-production: ## Read the production estate back and fail on anything not actually configured
	@[ -n "$(project)" ] || { echo 'usage: make verify-production project=<gcp-project-id>'; exit 1; }
	./infra/production/verify-production.sh $(project) $(or $(region),me-central1)

lint: lint-backend lint-frontend ## Lint both applications

lint-backend: ## Ruff check the backend
	$(COMPOSE) run --rm $(HOST_USER) backend ruff check .

lint-frontend: ## ESLint and type-check the frontend
	cd frontend && npm run lint && npm run typecheck

format-check: ## Fail if anything is unformatted, exactly as CI does
	$(COMPOSE) run --rm backend ruff format --check .
	cd frontend && npx eslint . --max-warnings=0

format: ## Ruff format and autofix the backend
	$(COMPOSE) run --rm $(HOST_USER) backend sh -c "ruff format . && ruff check --fix ."

lock: ## Recompile requirements.txt and the hash-pinned requirements.lock
	$(COMPOSE) run --rm $(HOST_USER) backend sh -c "pip-compile --strip-extras requirements.in -o requirements.txt && pip-compile --strip-extras --generate-hashes requirements.in -o requirements.lock"

realm-import: ## Recreate Keycloak so realm-agfze.json is imported again
	# start-dev keeps its H2 store inside the container and only imports a realm that
	# does not exist yet, so the container has to be discarded for a fresh import.
	$(COMPOSE) rm -sf keycloak
	$(COMPOSE) up -d keycloak

clean: ## Remove containers, named volumes and local build artefacts
	$(COMPOSE) down -v --remove-orphans
	rm -rf backend/.pytest_cache backend/.ruff_cache backend/var frontend/.next frontend/node_modules

.PHONY: help setup dev down logs migrate migration seed-demo mail vapid-keys icons rebuild-graph templates test test-backend test-frontend verify-sw verify-production lint lint-backend lint-frontend format format-check lock realm-import clean
