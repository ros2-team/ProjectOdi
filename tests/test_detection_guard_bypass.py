import unittest
import test_session_lifecycle as lifecycle
from odi_detection.turn_gate import TurnGate

class GuardBypassTests(unittest.TestCase):
    def test_bypass_publishes_candidates_without_odom_and_uses_new_id_for_new_label(self):
        f = lifecycle.DetectorTests(); f.setUp()
        n = f.node
        n.label_identity_enabled = False
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

    def test_label_only_blocks_repeat_but_allows_new_object_without_turn_gate(self):
        f = lifecycle.DetectorTests(); f.setUp()
        n = f.node
        n.turn_identity_enabled = False
        n.label_identity_enabled = True
        n.recent_detection_guards_enabled = False
        n.turn_gate = TurnGate()  # No odometry: turn gate itself remains closed.
        f.mission('EXPLORING')
        f.frame(1)
        first = n.batch_publisher.publish.call_args.args[0].objects[0].detection_id
        n.policy.handled(first, 1)
        n.model.names[0] = 'bottle'
        for t in (1.2, 1.4, 1.6):
            f.frame(t)
        self.assertEqual(n.batch_publisher.publish.call_count, 1)
        self.assertTrue(n.policy.tracks[first]['handled'])
        xy = f.result.boxes[0].xyxy[0]
        xy.cpu.return_value.numpy.return_value.astype.return_value = [220,20,310,180]
        n.turn_gate.update(.6, 2)
        f.frame(2)
        self.assertEqual(n.batch_publisher.publish.call_count, 2)
        second = n.batch_publisher.publish.call_args.args[0].objects[0].detection_id
        self.assertNotEqual(first, second)
