"""Offline companion-mode regressions. No robot, USB device, ROS or YOLO model."""
import json
import math
import sys
import time
import uuid
import threading
from concurrent.futures import Future
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock
from test_session_lifecycle import SRC, ROOT, load_classes, state, commands, HAS_WEB
import test_fresh_mapping as fresh
manager = fresh.manager

sys.path.insert(0, str(SRC/'odi_normal'))
from odi_normal.attention import Attention, tracking_angles
normal = load_classes(SRC/'odi_normal/odi_normal/normal_node.py',
    json=json, math=math, uuid=uuid, String=NS, Attention=Attention,
    tracking_angles=tracking_angles, Explore=NS(Goal=NS))
head = load_classes(SRC/'odi_normal/odi_normal/head_bridge.py',
    json=json, math=math, serial=NS(SerialException=OSError), String=NS)
manager.json = json
explore = load_classes(SRC/'odi_exploration/odi_exploration/exploration_node.py', json=json)
navigation = load_classes(SRC/'odi_exploration/odi_exploration/navigation_manager.py',
    rclpy=NS(ok=lambda:True), NavigateToPose=NS(Goal=NS))


def object_at(x=160, size=60, identifier='normal-one:1', name='bottle'):
    return NS(class_name=name, confidence=.9, width=size, height=size,
              center_x=x, center_y=120, detection_id=identifier)


class AttentionTests(unittest.TestCase):
    def test_stability_area_class_and_freshness(self):
        p = Attention()
        for now in (0., .2):
            self.assertFalse(p.observe(object_at(), now))
        self.assertTrue(p.observe(object_at(), .4))
        self.assertIsNotNone(p.candidate(.5))
        self.assertIsNone(p.candidate(2.))
        self.assertFalse(p.observe(object_at(size=10), 2.))
        self.assertFalse(p.observe(object_at(name='tv'), 2.))

    def test_cooldown_survives_detector_identity_change(self):
        p = Attention()
        p.handled_target(object_at(), 0)
        for now in (1., 1.2, 1.4):
            self.assertFalse(p.observe(object_at(identifier='different'), now))
        for now in (61., 61.2, 61.4):
            p.observe(object_at(identifier='different'), now)
        self.assertIsNotNone(p.candidate(61.5))

    def test_tracking_deadband_limits_and_sign(self):
        self.assertEqual(tracking_angles(object_at(), 320, 240, 90, 90,
            -1, 1, (60,120), (70,110)), (90,90,True))
        pan, tilt, centered = tracking_angles(object_at(x=319), 320, 240, 61, 90,
            -1, 1, (60,120), (70,110))
        self.assertEqual(pan, 60)
        self.assertFalse(centered)


