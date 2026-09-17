import unittest
import test_session_lifecycle as lifecycle
from odi_detection.turn_gate import TurnGate

class GuardBypassTests(unittest.TestCase):
    def test_bypass_publishes_candidates_without_odom_and_uses_new_id_for_new_label(self):
        f = lifecycle.DetectorTests(); f.setUp()
        n = f.node
        n.recent_detection_guards_enabled = False
        n.turn_gate = TurnGate()
        f.mission('EXPLORING')
        f.frame(1)
        first = n.batch_publisher.publish.call_args.args[0].objects[0].detection_id
        n.policy.handled(first, 1)
        n.model.names[0] = 'bottle'
        f.frame(2)
        self.assertEqual(n.batch_publisher.publish.call_count, 2)
        second = n.batch_publisher.publish.call_args.args[0].objects[0].detection_id
        self.assertNotEqual(first, second)
        n.policy.handled(second, 2)
        f.frame(3)
        self.assertEqual(n.batch_publisher.publish.call_count, 2)
