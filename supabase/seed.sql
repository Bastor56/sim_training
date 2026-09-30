-- Sample policies for the week1/day1 FNOL intake lab.
-- Deliberately spans the branches the demo needs to exercise: a fully active
-- policy, a policy missing coverage for a specific peril, and lapsed/cancelled/
-- pending policies where the tool result should contradict a naive coverage_flag.

insert into public.policies (policy_number, status, coverage_limits) values
  ('POL-100234', 'active',    '{"fire": 250000, "water": 50000, "theft": 10000, "wind": 100000}'),
  ('POL-100555', 'active',    '{"fire": 300000, "theft": 15000}'),
  ('POL-100777', 'lapsed',    '{}'),
  ('POL-100999', 'cancelled', '{}'),
  ('POL-100321', 'pending',   '{"fire": 200000}');

-- Harbor Credit Union core banking for the week2/day3 MCP lab
-- (labs/week2_day3/spec.md). Balances and the older transactions are week 1's
-- mock CRM fixtures (labs/week1_day4/mock_crm/fixtures.py), re-keyed from
-- CUST-100x to Harbor member IDs M-100x. The 2026-09-21..27 rows are new, so
-- "what did I spend last week?" has an answer relative to 2026-09-28.
--   M-1001  two accounts (checking + savings): the two-hop / "which account" demos
--   M-1002  ACC-2003 exists but has no transactions: "found, but empty"
--   M-1003..M-1006  normal here; their CRM *card* lookups carry week 1's faults

insert into harbor_core.accounts (account_id, member_id, type, balance, status, opened_on) values
  ('ACC-2001', 'M-1001', 'checking',  4210.55, 'active', '2019-03-11'),
  ('ACC-2002', 'M-1001', 'savings',  15320.10, 'active', '2019-03-11'),
  ('ACC-2003', 'M-1002', 'checking',   512.00, 'active', '2021-07-02'),
  ('ACC-2004', 'M-1003', 'checking',   980.40, 'active', '2020-01-20'),
  ('ACC-2005', 'M-1004', 'checking',  2300.00, 'active', '2022-11-08'),
  ('ACC-2006', 'M-1005', 'savings',   7800.25, 'active', '2018-05-30'),
  ('ACC-2007', 'M-1006', 'checking',  1150.75, 'active', '2023-02-14');

insert into harbor_core.transactions (transaction_id, account_id, posted_on, amount, description, category) values
  -- M-1001 checking: last week
  ('TXN-3010', 'ACC-2001', '2026-09-26',   -63.48, 'Green Leaf Grocery',     'groceries'),
  ('TXN-3009', 'ACC-2001', '2026-09-24',   -12.50, 'Harbor Coffee Co.',      'dining'),
  ('TXN-3008', 'ACC-2001', '2026-09-23',   -38.17, 'Green Leaf Grocery',     'groceries'),
  ('TXN-3007', 'ACC-2001', '2026-09-22',  -120.00, 'Bayside Fuel',           'transport'),
  ('TXN-3006', 'ACC-2001', '2026-09-21',  -500.00, 'Transfer to Savings',    'transfer'),
  -- M-1001 checking: week 1's rows
  ('TXN-3001', 'ACC-2001', '2026-09-10',   -42.10, 'Green Leaf Grocery',     'groceries'),
  ('TXN-3002', 'ACC-2001', '2026-09-08',   -15.00, 'Metro Transit',          'transport'),
  ('TXN-3003', 'ACC-2001', '2026-09-01',  2400.00, 'Payroll Deposit',        'income'),
  ('TXN-3004', 'ACC-2001', '2026-08-27',   -89.99, 'Citywide Electric',      'utilities'),
  -- M-1001 savings
  ('TXN-3104', 'ACC-2002', '2026-09-21',   500.00, 'Transfer from Checking', 'transfer'),
  ('TXN-3101', 'ACC-2002', '2026-09-05',   500.00, 'Transfer from Checking', 'transfer'),
  ('TXN-3102', 'ACC-2002', '2026-08-05',   500.00, 'Transfer from Checking', 'transfer'),
  ('TXN-3103', 'ACC-2002', '2026-07-31',    18.22, 'Interest Payment',       'interest'),
  -- M-1003..M-1006 (ACC-2003 deliberately has none)
  ('TXN-3401', 'ACC-2004', '2026-09-25',   -54.20, 'Northside Pharmacy',     'health'),
  ('TXN-3501', 'ACC-2005', '2026-09-24', -1200.00, 'Harborview Apartments',  'housing'),
  ('TXN-3601', 'ACC-2006', '2026-08-31',     9.75, 'Interest Payment',       'interest'),
  ('TXN-3701', 'ACC-2007', '2026-09-27',   -27.99, 'StreamBox Subscription', 'entertainment');
