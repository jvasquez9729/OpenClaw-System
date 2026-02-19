# OpenClaw Enterprise OS (Plantilla Inicial)

Esta carpeta contiene una base de arquitectura para un Sistema Multi-Agente Auditado con separacion estricta de memoria (financiera/tecnica/auditoria), HITL obligatorio y pipeline de validacion.

## Objetivo
Implementar 3 bloques:
1. Financial Intelligence System.
2. Software Factory con review cruzada y seguridad.
3. Control Plane + Auditoria con trazabilidad completa.

## Estructura
- `control-plane/openclaw.json`: configuracion base del orquestador y politicas globales.
- `policies/agent_capabilities.yaml`: permisos por agente (RBAC + tool allowlist).
- `workflows/state_machine.yaml`: ciclo de 7 estados con transicion formal.
- `prompts/*.md`: prompts iniciales por agente.
- `sql/*.sql`: esquemas de memoria separada y ledger auditable.
- `infra/docker-compose.yml`: PostgreSQL + pgvector para memoria persistente.
- `docs/architecture.md`: arquitectura de referencia y flujo operativo.
- `docs/skills-roadmap.md`: skills recomendadas para usar/crear en tu sistema.
- `docs/execution-and-ssh.md`: como ejecutar el sistema y como operarlo por SSH.
- `scripts/bootstrap.sh`: guia automatizable para primeros pasos.

## Principios no negociables
- Ningun agente hace merge/deploy sin `HITL_APPROVAL`.
- El agente que desarrolla no puede autoaprobar su PR.
- Toda accion se registra con hash de entrada/salida y costo.
- Memoria financiera y tecnica aisladas por esquema + rol DB.

## Quickstart de comandos
Para ejecutar todo en orden, sigue `docs/quickstart-commands.md`.
