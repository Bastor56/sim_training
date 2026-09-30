-- Harbor Credit Union core banking (week2/day3): accounts and transactions,
-- reachable only through the harbor-mcp server (labs/week2_day3/spec.md).
--
-- Kept in its own schema, not `public`: `public` is the schema the Supabase
-- REST API exposes, and Harbor's rule is that no outside team touches core
-- banking directly. Nothing here is granted to anon / authenticated /
-- service_role, so the REST API can't reach it either.

create schema if not exists harbor_core;

create table harbor_core.accounts (
  account_id text primary key,
  member_id  text not null,
  type       text not null check (type in ('checking', 'savings', 'credit')),
  balance    numeric(12, 2) not null,  -- numeric, not float: money must add up to the cent
  status     text not null check (status in ('active', 'frozen', 'closed')),
  opened_on  date not null
);

create index accounts_member_id_idx on harbor_core.accounts (member_id);

create table harbor_core.transactions (
  transaction_id text primary key,
  account_id     text not null references harbor_core.accounts (account_id),
  posted_on      date not null,
  amount         numeric(12, 2) not null,  -- negative = money out
  description    text not null,
  category       text not null
);

create index transactions_account_posted_idx on harbor_core.transactions (account_id, posted_on desc);

-- The MCP server's login. Created WITHOUT a password: a password in a
-- migration would be committed to git. scripts/set_db_password.py in the lab
-- sets it from the server's own .env (spec.md "Backend credentials").
-- Roles are cluster-wide and can outlive a `db reset`, hence the guard.
do $$
begin
  if not exists (select from pg_roles where rolname = 'harbor_mcp') then
    create role harbor_mcp login;
  end if;
end
$$;

-- Least privilege: read two tables, nothing else. No INSERT/UPDATE/DELETE,
-- no other schemas (week 1's public.policies stays out of reach), and a
-- statement timeout so one bad query can't hold a connection forever.
grant usage on schema harbor_core to harbor_mcp;
grant select on harbor_core.accounts, harbor_core.transactions to harbor_mcp;
alter role harbor_mcp set statement_timeout = '5s';
