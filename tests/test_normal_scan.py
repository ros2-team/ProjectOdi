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
                   rest_sec=3., move_timeout_sec=30., track_timeout_sec=6.,
                   image_width=320, image_height=240, confidence=.6,
                   pan_sign=-1., tilt_sign=1., tilt_min=0., tilt_max=100.)
        n.head = dict(pan=84, tilt=65)
        n.head_pub = Mock()
        n.head_touched = False
        n.target = None
        n.target_seen = 0.
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

    def test_discovery_then_hum_then_bounded_tracking(self):
        n = self.node('LOOK_RIGHT')
        n.head = dict(pan=109, tilt=65)
        n.attention.latest = (normal.time.monotonic(), object_at(x=300))
        n.tick()
        self.assertEqual(n.stage, 'DISCOVERED')
        self.assertEqual(self.commands(n)[0]['pan'], 109)
        self.assertEqual(self.commands(n)[0]['beep'], 4)
        n.tick()
        self.assertEqual(len(self.commands(n)), 1)
        n.head_done.return_value = True
        n.tick()
        self.assertEqual(n.stage, 'TRACKING')
        self.assertEqual(self.commands(n)[-1]['beep'], 5)
        n.tick()
        self.assertEqual(self.commands(n)[-1]['beep'], 0)
        self.assertLess(self.commands(n)[-1]['pan'], 109)
        self.assertEqual(sum(c['beep'] == 5 for c in self.commands(n)), 1)
        n.deadline = normal.time.monotonic() - 1
        n.tick()
        self.assertEqual(n.stage, 'GOODBYE')
        self.assertEqual(self.commands(n)[-1]['pan'], 84)
        self.assertFalse(n.attention.observe(object_at(identifier='new'), normal.time.monotonic()))

    def test_tracking_updates_same_target_despite_discovery_cooldown(self):
        n = self.node()
        n.discover(object_at(), normal.time.monotonic())
        n.on_detection(object_at(x=200))
        self.assertEqual(n.target.center_x, 200)
        n.on_detection(object_at(x=100, identifier='normal-one:other'))
        self.assertEqual(n.target.center_x, 200)
        n.on_detection(object_at(x=50, identifier='old:1'))
        self.assertEqual(n.target.center_x, 200)

    def test_lost_target_returns_home_without_repeating_hum(self):
        n = self.node('TRACKING')
        n.target = object_at()
        n.target_seen = normal.time.monotonic() - 2
        n.deadline = normal.time.monotonic() + 6
        n.tick()
        self.assertEqual(n.stage, 'GOODBYE')
        self.assertEqual(self.commands(n)[0]['beep'], 6)

    def test_centered_target_does_not_generate_repeated_motor_commands(self):
        n = self.node('TRACKING')
        n.target = object_at()
        n.target_seen = normal.time.monotonic()
        n.deadline = normal.time.monotonic() + 6
        n.head_done.return_value = True
        n.tick()
        self.assertEqual(n.stage, 'TRACKING')
        n.head_pub.publish.assert_not_called()

    def test_tracking_waits_for_matching_ack(self):
        n = self.node('TRACKING')
        n.target = object_at(x=300)
        n.target_seen = n.head_sent = normal.time.monotonic()
        n.deadline = normal.time.monotonic() + 6
        n.tick()
        n.head_pub.publish.assert_not_called()

    def test_goodbye_centers_and_finishes_sound_before_direct_roaming(self):
        n = self.node()
        n.say_goodbye()
        n.tick()
        n.nav.send_goal_async.assert_not_called()
        self.assertEqual(self.commands(n)[-1]['beep'], 6)
        n.head_done.return_value = True
        n.tick()
        n.nav.send_goal_async.assert_not_called()  # Phrase has not finished yet.
        n.head_sent -= .7
        n.tick()
        self.assertEqual(n.stage, 'MOVING')
        n.nav.send_goal_async.assert_called_once()
        self.assertEqual(len(self.commands(n)), 1)  # No duplicate departure sound.

    def test_goodbye_cannot_start_roaming_without_centering_ack(self):
        n = self.node()
        n.say_goodbye()
        n.head_sent -= 1
        n.tick()
        n.nav.send_goal_async.assert_not_called()
        n.deadline = normal.time.monotonic() - 1
        n.tick()
        self.assertTrue(n.stop_requested)
        n.nav.send_goal_async.assert_not_called()

    def test_bridge_forwards_new_sounds_and_matches_completion(self):
        from test_normal_mode import HeadProtocolTests
        bridge = HeadProtocolTests().node()
        for sound in (4, 5, 6):
            bridge.command(NS(data=json.dumps(dict(id=str(sound), session_id='one',
                                                   pan=84, tilt=65, beep=sound))))
            bridge.write.assert_called_with(f'M {sound-3} 84 65 {sound}')
            bridge.line(f'D {sound-3}')
            self.assertEqual(bridge.done, str(sound))

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

