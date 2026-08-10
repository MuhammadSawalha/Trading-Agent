.PHONY: up down test-mcp test-scheduler test-api
up:
	docker compose up --build
down:
	docker compose down -v
test-mcp:
	cd services/mcp-server && pytest
test-scheduler:
	cd services/scheduler && pytest
test-api:
	cd services/api-backend && pytest
