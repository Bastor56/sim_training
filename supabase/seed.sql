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
