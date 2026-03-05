.PHONY: help preflight runtime-test runtime-api runtime-api-smoke runtime-api-approve install-ci

help:
	@echo "Targets disponibles:"
	@echo "  make preflight         - Validaciones previas de entorno"
	@echo "  make runtime-test      - Prueba basica del runtime (import check)"
	@echo "  make runtime-api       - Levanta API HTTP del runtime (FastAPI)"
	@echo "  make runtime-api-smoke - Prueba execute/approve"
	@echo "  make runtime-api-approve - Aprueba ejecucion por ID (EXEC_ID=...)"

preflight:
	bash scripts/preflight.sh

runtime-test:
	@if [ ! -f scripts/runtime_server.py ]; then \
		echo "scripts/runtime_server.py no existe"; \
		exit 1; \
	fi
	python3 -c "import scripts.runtime_server as s; print('runtime_server import OK', s.app.title)"

runtime-api:
	uvicorn scripts.runtime_server:app --host 0.0.0.0 --port 8000

runtime-api-smoke:
	curl -s -X POST http://127.0.0.1:8000/runtime/execute -H "Content-Type: application/json" -d "{\"task\":\"smoke test\",\"domain\":\"mem_finance\",\"agent_id\":\"chief_of_staff\",\"budget_key\":\"finance_analysis\"}"

runtime-api-approve:
	@test -n "$(EXEC_ID)" || (echo "Uso: make runtime-api-approve EXEC_ID=exec-xxxx"; exit 1)
	curl -s -X POST http://127.0.0.1:8000/runtime/approve -H "Content-Type: application/json" -d "{\"execution_id\":\"$(EXEC_ID)\",\"approved\":true}"
