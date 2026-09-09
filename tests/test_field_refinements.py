"""Offline candidate, UI state, and return-arrival regressions."""

from concurrent.futures import Future
import copy
import math
import threading
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

from test_session_lifecycle import (
    SRC, CandidatePolicy, projected_range, load_classes, bridge_module, state,
)


class CandidateTests(unittest.TestCase):
    def test_reordering_two_boxes_retains_individual_ids(self):
        policy = CandidatePolicy(min_hits=1)
        a, b = ((0, 0, 60, 80), 'bag'), ((150, 0, 200, 80), 'bag')
        first = policy.update([a, b], 320, 240, 1)
        second = policy.update([b, a], 320, 240, 2)
        self.assertEqual({r[0]: r[2] for r in first}, {r[0]: r[2] for r in second})
        self.assertEqual(len({r[2] for r in second}), 2)

    def test_small_background_and_unstable_candidates_are_filtered(self):
        policy = CandidatePolicy(min_hits=3)
        items = [((0, 0, 10, 10), 'bottle'), ((0, 0, 200, 200), 'tv'),
                 ((200, 0, 300, 200), 'backpack')]
        for now in (0.0, 0.2):
            self.assertFalse(any(r[3] for r in policy.update(items, 320, 240, now)))
        eligible = [r[1] for r in policy.update(items, 320, 240, 0.4) if r[3]]
        self.assertEqual(eligible, ['backpack'])

    def test_handled_target_suppressed_after_track_loss_then_rearmed_by_session(self):
        policy = CandidatePolicy(min_hits=1)
        item = [((0, 0, 100, 200), 'backpack')]
        policy.reset('one')
        first = policy.update(item, 320, 240, 0, (0, 0))[0]
        policy.update([], 320, 240, 4)
        policy.handled(first[2], 5)  # Result can arrive after image track loss.
        self.assertFalse(policy.update(item, 320, 240, 6, (0, 0))[0][3])
        policy.reset('two')
        self.assertTrue(policy.update(item, 320, 240, 7, (0, 0))[0][3])

    def test_different_location_not_blocked_by_local_cooldown(self):
        policy = CandidatePolicy(min_hits=1)
        item = [((0, 0, 100, 200), 'backpack')]
        key = policy.update(item, 320, 240, 0, (0, 0))[0][2]
        policy.handled(key, 1)
        self.assertTrue(policy.update(item, 320, 240, 5, (2, 0))[0][3])

    def test_scan_projection_needs_multiple_consistent_in_box_points(self):
        k = [100, 0, 160, 0, 100, 120, 0, 0, 1]
        box = (100, 50, 220, 200)
        points = [(0, 0, 3, 3.0), (0.01, 0, 3, 3.01), (-0.01, 0, 3, 2.99)]
        self.assertAlmostEqual(projected_range(points, box, k), 3.0)
        self.assertIsNone(projected_range(points[:1], box, k))
        self.assertIsNone(projected_range([(10, 0, 1, 10)]*3, box, k))
        self.assertIsNone(projected_range(points+[(0, 0, 8, 8)], box, k))

    def test_web_receives_mode_changes_and_ignores_empty_mode(self):
        state.reset()
        bridge = bridge_module.OdiBridgeNode.__new__(bridge_module.OdiBridgeNode)
        bridge.on_behavior(NS(behavior='EXPLORE', exploration_mode='ROAM'))
        self.assertEqual(state.snapshot()['explore_mode'], 'ROAM')
        bridge.on_behavior(NS(behavior='OBSERVE', exploration_mode=''))
        self.assertEqual(state.snapshot()['explore_mode'], 'ROAM')
        bridge.on_behavior(NS(behavior='EXPLORE', exploration_mode='FRONTIER'))
        self.assertEqual(state.snapshot()['explore_mode'], 'FRONTIER')


STATUS = NS(STATUS_SUCCEEDED=4, STATUS_CANCELED=5, STATUS_ABORTED=6)
return_module = load_classes(
    SRC / 'odi_return_home/odi_return_home/return_home_node.py',
    math=math, copy=copy, GoalStatus=STATUS, rclpy=NS(ok=lambda: True),
    NavigateToPose=NS(Goal=NS), ReturnHome=NS(Result=NS, Feedback=NS))


