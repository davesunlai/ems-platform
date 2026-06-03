.PHONY: install run-mock run-api up down discover

install:
	pip install -e ".[all]"

# Rychlý běh bez DB: mock měniče -> stdout
run-mock:
	EMS_SINK=stdout EMS_DEVICES=devices.yaml EMS_POLL_INTERVAL=5 python -m ems.collector.main

# Lokální API (vyžaduje běžící TimescaleDB)
run-api:
	uvicorn ems.api.main:app --host 0.0.0.0 --port 8000 --reload

# Celý stack v Dockeru (DB + kolektor + API + web na :8080)
up:
	docker compose -f infra/docker-compose.yml up -d --build

down:
	docker compose -f infra/docker-compose.yml down

# Vypsat všechny sensory reálného měniče (ladění mapování)
discover:
	python scripts/discover.py $(IP)
