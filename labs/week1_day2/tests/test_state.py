import context  # noqa: F401
import unittest

from state import AgentState, Observation


class ObservationTests(unittest.TestCase):
    def test_requires_exactly_one_of_result_or_error(self):
        with self.assertRaises(ValueError):
            Observation(tool="t", args={}, timestamp=0.0)  # neither set

        with self.assertRaises(ValueError):
            Observation(tool="t", args={}, timestamp=0.0, result={"a": 1}, error="boom")

    def test_result_only_is_valid(self):
        obs = Observation(tool="t", args={}, timestamp=0.0, result={"a": 1})
        self.assertEqual(obs.result, {"a": 1})
        self.assertIsNone(obs.error)

    def test_error_only_is_valid(self):
        obs = Observation(tool="t", args={}, timestamp=0.0, error="boom")
        self.assertEqual(obs.error, "boom")
        self.assertIsNone(obs.result)

    def test_falsy_but_non_none_result_is_valid(self):
        # [] and 0 are legitimate tool results, not "unset".
        obs = Observation(tool="t", args={}, timestamp=0.0, result=[])
        self.assertEqual(obs.result, [])


class AgentStateTests(unittest.TestCase):
    def test_add_observation_appends(self):
        state = AgentState(goal="g", claim_id="CLM-1")
        obs = Observation(tool="t", args={}, timestamp=0.0, result=1)
        state.add_observation(obs)
        self.assertEqual(state.observations, [obs])

    def test_elapsed_seconds_is_nonnegative_and_increases(self):
        state = AgentState(goal="g", claim_id="CLM-1")
        first = state.elapsed_seconds()
        second = state.elapsed_seconds()
        self.assertGreaterEqual(first, 0)
        self.assertGreaterEqual(second, first)

    def test_to_dict_from_dict_roundtrip(self):
        state = AgentState(goal="g", claim_id="CLM-1")
        state.add_observation(Observation(tool="t", args={"x": 1}, timestamp=1.0, result={"y": 2}))
        state.iteration_count = 2
        state.status = "terminated_success"
        state.final_decision = {"decision": "approve", "reasoning": "clean"}

        dump = state.to_dict()
        restored = AgentState.from_dict(dump)

        self.assertEqual(restored.goal, state.goal)
        self.assertEqual(restored.claim_id, state.claim_id)
        self.assertEqual(restored.iteration_count, 2)
        self.assertEqual(restored.status, "terminated_success")
        self.assertEqual(restored.final_decision, {"decision": "approve", "reasoning": "clean"})
        self.assertEqual(len(restored.observations), 1)
        self.assertEqual(restored.observations[0].tool, "t")
        self.assertEqual(restored.observations[0].result, {"y": 2})

    def test_defaults_are_not_shared_across_instances(self):
        # dataclass field(default_factory=list) pitfall: verify each
        # AgentState gets its own observations list, not one shared mutable
        # default.
        a = AgentState(goal="g1", claim_id="CLM-1")
        b = AgentState(goal="g2", claim_id="CLM-2")
        a.add_observation(Observation(tool="t", args={}, timestamp=0.0, result=1))
        self.assertEqual(len(a.observations), 1)
        self.assertEqual(len(b.observations), 0)


if __name__ == "__main__":
    unittest.main()