class ReturnTests(unittest.TestCase):
    def setUp(self):
        self.now = 0.0
        self.clock_patch = patch.object(return_module.time, 'monotonic', lambda: self.now)
        self.sleep_patch = patch.object(return_module.time, 'sleep', self.advance)
        self.clock_patch.start()
        self.sleep_patch.start()
        self.addCleanup(self.clock_patch.stop)
        self.addCleanup(self.sleep_patch.stop)
        cls = return_module.ReturnHomeNode
        self.node = cls.__new__(cls)
        self.node.goal_lock = threading.Lock()
        self.node.home_arrival_radius = 0.3
        self.node.home_arrival_hold_sec = 0.1
        self.node.navigation_timeout_sec = 0.5
        self.node.navigation_server_timeout_sec = 0.5
        self.node._wait_for_home_pose = Mock(return_value=NS(header=NS()))
        self.node.get_clock = Mock()
        self.node._distance_to_home = Mock(return_value=0.2)
        self.node._wait_for_stopped = Mock(return_value=True)
        self.result = Future()
        self.handle = Mock(accepted=True)
        self.handle.get_result_async.return_value = self.result
        self.handle.cancel_goal_async.side_effect = self.cancel
        sent = Future()
        sent.set_result(self.handle)
        self.node.navigation_client = Mock()
        self.node.navigation_client.send_goal_async.return_value = sent
        self.goal = Mock(is_cancel_requested=False)

    def advance(self, duration):
        self.now += duration

    def cancel(self):
        if not self.result.done():
            self.result.set_result(NS(status=STATUS.STATUS_CANCELED))
        return Future()

    def test_near_home_cancels_nav_then_confirms_stop_before_success(self):
        result = self.node.execute_callback(self.goal)
        self.assertTrue(result.success)
        self.handle.cancel_goal_async.assert_called_once()
        self.node._wait_for_stopped.assert_called_once()
        self.goal.succeed.assert_called_once()

    def test_cancel_ack_without_terminal_result_never_succeeds(self):
        self.handle.cancel_goal_async.side_effect = lambda: Future()
        self.assertFalse(self.node.execute_callback(self.goal).success)
        self.goal.succeed.assert_not_called()

    def test_brief_radius_entry_does_not_complete(self):
        self.node._distance_to_home.side_effect = lambda _: 0.2 if self.now < 0.05 else 1.0
        self.assertFalse(self.node.execute_callback(self.goal).success)
        self.goal.succeed.assert_not_called()

    def test_missing_tf_never_counts_as_arrival(self):
        self.node._distance_to_home.return_value = math.inf
        self.assertFalse(self.node.execute_callback(self.goal).success)
        self.goal.succeed.assert_not_called()

    def test_unconfirmed_motion_never_succeeds(self):
        self.node._wait_for_stopped.return_value = False
        self.assertFalse(self.node.execute_callback(self.goal).success)
        self.goal.succeed.assert_not_called()

    def test_user_cancel_is_not_reported_as_arrival(self):
        self.goal.is_cancel_requested = True
        self.assertFalse(self.node.execute_callback(self.goal).success)
        self.goal.canceled.assert_called_once()

    def test_stationary_check_rejects_stale_odometry(self):
        self.node.latest_motion = (-5.0, 0.0, 0.0)
        self.assertFalse(return_module.ReturnHomeNode._wait_for_stopped(self.node))

    def test_real_distance_helper_rejects_stale_tf(self):
        class Stamp:
            def __init__(self, seconds=0):
                self.seconds = seconds

            def __sub__(self, other):
                return NS(nanoseconds=int((self.seconds-other.seconds)*1e9))

            @staticmethod
            def from_msg(message):
                return Stamp(message.sec)

        self.node.map_frame, self.node.robot_frame = 'map', 'base_footprint'
        transform = NS(header=NS(stamp=NS(sec=9.5)),
                       transform=NS(translation=NS(x=0.2, y=0.0)))
        self.node.tf_buffer = Mock()
        self.node.tf_buffer.lookup_transform.return_value = transform
        self.node.get_clock.return_value.now.return_value = Stamp(10)
        home = NS(pose=NS(position=NS(x=0.0, y=0.0)))
        with patch.object(return_module, 'Time', Stamp, create=True), \
                patch.object(return_module, 'Duration', lambda **kw: NS(), create=True):
            read = return_module.ReturnHomeNode._distance_to_home
            self.assertAlmostEqual(read(self.node, home), 0.2)
            transform.header.stamp.sec = 7
            self.assertEqual(read(self.node, home), math.inf)
            self.node.tf_buffer.lookup_transform.side_effect = RuntimeError('missing TF')
            self.assertEqual(read(self.node, home), math.inf)


if __name__ == '__main__':
    unittest.main()
