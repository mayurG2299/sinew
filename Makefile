.PHONY: db api web test
db:      ## start FalkorDB (+ Browser on :3000)
	docker compose up -d falkordb
api:     ## run the API on :8000
	uv run uvicorn sinew.main:app --reload --port 8000
web:     ## run the web app on :5173
	cd web && npm run dev
test:
	uv run pytest -q
