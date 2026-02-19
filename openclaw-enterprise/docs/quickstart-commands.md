# Quickstart: comandos exactos (paso a paso)

> Ejecuta estos comandos desde la raiz del repositorio (`/workspace/Biblioteca`).

## 0) Entrar al proyecto y validar prerequisitos
```bash
cd /workspace/Biblioteca
which docker
which psql
```

## 1) Levantar base local (PostgreSQL + pgvector) y crear esquemas/tablas
```bash
bash openclaw-enterprise/scripts/bootstrap.sh
```

Si prefieres manual, usa:

```bash
docker compose -f openclaw-enterprise/infra/docker-compose.yml up -d
export PGPASSWORD="openclaw_dev"
psql -h 127.0.0.1 -U openclaw -d openclaw -f openclaw-enterprise/sql/001_memory_schemas.sql
psql -h 127.0.0.1 -U openclaw -d openclaw -f openclaw-enterprise/sql/002_audit_ledger.sql
```

## 2) Configurar conexion de memoria para OpenClaw
```bash
export OPENCLAW_DB_URL="postgresql://openclaw:openclaw_dev@127.0.0.1:5432/openclaw"
```

Si quieres dejarlo persistente en tu shell:

```bash
echo 'export OPENCLAW_DB_URL="postgresql://openclaw:openclaw_dev@127.0.0.1:5432/openclaw"' >> ~/.bashrc
source ~/.bashrc
```

## 3) Verificar que control plane y politicas esten en su lugar
```bash
python -m json.tool openclaw-enterprise/control-plane/openclaw.json >/dev/null && echo "openclaw.json OK"
rg -n "human_in_the_loop_required|approval_command|policy_file|workflow_file" openclaw-enterprise/control-plane/openclaw.json
rg -n "requires_human_approval_for|denied_tools|allowed_tools" openclaw-enterprise/policies/agent_capabilities.yaml
```

## 4) Validar workflow obligatorio de 7 estados
```bash
rg -n "workflow_name|initial_state|HITL_WAIT|irreversible_actions_require_hitl" openclaw-enterprise/workflows/state_machine.yaml
```

## 5) Prueba rapida de escritura de auditoria (ledger)
```bash
export PGPASSWORD="openclaw_dev"
psql -h 127.0.0.1 -U openclaw -d openclaw -c "\
insert into mem_audit.execution_ledger \
(execution_id,agent_id,model_id,state,input_hash,output_hash,prev_event_hash,event_hash,token_in,token_out,cost_usd,status) \
values ('exec-demo-001','chief_of_staff','claude-opus-4.6','VALIDATION','in_hash','out_hash',null,'event_hash_1',120,300,0.12,'approved');"

psql -h 127.0.0.1 -U openclaw -d openclaw -c "select execution_id, agent_id, state, status, created_at from mem_audit.execution_ledger order by event_id desc limit 5;"
```

## 6) Flujo recomendado Release 1 (finanzas + auditoria)
### 6.1 Cargar datos financieros (staging)
```bash
mkdir -p data/finance
cp /ruta/a/tus_estados/*.csv data/finance/
```

### 6.2 Ejecutar parsing/analisis con tu runtime OpenClaw
```bash
# Comando referencial: reemplaza por tu ejecutor real
# openclaw run --config openclaw-enterprise/control-plane/openclaw.json --task "Procesar estados financieros Q1"
```

### 6.3 Forzar pausa HITL antes de accion irreversible
```bash
# Comando referencial en chat/control channel
/approve
```

## 7) Comprobaciones de salud (post-bootstrap)
```bash
docker ps --filter "name=openclaw-postgres"
psql -h 127.0.0.1 -U openclaw -d openclaw -c "select schema_name from information_schema.schemata where schema_name like 'mem_%' order by schema_name;"
psql -h 127.0.0.1 -U openclaw -d openclaw -c "\dt mem_audit.*"
```

## 8) Apagar entorno local
```bash
docker compose -f openclaw-enterprise/infra/docker-compose.yml down
```