class NormalTransitionTests(unittest.TestCase):
    def test_mode_mutual_exclusion_and_stop_ack(self):
        n = fresh.FreshMappingTests().node()
        n.command_callback(NS(data='NORMAL'))
        self.assertEqual(n.current_state.value, 'NORMAL')
        session = n.session_id
        n.handle_start_command()
        self.assertEqual(n.session_id, session)
        n.command_callback(NS(data='NORMAL_STOP'))
        self.assertEqual(n.current_state.value, 'NORMAL_STOPPING')
        n.handle_reset_completed()
        self.assertEqual(n.current_state.value, 'NORMAL_STOPPING')
        n.normal_event(NS(data=json.dumps(dict(session_id='old',event='STOPPED'))))
        self.assertEqual(n.current_state.value, 'NORMAL_STOPPING')
        n.normal_event(NS(data=json.dumps(dict(session_id=session,event='STOPPED'))))
        self.assertEqual(n.current_state.value, 'IDLE')

    def test_late_accepted_navigation_stays_owned_until_result(self):
        n = normal.NormalModeNode.__new__(normal.NormalModeNode)
        n.send_future = Future()
        n.goal = n.result_future = n.cancel_future = None
        n.cancel_at = 0.
        n.stop_requested = True
        n.stage = 'BRAKING'
        n.cancel_navigation()  # No handle yet: preserve send future.
        self.assertTrue(n.nav_pending())
        handle = Mock(accepted=True)
        result = Future()
        handle.get_result_async.return_value = result
        n.send_future.set_result(handle)
        n.poll_navigation()
        n.cancel_navigation()
        handle.cancel_goal_async.assert_called_once()
        self.assertTrue(n.nav_pending())
        result.set_result(NS(status=5))
        n.poll_navigation()
        self.assertFalse(n.nav_pending())

    def test_stop_waits_for_stationary_and_matching_home_ack(self):
        n = normal.NormalModeNode.__new__(normal.NormalModeNode)
        n.cancel_navigation = Mock()
        n.nav_pending = Mock(return_value=False)
        n.head_touched = True
        n.stationary = Mock(return_value=False)
        n.stage = 'TRACKING'
        n.event = Mock()
        n.home = Mock()
        n.stop_tick()
        n.home.assert_not_called()
        n.stationary.return_value = True
        n.stop_tick()
        self.assertEqual(n.stage, 'STOPPING')
        n.home.assert_called_once()
        n.head_done = Mock(return_value=True)
        n.fault_detail = ''
        n.stop_tick()
        n.event.assert_called_once_with('STOPPED', 'Normal mode stopped; camera centered')

    def test_old_head_session_or_stale_report_is_not_ready(self):
        n = normal.NormalModeNode.__new__(normal.NormalModeNode)
        n.session = 'new'
        n.head_seen = time.monotonic()
        n.head = dict(ready=True, session_id='old', done='anything')
        self.assertFalse(n.head_ready())
        n.head['session_id'] = 'new'
        self.assertTrue(n.head_ready())
        n.head_seen -= 2
        self.assertFalse(n.head_ready())

    def test_short_roam_lease_expires_when_controller_disappears(self):
        n = explore.ExplorationNode.__new__(explore.ExplorationNode)
        now = time.monotonic()
        n.normal_lease = ('one', now)
        n.mission_report = ('one', 'NORMAL', now)
        self.assertTrue(n.normal_authorized('one'))
        n.normal_lease = ('one', now-4)
        self.assertFalse(n.normal_authorized('one'))


class HeadProtocolTests(unittest.TestCase):
    def test_lcd_stage_session_and_stale_source(self):
        n = self.node()
        now = time.monotonic()
        n.normal_at = now
        n.normal_stage = 'REST'
        self.assertEqual(n.display_face(now), 1)
        n.on_normal(NS(data=json.dumps(dict(session_id='wrong', stage='NOD_DOWN'))))
        self.assertEqual(n.normal_stage, 'REST')
        for stage, face in [('MOVING', 2), ('TRACKING', 3), ('NOD_DOWN', 4), ('STOPPING', 5)]:
            n.on_normal(NS(data=json.dumps(dict(session_id='one', stage=stage))))
            self.assertEqual(n.display_face(time.monotonic()), face)
        self.assertEqual(n.display_face(now+4), 6)
        n.connection = None
        n.on_mission(NS(state='NORMAL', session_id='two'))
        self.assertEqual(n.normal_stage, '')
        self.assertEqual(n.normal_at, 0.)

    def node(self):
        n = head.HeadBridge.__new__(head.HeadBridge)
        n.ready = True
        n.last_rx = n.mission_at = time.monotonic()
        n.session = 'one'
        n.mission = 'NORMAL'
        n.recent = []
        n.serial_sequence = 0
        n.pending = None
        n.done = ''
        n.write = Mock()
        return n

    def test_invalid_session_nonfinite_and_exploration_cannot_move_head(self):
        n = self.node()
        req = dict(id='one', session_id='wrong', pan=90, tilt=90)
        n.command(NS(data=json.dumps(req)))
        req.update(session_id='one', pan=math.nan)
        n.command(NS(data=json.dumps(req)))
        req.update(pan=90)
        n.mission = 'EXPLORING'
        n.command(NS(data=json.dumps(req)))
        n.write.assert_not_called()

    def test_duplicate_and_late_ack_cannot_complete_new_command(self):
        n = self.node()
        req = NS(data=json.dumps(dict(id='client-id', session_id='one', pan=92, tilt=88)))
        n.command(req)
        n.command(req)
        n.write.assert_called_once_with('M 1 92 88 0')
        n.line('D 99')
        self.assertEqual(n.done, '')
        n.line('D 1')
        self.assertEqual(n.done, 'client-id')
        n.line('BOOT')
        self.assertEqual(n.done, '')
        self.assertFalse(n.ready)


class StrictNavigationTests(unittest.TestCase):
    def test_late_nav2_acceptance_waits_for_terminal_not_cancel_ack(self):
        n = navigation.NavigationManager.__new__(navigation.NavigationManager)
        n.node = Mock()
        n.client = Mock()
        n._goal_lock = threading.Lock()
        n._active_goal_handle = None
        n.server_timeout_sec = .1
        n.navigation_timeout_sec = 5
        sent, terminal, canceled = Future(), Future(), Future()
        canceled.set_result(NS())  # Cancellation acknowledgement is NOT termination.
        handle = Mock(accepted=True)
        handle.get_result_async.return_value = terminal
        handle.cancel_goal_async.return_value = canceled
        n.client.send_goal_async.return_value = sent
        clock = [0.]
        def sleep(seconds):
            clock[0] += seconds
            if clock[0] >= .3 and not sent.done():
                sent.set_result(handle)
            if clock[0] >= .8 and not terminal.done():
                terminal.set_result(NS(status=5))
        previous = navigation.time
        navigation.time = NS(monotonic=lambda:clock[0], sleep=sleep)
        try:
            outcome, _ = n._navigate_strict(NS(header=NS()), lambda:False)
        finally:
            navigation.time = previous
        self.assertEqual(outcome, navigation.NavigationOutcome.CANCELED)
        self.assertGreaterEqual(clock[0], .8)
        handle.cancel_goal_async.assert_called_once()
        self.assertIsNone(n._active_goal_handle)


class NormalWebStateTests(unittest.TestCase):
    def setUp(self):
        state.reset()
        commands.drain()

    def test_normal_stop_waits_for_real_stop_state_and_idle(self):
        state.apply_mission_report('IDLE', '')
        self.assertEqual(state.queue_mission_command('NORMAL', commands.send, {'IDLE'})[0], 202)
        self.assertFalse(state.apply_mission_report('IDLE', ''))
        state.apply_mission_report('NORMAL', 'normal-one')
        self.assertEqual(state.queue_mission_command('START', commands.send, {'IDLE'})[0], 409)
        self.assertEqual(state.queue_mission_command('NORMAL_STOP', commands.send, {'NORMAL'})[0], 202)
        self.assertFalse(state.apply_mission_report('IDLE', ''))
        state.apply_mission_report('NORMAL_STOPPING', 'normal-one')
        state.apply_mission_report('IDLE', '')
        self.assertEqual(state.snapshot()['pending_command'], '')

    def test_normal_start_requires_fresh_robot_status(self):
        self.assertEqual(state.queue_mission_command('NORMAL', commands.send, {'IDLE'})[0], 503)


@unittest.skipUnless(HAS_WEB, 'Flask dependencies required')
class NormalRoutes(unittest.TestCase):
    def test_normal_routes_and_conflict_status(self):
        from unittest.mock import patch
        import config
        from bridge.app import create_app
        with patch.object(config, 'USE_FAKE', False):
            state.reset()
            commands.drain()
            client = create_app().test_client()
            self.assertEqual(client.post('/normal/start').status_code, 503)
            state.apply_mission_report('IDLE', '')
            self.assertEqual(client.post('/normal/start').status_code, 202)
            state.apply_mission_report('NORMAL', 'normal-one')
            self.assertEqual(client.post('/sessions').status_code, 409)
            self.assertEqual(client.post('/normal/stop').status_code, 202)


if __name__ == '__main__':
    unittest.main()
