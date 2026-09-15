"""Normal-mode scan choreography and navigation/head interlocks."""
import json
import unittest
from unittest.mock import Mock
from test_normal_mode import normal, object_at, Attention, NS


class ScanTests(unittest.TestCase):
    def node(self, stage='REST'):
        n = normal.NormalModeNode.__new__(normal.NormalModeNode)
        n.session = 'normal-one'
        n.stage = stage
        n.p = dict(pan_home=84., tilt_home=65., pan_min=40., pan_max=140.,
                   rest_sec=8., move_timeout_sec=30.)
        n.head = dict(pan=84, tilt=65)
        n.head_pub = Mock()
        n.head_touched = False
        n.attention = Attention()
        n.get_logger = Mock(return_value=Mock())
        n.poll_navigation = Mock()
        n.stationary = Mock(return_value=True)
        n.head_ready = Mock(return_value=True)
        n.head_done = Mock(return_value=False)
        n.nav_pending = Mock(return_value=False)
        n.cancel_navigation = Mock()
        n.nav = Mock()
        n.stop_requested = False
        n.fault_detail = ''
        n.events = Mock()
        n.status_pub = Mock()
        n.mission_seen = normal.time.monotonic()
        n.last_status = n.mission_seen
        n.deadline = n.mission_seen - 1
        return n

    def commands(self, n):
        return [json.loads(c.args[0].data) for c in n.head_pub.publish.call_args_list]

    def test_departure_ack_precedes_navigation(self):
        n = self.node()
        n.tick()
        self.assertEqual(n.stage, 'DEPARTING')
        self.assertEqual(self.commands(n)[0]['beep'], 1)
        n.nav.send_goal_async.assert_not_called()
        n.tick()
        n.nav.send_goal_async.assert_not_called()
        n.head_done.return_value = True
        n.tick()
        self.assertEqual(n.stage, 'MOVING')
        self.assertEqual(n.nav.send_goal_async.call_args.args[0].mode, 'SHORT_ROAM')

    def test_scan_waits_for_navigation_and_stationary_base(self):
        n = self.node('BRAKING')
        n.deadline = normal.time.monotonic() + 10
        n.nav_pending.return_value = True
        n.tick()
        n.head_pub.publish.assert_not_called()
        n.nav_pending.return_value = False
        n.stationary.return_value = False
        n.tick()
        n.head_pub.publish.assert_not_called()
        n.stationary.return_value = True
        n.tick()
        self.assertEqual(n.stage, 'SCAN_LEFT')
        self.assertEqual(self.commands(n)[0]['beep'], 2)

    def test_full_scan_without_discovery_centers_before_rest(self):
        n = self.node('BRAKING')
        n.tick()
        n.head_done.return_value = True
        for side in ('LEFT', 'RIGHT', 'CENTER'):
            self.assertEqual(n.stage, 'SCAN_' + side)
            n.tick()
            self.assertEqual(n.stage, 'LOOK_' + side)
            n.deadline = normal.time.monotonic() - 1
            n.tick()
        self.assertEqual(n.stage, 'REST')
        self.assertEqual([c['pan'] for c in self.commands(n)], [59., 109., 84.])
        self.assertEqual([c['beep'] for c in self.commands(n)], [2, 0, 0])

    def test_discovery_at_current_angle_once_and_no_tracking(self):
        n = self.node('LOOK_RIGHT')
        n.head = dict(pan=109, tilt=65)
        n.attention.latest = (normal.time.monotonic(), object_at(x=300))
        n.tick()
        self.assertEqual(n.stage, 'DISCOVERED')
        self.assertEqual(self.commands(n)[0]['pan'], 109)
        self.assertEqual(self.commands(n)[0]['beep'], 3)
        n.tick()
        self.assertEqual(len(self.commands(n)), 1)
        n.head_done.return_value = True
        n.tick()
        self.assertEqual(n.stage, 'DISCOVERY_PAUSE')
        n.deadline = normal.time.monotonic() - 1
        n.tick()
        self.assertEqual(n.stage, 'RETURN_HEAD')
        self.assertEqual(self.commands(n)[-1]['pan'], 84)
        self.assertFalse(n.attention.observe(object_at(identifier='new'), normal.time.monotonic()))

    def test_stale_detection_during_pan_is_discarded(self):
        n = self.node('SCAN_LEFT')
        n.attention.latest = (normal.time.monotonic(), object_at())
        n.head_done.return_value = True
        n.tick()
        self.assertIsNone(n.attention.candidate(normal.time.monotonic()))
        n.tick()
        self.assertEqual(n.stage, 'LOOK_LEFT')

    def test_stop_during_scan_never_starts_roaming(self):
        n = self.node('SCAN_LEFT')
        n.stop_requested = True
        n.stop_tick = Mock()
        n.tick()
        n.stop_tick.assert_called_once()
        n.nav.send_goal_async.assert_not_called()
        n.head_pub.publish.assert_not_called()

    def test_missing_departure_ack_faults_without_navigation(self):
        n = self.node('DEPARTING')
        n.tick()
        self.assertTrue(n.stop_requested)
        n.nav.send_goal_async.assert_not_called()


if __name__ == '__main__':
    unittest.main()
