"""Conservative turn association; no ROS/model or appearance embedding needed."""
import unittest
from test_label_flicker import CandidatePolicy
from odi_detection.turn_gate import TurnGate
import test_session_lifecycle as lifecycle

LEFT = (10, 40, 90, 200)
RIGHT = (220, 40, 300, 200)

class TurnIdentityTests(unittest.TestCase):
    def make(self, items=None):
        p = CandidatePolicy(min_hits=1)
        old = p.update(items or [(LEFT, 'bottle')], 320, 240, 0)
        p.handled(old[0][2], 0)
        return p, old[0][2]

    def test_shift_and_brief_absence_preserve_handled(self):
        p, key = self.make()
        p.update([], 320, 240, .5, turn_link=True)
        row = p.update([(RIGHT, 'bottle')], 320, 240, 1.5,
                       (1, 0), turn_link=True)[0]
        self.assertEqual(row[2], key)
        self.assertFalse(row[3])

    def test_disabled_stale_and_different_class_remain_new(self):
        for t, name, enabled in ((.5, 'bottle', False),
                                 (2.01, 'bottle', True),
                                 (.5, 'book', True)):
            p, key = self.make()
            row = p.update([(RIGHT, name)], 320, 240, t,
                           (1, 0), turn_link=enabled)[0]
            self.assertNotEqual(row[2], key)
            self.assertTrue(row[3])

    def test_ambiguous_previous_or_current_keeps_new_id(self):
        p, key = self.make([(LEFT, 'bottle'), ((100, 40, 170, 200), 'bottle')])
        row = p.update([(RIGHT, 'bottle')], 320, 240, .5,
                       (1, 0), turn_link=True)[0]
        self.assertNotEqual(row[2], key)
        p, key = self.make()
        rows = p.update([(RIGHT, 'bottle'), ((120, 40, 200, 200), 'bottle')],
                        320, 240, .5, (1, 0), turn_link=True)
        self.assertTrue(all(row[2] != key for row in rows))

    def test_overlap_has_priority_over_turn_fallback(self):
        p, key = self.make()
        # Larger new bottle is processed first; old box now has a flickering label.
        rows = p.update([((170, 20, 310, 230), 'bottle'), (LEFT, 'cup')],
                        320, 240, .5, (1, 0), turn_link=True)
        self.assertNotEqual(rows[0][2], key)
        self.assertEqual(rows[1][2], key)
        self.assertFalse(rows[1][3])

    def test_gate_requires_actual_recent_turn_and_fresh_odom(self):
        g = TurnGate()
        self.assertFalse(g.can_link(0))
        g.update(0, 0)
        self.assertFalse(g.can_link(0))
        g.update(-.6, .1)
        self.assertTrue(g.can_link(.1))
        g.update(0, .2)
        for t in (.7, 1.2, 1.7, 2.09):
            g.update(0, t)
        self.assertTrue(g.can_link(2.09))
        g.update(0, 2.11)
        self.assertFalse(g.can_link(2.11))
        g.update(.6, 2.2)
        self.assertFalse(g.can_link(3.21))
        g.update(0, 3.3)
        self.assertFalse(g.can_link(3.3))

    def test_callback_preserves_id_through_turn_without_new_observation(self):
        f = lifecycle.DetectorTests(); f.setUp()
        n = f.node; n.turn_gate = TurnGate()
        f.mission('EXPLORING')
        n.turn_gate.update(0, 0); n.turn_gate.update(0, .6); f.frame(.6)
        key = next(iter(n.policy.tracks))
        n.policy.handled(key, .6)
        n.batch_publisher.publish.reset_mock()
        xy = f.result.boxes[0].xyxy[0]
        xy.cpu.return_value.numpy.return_value.astype.return_value = list(RIGHT)
        n.turn_gate.update(.6, .8); f.frame(.8)
        self.assertEqual(list(n.policy.tracks), [key])
        n.turn_gate.update(0, .9)
        n.turn_gate.update(0, 1.5); f.frame(1.5)
        n.batch_publisher.publish.assert_not_called()
        self.assertTrue(n.policy.tracks[key]['handled'])
        f.mission('EXPLORING', 'two'); f.frame(1.6)
        n.batch_publisher.publish.assert_called_once()
