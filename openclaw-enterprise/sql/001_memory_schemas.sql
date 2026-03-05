-- Memoria separada por dominio
create schema if not exists mem_finance;
create schema if not exists mem_tech;
create schema if not exists mem_audit;

-- Roles dedicados (adaptar en Supabase según políticas de acceso)
do $$ begin
  create role role_finance_agent;
exception when duplicate_object then null;
end $$;

do $$ begin
  create role role_dev_agent;
exception when duplicate_object then null;
end $$;

do $$ begin
  create role role_auditor;
exception when duplicate_object then null;
end $$;

do $$ begin
  create role role_orchestrator;
exception when duplicate_object then null;
end $$;

-- USAGE en schemas (permite acceder al schema)
grant usage on schema mem_finance to role_finance_agent, role_orchestrator;
grant usage on schema mem_tech    to role_dev_agent, role_orchestrator;
grant usage on schema mem_audit   to role_auditor, role_orchestrator;

-- M2: Grants de operación sobre tablas existentes y futuras ──────
-- role_finance_agent: solo lectura/escritura en mem_finance
grant select, insert, update on all tables in schema mem_finance to role_finance_agent;
alter default privileges in schema mem_finance
  grant select, insert, update on tables to role_finance_agent;

-- role_dev_agent: solo lectura/escritura en mem_tech
grant select, insert, update on all tables in schema mem_tech to role_dev_agent;
alter default privileges in schema mem_tech
  grant select, insert, update on tables to role_dev_agent;

-- role_auditor: solo lectura en mem_audit (no puede alterar el ledger)
grant select on all tables in schema mem_audit to role_auditor;
alter default privileges in schema mem_audit
  grant select on tables to role_auditor;

-- role_orchestrator: lectura en todos los schemas, escritura en mem_audit
grant select, insert, update on all tables in schema mem_finance to role_orchestrator;
grant select, insert, update on all tables in schema mem_tech    to role_orchestrator;
grant select, insert, update on all tables in schema mem_audit   to role_orchestrator;
alter default privileges in schema mem_audit
  grant select, insert, update on tables to role_orchestrator;

-- Grants para secuencias (bigserial en execution_ledger y pr_checks)
grant usage, select on all sequences in schema mem_audit to role_orchestrator, role_auditor;
alter default privileges in schema mem_audit
  grant usage, select on sequences to role_orchestrator, role_auditor;
