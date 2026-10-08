import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock
from test_session_lifecycle import state, load_classes, SRC

behavior = load_classes(SRC/'odi_behavior_executor/odi_behavior_executor/behavior_executor_node.py', String=NS, json=json)
observation = load_classes(SRC/'odi_observation/odi_observation/observation_node.py')

class MotivationTests(unittest.TestCase):
    def setUp(self):
        state.reset()
        state.apply_mission_report('EXPLORING', 'current')

    def test_real_budget_flows_from_publisher_to_web(self):
        n = behavior.BehaviorExecutorNode.__new__(behavior.BehaviorExecutorNode)
        n.blackboard = NS(session_id='current', motivation=30)
        n.initial_motivation = 40
        n.motivation_publisher = Mock()
        n.publish_motivation()
        data = json.loads(n.motivation_publisher.publish.call_args.args[0].data)
        self.assertTrue(state.apply_motivation_report(data))
        self.assertEqual(state.snapshot()['motivation'], .75)
        data['current'] = 0
        state.apply_motivation_report(data)
        self.assertEqual(state.snapshot()['motivation'], 0)

    def test_old_mission_and_bad_numbers_do_not_change_gauge(self):
        for report in [dict(session_id='old',initial=40,current=10),
                       dict(session_id='current',initial=40,current=float('nan')),
                       dict(session_id='current',initial=-1,current=10), {}]:
            self.assertFalse(state.apply_motivation_report(report))
        self.assertEqual(state.snapshot()['motivation'], 1)
        state.apply_motivation_report(dict(session_id='current', initial=0,current=0))
        self.assertEqual(state.snapshot()['motivation'],0)
        state.apply_mission_report('PREPARING', 'next')
        self.assertEqual(state.snapshot()['motivation'],1)

    def test_summary_fallback_avoids_english_attribute_dump(self):
        summary = observation.ObservationNode.build_diary_summary(NS(object_name='bottle'))
        self.assertIn('물병', summary)
        self.assertNotIn('unknown', summary)
        summary = observation.ObservationNode.build_diary_summary(NS(object_name='unknown'))
        self.assertNotIn('unknown',summary)
