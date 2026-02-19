-- Memoria separada por dominio
create schema if not exists mem_finance;
create schema if not exists mem_tech;
create schema if not exists mem_audit;

-- Roles dedicados (adaptar en Supabase segun politicas de acceso)
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

grant usage on schema mem_finance to role_finance_agent, role_orchestrator;
grant usage on schema mem_tech to role_dev_agent, role_orchestrator;
grant usage on schema mem_audit to role_auditor, role_orchestrator;