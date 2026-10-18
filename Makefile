.PHONY: help up down build migrate test lint

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-20s\033[0m %s\n", $$1, $$2}'

up: ## Start all services
	docker-compose up -d

down: ## Stop all services
	docker-compose down

build: ## Build all Docker images
	docker-compose build

rebuild: ## Rebuild and restart
	docker-compose down && docker-compose up -d --build

init-db: ## Ensure database and tables exist
	python init_db.py

migrate: ## Run database migrations
	cd migrations && alembic upgrade head

migrate-down: ## Rollback last migration
	cd migrations && alembic downgrade -1

migrate-new: ## Create a new migration (usage: make migrate-new msg="description")
	cd migrations && alembic revision --autogenerate -m "$(msg)"

lint: ## Lint all code
	ruff check shared/ agent_server/ merchant_server/ payment_server/

format: ## Format all code
	ruff format shared/ agent_server/ merchant_server/ payment_server/

test: ## Run all tests
	pytest tests/ -v

logs: ## Tail all service logs
	docker-compose logs -f

logs-agent: ## Tail agent server logs
	docker-compose logs -f agent-server

logs-merchant: ## Tail merchant server logs
	docker-compose logs -f merchant-server

logs-payment: ## Tail payment server logs
	docker-compose logs -f payment-server

psql: ## Connect to PostgreSQL
	docker-compose exec postgres psql -U commerce -d agenticcommerce

redis-cli: ## Connect to Redis
	docker-compose exec redis redis-cli
