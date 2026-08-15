.PHONY: up down test-common test-mcp test-scheduler test-api install
up:
	docker compose up --build
down:
	docker compose down -v
test-common:
	cd packages/common && pytest
test-mcp:
	cd services/mcp-server && pytest
test-scheduler:
	cd services/scheduler && pytest
test-api:
	cd services/api-backend && pytest
install:
	# Each service depends on packages/common via a relative `file:../../packages/common`
	# URL in its pyproject.toml, which pip resolves relative to the CURRENT DIRECTORY at
	# install time (not relative to the pyproject.toml declaring it) -- so each `pip install
	# -e .` below must run with that package's own directory as cwd. Installing a service
	# also rebuilds `common` as a plain (non-editable) snapshot to satisfy that direct URL
	# reference, clobbering any earlier editable install of it -- so packages/common is
	# (re)installed editable last, to guarantee it ends up live-linked rather than frozen.
	# pip is upgraded first because pip<25's vendored `packaging` fails to parse that
	# relative file: URL at all (raises "Invalid URL given"), independent of the above.
	pip install --upgrade pip
	pip install -e packages/common
	cd services/mcp-server && pip install -e .
	cd services/scheduler && pip install -e .
	cd services/api-backend && pip install -e .
	pip install -e packages/common
