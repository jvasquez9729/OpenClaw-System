create table if not exists mem_audit.execution_ledger (
  event_id bigserial primary key,
  execution_id text not null,
  agent_id text not null,
  model_id text not null,
  state text not null,
  input_hash text not null,
  output_hash text not null,
  prev_event_hash text,
  event_hash text not null,
  token_in integer default 0,
  token_out integer default 0,
  cost_usd numeric(12,4) default 0,
  status text not null,
  created_at timestamptz not null default now()
);

create index if not exists idx_execution_ledger_execution_id
  on mem_audit.execution_ledger (execution_id, created_at);

create table if not exists mem_audit.pr_checks (
  id bigserial primary key,
  pr_id text not null,
  check_name text not null,
  check_status text not null,
  severity text,
  details jsonb default '{}'::jsonb,
  created_at timestamptz not null default now()
);