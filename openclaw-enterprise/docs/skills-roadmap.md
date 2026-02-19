# Skills recomendadas para tu sistema multi-agente

Este roadmap separa skills para usar ya y skills que conviene crear para tu arquitectura (finanzas + software factory + auditoria).

## 1) Skills a usar (inmediatas)

### 1.1 skill-installer
Para que usarla:
- Instalar skills curadas cuando necesites capacidades puntuales sin construir todo desde cero.
- Estandarizar instalacion desde repos o paths de GitHub.

Cuando activarla en tu flujo:
- Antes de cada release para anadir capacidades faltantes del stack.
- En entornos nuevos para bootstrap rapido del workspace.

### 1.2 skill-creator
Para que usarla:
- Disenar skills propias con estructura reusable (`SKILL.md`, `scripts/`, `references/`, `assets/`).
- Evitar prompts largos dispersos y convertirlos en procedimientos operativos versionables.

Cuando activarla en tu flujo:
- Cuando una tarea se repite 2+ veces (ej: parseo financiero, checklist de seguridad, creacion de PR auditado).

## 2) Skills que te recomiendo crear primero (prioridad)

## A. `financial-ingestion-audit`
Objetivo: ingestion y validacion financiera robusta con trazabilidad.

Debe incluir:
- `scripts/parse_financials.py` (CSV/PDF->dataset normalizado)
- `scripts/validate_financial_schema.py` (checks de integridad)
- `references/finance-schema.md` (diccionario de campos y KPIs)

Salida estandar:
- dataset limpio
- errores detectados
- hash de input/output para `mem_audit.execution_ledger`

## B. `secure-pr-gate`
Objetivo: gate tecnico obligatorio antes de merge.

Debe incluir:
- `scripts/run_pr_gate.sh` (lint, tests, SAST, secret scan)
- `references/severity-policy.md` (HIGH/CRITICAL bloquea)
- plantilla de reporte de remediacion

Salida estandar:
- PASS/FAIL
- severidad
- evidencias
- acciones de remediacion

## C. `hitl-approval-controller`
Objetivo: impedir acciones irreversibles sin aprobacion humana.

Debe incluir:
- `scripts/check_hitl.sh` (valida existencia de `/approve`)
- `references/hitl-policy.md`

Salida estandar:
- approved/rejected
- aprobador
- timestamp
- motivo

## D. `execution-ledger-recorder`
Objetivo: registrar cadena de auditoria hash-encadenada.

Debe incluir:
- `scripts/write_ledger_event.py`
- `scripts/verify_ledger_chain.py`
- `references/audit-event-contract.md`

Salida estandar:
- `event_hash`
- `prev_event_hash`
- `execution_id`
- `cost_usd`

## E. `saas-backend-scaffold`
Objetivo: acelerar creacion de backend SaaS con estandares de seguridad.

Debe incluir:
- `assets/` de plantilla de backend
- `scripts/bootstrap_service.sh`
- `references/backend-architecture-rules.md`

Salida estandar:
- servicio inicial
- pruebas minimas
- checklist de seguridad cumplido

## 3) Orden recomendado de implementacion
1. `financial-ingestion-audit`
2. `execution-ledger-recorder`
3. `hitl-approval-controller`
4. `secure-pr-gate`
5. `saas-backend-scaffold`

## 4) Criterio para decidir si una skill vale la pena
Crea una skill si cumple al menos 2 de 3:
- tarea repetida semanalmente,
- alto riesgo (finanzas/seguridad/produccion),
- facil de estandarizar con script/plantilla.

## 5) Gobernanza minima de skills
- versiona cada skill (`v0.1`, `v0.2`)
- define owner por skill
- registra cambios en `CHANGELOG.md`
- prueba script principal antes de usar en produccion