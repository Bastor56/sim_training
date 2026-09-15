-- Backs the FNOL intake lab's check_policy_coverage tool (week1/day1).
-- The tool is only ever called server-side with the service role key, which
-- bypasses RLS by design — RLS is still enabled here with no anon/authenticated
-- policies, so the table has no accidental public read path if it's ever
-- queried with a lesser key.

create type policy_status as enum ('active', 'lapsed', 'cancelled', 'pending');

create table public.policies (
  policy_number text primary key,
  status policy_status not null,
  -- Per-peril limits, e.g. {"fire": 250000, "water": 50000, "theft": 10000}
  coverage_limits jsonb not null,
  created_at timestamptz not null default now()
);

alter table public.policies enable row level security;
