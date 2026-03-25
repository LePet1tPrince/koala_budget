include custom.mk
# Set the user and group IDs in docker compose to the same as the host user so new files belong to the host user
# instead of root.
# This can be changed to your own user/group ID here, though these defaults should be fine for most people.
export MY_UID := 1000
export MY_GID := 1000

setup-env:
	@[ ! -f ./.env ] && cp ./.env.example ./.env || echo ".env file already exists."
	@[ ! -f ./frontend/.env ] && cp ./frontend/.env.example ./frontend/.env || echo "frontend .env file already exists."

start: ## Start the docker containers
	@echo "Starting the docker containers"
	@docker compose up

stop: ## Stop Containers
	@docker compose down

restart: stop start ## Restart Containers

start-bg:  ## Run containers in the background
	@docker compose up -d

build: ## Build Containers
	@docker compose build

ssh: ## SSH into running web container
	docker compose exec web bash

bash: ## Get a bash shell into the web container
	docker compose run --rm --no-deps web bash

manage: ## Run any manage.py command. E.g. `make manage ARGS='createsuperuser'`
	@docker compose run --rm web python manage.py ${ARGS}

migrations: ## Create DB migrations in the container
	@docker compose run --rm web python manage.py makemigrations

migrate: ## Run DB migrations in the container
	@docker compose run --rm web python manage.py migrate

translations:  ## Rebuild translation files
	@docker compose run --rm --no-deps web python manage.py makemessages --all --ignore node_modules --ignore venv --ignore .venv
	@docker compose run --rm --no-deps web python manage.py makemessages -d djangojs --all --ignore node_modules --ignore venv --ignore .venv
	@docker compose run --rm --no-deps web python manage.py compilemessages --ignore venv --ignore .venv

shell: ## Get a Django shell
	@docker compose run --rm web python manage.py shell

dbshell: ## Get a Database shell
	@docker compose exec db psql -U postgres koala_budget

test: ## Run Django tests
	@docker compose run --rm \
		-e DJANGO_SETTINGS_MODULE=koala_budget.settings_test \
		web python manage.py test ${ARGS}

e2e-install: ## Install Playwright browser binaries (run once after e2e deps install)
	@docker compose run --rm --no-deps web uv run playwright install --with-deps chromium

test-e2e: ## Run E2E tests with Playwright. React-page tests need 'make start-bg' first (Vite dev server).
	@docker compose run --rm \
		-e DJANGO_SETTINGS_MODULE=koala_budget.settings_e2e \
		web uv run pytest e2e/ -v ${ARGS}

test-e2e-accounts: ## Run only the accounts E2E tests (no Vite dev server required)
	@docker compose run --rm \
		-e DJANGO_SETTINGS_MODULE=koala_budget.settings_e2e \
		web uv run pytest e2e/tests/test_auth.py e2e/tests/test_accounts.py -v ${ARGS}


init: setup-env start-bg migrations migrate  ## Quickly get up and running (start containers and bootstrap DB)

uv: ## Run a uv command
	@docker compose run --rm web uv $(filter-out $@,$(MAKECMDGOALS))

uv-sync: ## Sync dependencies
	@docker compose run --rm web uv sync --frozen

requirements: uv-sync build stop start-bg  ## Rebuild your requirements and restart your containers

ruff-format: ## Runs ruff formatter on the codebase
	@docker compose run --rm --no-deps web uv run ruff format .

ruff-lint:  ## Runs ruff linter on the codebase
	@docker compose run --rm --no-deps web uv run ruff check --fix .

ruff: ruff-format ruff-lint ## Formatting and linting using Ruff

npm-install-all: ## Runs npm install
	@docker compose run --rm --no-deps vite npm install

npm-install: ## Runs npm install (optionally accepting package names)
	@docker compose run --rm --no-deps vite npm install $(filter-out $@,$(MAKECMDGOALS))

npm-uninstall: ## Runs npm uninstall (takes package name(s))
	@docker compose run --rm --no-deps vite npm uninstall $(filter-out $@,$(MAKECMDGOALS))

npm-build: ## Runs npm build (for production assets)
	@docker compose run --rm --no-deps vite npm run build

npm-dev: ## Runs npm dev
	@docker compose run --rm --no-deps vite npm run dev

npm-type-check: ## Runs the type checker on the front end TypeScript code
	@docker compose run --rm --no-deps vite npm run type-check

upgrade: requirements migrations migrate npm-install npm-dev  ## Run after a Pegasus upgrade to update requirements, migrate the database, and rebuild the front end

build-api-client:  ## Update the JavaScript API client code.
	@cp ./api-client/package.json ./package.json.api-client
	@rm -rf ./api-client
	@mkdir -p ./api-client
	@mv ./package.json.api-client ./api-client/package.json
	@docker run --rm --network host \
		-v ./api-client:/local \
		--user $(MY_UID):$(MY_GID) \
		openapitools/openapi-generator-cli:v7.9.0 generate \
		-i http://localhost:8000/api/schema/ \
		-g typescript-fetch \
		-o /local/

.PHONY: help
.DEFAULT_GOAL := help

help:
	@grep -hE '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-30s\033[0m %s\n", $$1, $$2}'

# catch-all for any undefined targets - this prevents error messages
# when running things like make npm-install <package>
%:
	@:
