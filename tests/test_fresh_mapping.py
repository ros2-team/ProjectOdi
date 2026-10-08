"""Offline preparation/cancellation regressions, without moving a robot."""
import copy
import math
import threading
import time
import uuid
from concurrent.futures import Future
from types import SimpleNamespace as NS
from unittest.mock import Mock
from unittest.mock import patch
import unittest

from test_session_lifecycle import SRC, load_classes

manager = load_classes(
    SRC / 'odi_mission_manager/odi_mission_manager/mission_manager_node.py',
    uuid=uuid, PrepareMapping=NS(Request=NS), SetHomePose=NS(Request=NS))
home = load_classes(SRC / 'odi_return_home/odi_return_home/return_home_node.py',
                    math=math, copy=copy)
supervisor = load_classes(SRC / 'odi_bringup/odi_bringup/mapping_supervisor.py',
                         rclpy=NS(ok=lambda: True), Buffer=Mock(), TransformListener=Mock())


class FreshMappingTests(unittest.TestCase):
    def node(self):
        node = manager.MissionManagerNode.__new__(manager.MissionManagerNode)
        node.current_state = manager.MissionStatus.IDLE
        node.session_id = ''
        node.preparation_future = None
        node.preparing_timer = None
        node.mapping_client = Mock()
        node.home_client = Mock()
        node.get_clock = Mock()
        node.publish_state = Mock()
        node.mapping_client.call_async.return_value = Future()
        node.home_client.call_async.return_value = Future()
        return node

    def test_waits_for_map_then_home_ack(self):
        n = self.node()
        n.handle_start_command()
        n.poll_preparation()
        self.assertEqual(n.current_state, manager.MissionStatus.PREPARING)
        n.preparation_future.set_result(NS(success=True, home_pose='fresh'))
        n.poll_preparation()
        self.assertEqual(n.current_state, manager.MissionStatus.PREPARING)
        n.poll_preparation()
        self.assertEqual(n.home_client.call_async.call_args.args[0].pose, 'fresh')
        n.preparation_future.set_result(NS(success=True))
        n.poll_preparation()
        self.assertEqual(n.current_state, manager.MissionStatus.EXPLORING)

    def test_failure_never_starts_exploring(self):
        n = self.node()
        n.handle_start_command()
        n.poll_preparation()
        n.preparation_future.set_result(NS(success=False, message='TF missing'))
        n.poll_preparation()
        self.assertEqual(n.current_state, manager.MissionStatus.ERROR)
        n.home_client.call_async.assert_not_called()

    def test_stop_during_prepare_waits_for_cleanup(self):
        n = self.node()
        n.handle_start_command()
        n.poll_preparation()
        pending = n.preparation_future
        n.handle_stop_command()
        n.handle_reset_completed()
        self.assertEqual(n.current_state, manager.MissionStatus.RESETTING)
        session = n.session_id
        n.handle_start_command()
        self.assertEqual(n.session_id, session)
        pending.set_result(NS(success=True, home_pose='late'))
        n.poll_preparation()
        self.assertEqual(n.current_state, manager.MissionStatus.IDLE)
        n.home_client.call_async.assert_not_called()

    def test_missing_service_times_out(self):
        n = self.node()
        n.handle_start_command()
        n.mapping_client.service_is_ready.return_value = False
        n.poll_preparation()
        n.mapping_client.call_async.assert_not_called()
        n.preparation_deadline = time.monotonic() - 1
        n.poll_preparation()
        self.assertEqual(n.current_state, manager.MissionStatus.ERROR)

    def test_timeout_keeps_inflight_request_until_cleanup(self):
        n = self.node()
        n.handle_start_command()
        n.poll_preparation()
        pending = n.preparation_future
        n.preparation_deadline = time.monotonic() - 1
        n.poll_preparation()
        n.handle_reset_command()
        n.handle_reset_completed()
        self.assertIs(n.preparation_future, pending)
        self.assertEqual(n.current_state, manager.MissionStatus.RESETTING)
        pending.set_exception(RuntimeError('Canceled'))
        n.poll_preparation()
        self.assertEqual(n.current_state, manager.MissionStatus.IDLE)

    def test_stop_after_preparation_still_returns_home(self):
        n = self.node()
        n.current_state = manager.MissionStatus.EXPLORING
        n.handle_stop_command()
        self.assertEqual(n.current_state, manager.MissionStatus.RETURNING)

    def test_home_update_rejects_active_goal_and_bad_pose(self):
        n = home.ReturnHomeNode.__new__(home.ReturnHomeNode)
        n.map_frame = 'map'
        n.goal_lock = threading.Lock()
        n.home_lock = threading.Lock()
        n.home_capture_timer = Mock()
        n.goal_reserved = True
        pose = NS(header=NS(frame_id='map'), pose=NS(
            position=NS(x=1., y=2., z=0.), orientation=NS(x=0., y=0., z=0., w=1.)))
        request = NS(session_id='new', pose=pose)
        self.assertFalse(n.set_home_pose(request, NS()).success)
        n.goal_reserved = False
        self.assertTrue(n.set_home_pose(request, NS()).success)
        self.assertIsNot(n.home_pose, pose)
        self.assertEqual(n.home_session_id, 'new')
        pose.pose.position.x = math.nan
        self.assertFalse(n.set_home_pose(request, NS()).success)
        self.assertEqual(n.home_pose.pose.position.x, 1.)

    def supervisor(self):
        n = supervisor.MappingSupervisor.__new__(supervisor.MappingSupervisor)
        n.busy = threading.Lock()
        n.mission = NS(session_id='new', state='PREPARING')
        n.motion = (time.monotonic(), 0., 0.)
        n.boot_timer = Mock()
        n.get_clock = Mock()
        n.tf_listener = Mock()
        n.slam, n.nav = Mock(), Mock()
        n.wait_ready = Mock(return_value='fresh home')
        return n

    def test_supervisor_restarts_only_owned_stack_before_ready(self):
        n = self.supervisor()
        calls = Mock()
        calls.attach_mock(n.nav, 'nav')
        calls.attach_mock(n.slam, 'slam')
        result = n.prepare(NS(session_id='new'), NS())
        self.assertTrue(result.success)
        self.assertEqual(result.home_pose, 'fresh home')
        self.assertEqual([c[0] for c in calls.mock_calls],
                         ['nav.stop', 'slam.stop', 'slam.start', 'nav.start'])
        n.wait_ready.assert_called_once()

    def test_supervisor_refuses_moving_robot(self):
        n = self.supervisor()
        n.motion = (time.monotonic(), .2, 0.)
        self.assertFalse(n.prepare(NS(session_id='new'), NS()).success)
        n.slam.stop.assert_not_called()

    def test_supervisor_cleans_up_failed_preparation(self):
        n = self.supervisor()
        n.wait_ready.side_effect = RuntimeError('Canceled')
        self.assertFalse(n.prepare(NS(session_id='new'), NS()).success)
        self.assertEqual(n.nav.stop.call_count, 2)
        self.assertEqual(n.slam.stop.call_count, 2)
        self.assertFalse(n.busy.locked())

    def test_readiness_rejects_canceled_session(self):
        n = self.supervisor()
        del n.wait_ready
        n.ready_timeout = 60
        n.mission.state = 'RESETTING'
        with self.assertRaisesRegex(RuntimeError, 'canceled'):
            n.wait_ready('new', 0)


if __name__ == '__main__':
    unittest.main()
