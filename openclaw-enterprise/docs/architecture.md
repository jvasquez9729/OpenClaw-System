# Arquitectura Empresarial Multi-Agente (MVP)

## 1. Bloques
- Control Plane: orquestacion, politicas, workflow, presupuesto.
- Financial Intelligence: parsing + analisis + narrativa ejecutiva.
- Software Factory: build/review/security con gates obligatorios.
- Memory Plane: `mem_finance`, `mem_tech`, `mem_audit`.
- Audit Plane: ledger hash-encadenado + PR checks + eventos de estado.

## 2. Flujo operativo
1. VALIDATION (integridad input)
2. DECOMPOSITION (micro-tareas)
3. EXECUTION (agentes especializados)
4. AUDIT (review + security)
5. CONSOLIDATION (unificar resultados)
6. EXEC_SUMMARY (reporte ejecutivo)
7. HITL_WAIT (espera `/approve`)

## 3. Mecanismos de seguridad
- Principio de minimo privilegio por rol.
- Separacion de memoria por esquema y credenciales.
- Denegacion explicita de acciones irreversibles sin HITL.
- Gate de seguridad bloqueante para severidad HIGH/CRITICAL.

## 4. Metricas minimas por release
- Tiempo promedio de ciclo de tarea (TCT).
- Costo por ejecucion.
- Porcentaje de PR rechazadas por seguridad.
- Precision de extraccion financiera validada.
