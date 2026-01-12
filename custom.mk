# you can use this file to add custom make targets and avoid conflicting with the main Pegasus makefile

make user_to_superuser: # Promotes a user to a superuser eg. `make user_to_superuser ARGS="tito@redsox.com"`
	@docker compose exec web python manage.py promote_user_to_superuser ${ARGS}


PROJECT=koala_budget

vite-reset: ## Stop vite container and remove node_modules volume
	docker compose stop vite
	docker volume rm $(PROJECT)_vite_node_modules || true
	docker compose up --build vite