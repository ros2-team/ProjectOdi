"""Offline regressions for repeated missions; no ROS, robot, DB or model calls.

ROS class bodies are compiled from the production files with transport/model
dependencies replaced by small fakes. This exercises actual callbacks without
claiming to validate DDS delivery, executor scheduling, navigation or images.
HTTP tests additionally require Flask, flask-sock and PyMySQL.
"""

import ast
import asyncio
from dataclasses import dataclass, field
from enum import Enum
import importlib.util
from pathlib import Path
import sys
import time
from types import ModuleType, SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'Odi_ws/src'
sys.path.insert(0, str(SRC / 'odi_detection'))
from odi_detection.candidate_policy import CandidatePolicy, projected_range
sys.path.insert(0, str(ROOT / 'web_ws'))
from bridge import commands, state


class NodeFake:
    def get_logger(self):
        return Mock()


def load_classes(path, **dependencies):
    """Keep production class bodies intact; omit imports and the entry point."""
    parsed = ast.parse(path.read_text())
    body = ast.parse('from __future__ import annotations').body
    body += [node for node in parsed.body if isinstance(node, ast.ClassDef)]
    module = ModuleType('_offline_' + path.stem)
    sys.modules[module.__name__] = module
    module.__dict__.update(Node=NodeFake, dataclass=dataclass, field=field,
                           Enum=Enum, time=time, safe=lambda fn: fn)
    module.__dict__.update(dependencies)
    exec(compile(ast.Module(body=body, type_ignores=[]), str(path), 'exec'),
         module.__dict__)
    return module


blackboard_module = load_classes(
    SRC / 'odi_behavior_executor/odi_behavior_executor/blackboard.py')
behavior_module = load_classes(
    SRC / 'odi_behavior_executor/odi_behavior_executor/behavior_executor_node.py',
    ObjectProcessStage=blackboard_module.ObjectProcessStage)
detector_module = load_classes(
    SRC / 'odi_detection/odi_detection/yolo_node.py',
    DetectedObject=NS, DetectedObjectArray=NS, cv2=Mock(), math=__import__('math'),
    CandidatePolicy=CandidatePolicy, projected_range=projected_range)
reflection_module = load_classes(
    SRC / 'odi_reflection/odi_reflection/odi_reflection_node.py',
    Reflect=NS(Result=NS, Feedback=NS),
    GetMissionObservations=NS(Request=NS), SaveDiary=NS(Request=NS))
bridge_module = load_classes(ROOT / 'web_ws/bridge/ros_link.py', state=state,
                             route_archive=NS(load=lambda session:None))


class MissionStateTests(unittest.TestCase):
    def setUp(self):
        state.reset()
        list(commands.drain())

    def command(self, name):
        allowed = {'IDLE'} if name == 'START' else None
        return state.queue_mission_command(name, commands.send, allowed)[0]

    def test_start_needs_recent_robot_status(self):
        self.assertEqual(self.command('START'), 503)
        state.apply_mission_report('IDLE', '')
        with patch.object(state.time, 'monotonic', return_value=time.monotonic() + 6):
            self.assertEqual(self.command('START'), 503)
        self.assertEqual(list(commands.drain()), [])

    def test_double_start_enqueues_once_and_old_idle_does_not_unlock(self):
        state.apply_mission_report('IDLE', '')
        self.assertEqual(self.command('START'), 202)
        self.assertEqual(self.command('START'), 202)
        self.assertEqual(len(list(commands.drain())), 1)
        self.assertFalse(state.apply_mission_report('IDLE', ''))
        self.assertEqual(state.snapshot()['mission'], 'PREPARING')
        self.assertTrue(state.apply_mission_report('PREPARING', 'new'))
        self.assertEqual(state.snapshot()['pending_command'], '')

    def test_reset_waits_for_resetting_then_empty_idle(self):
        state.apply_mission_report('COMPLETED', 'old')
        self.assertEqual(self.command('RESET'), 202)
        self.assertEqual(self.command('START'), 409)
        for mission, session in [('COMPLETED', 'old'), ('IDLE', '')]:
            self.assertFalse(state.apply_mission_report(mission, session))
        self.assertTrue(state.apply_mission_report('RESETTING', 'old'))
        self.assertFalse(state.apply_mission_report('IDLE', 'old'))
        self.assertEqual(self.command('START'), 409)
        self.assertTrue(state.apply_mission_report('IDLE', ''))
        self.assertEqual(self.command('START'), 202)

    def test_reset_can_cancel_unacknowledged_start(self):
        state.apply_mission_report('IDLE', '')
        self.command('START')
        self.assertEqual(self.command('RESET'), 202)
        self.assertFalse(state.apply_mission_report('PREPARING', 'old'))
        self.assertFalse(state.apply_mission_report('EXPLORING', 'old'))
        state.apply_mission_report('RESETTING', 'old')
        state.apply_mission_report('IDLE', '')
        self.assertEqual(state.snapshot()['pending_command'], '')

    def test_queue_failure_does_not_change_state(self):
        state.apply_mission_report('IDLE', '')
        before = state.snapshot()
        status, _ = state.queue_mission_command('START', lambda _: False, {'IDLE'})
        self.assertEqual(status, 503)
        self.assertEqual(state.snapshot(), before)

    def test_three_sessions_clear_discoveries_and_keep_camera(self):
        state.apply_mission_report('IDLE', '')
        state.patch(camera={'live': True}, battery={'percent': 80})
        for index in range(3):
            self.assertEqual(self.command('START'), 202)
            state.apply_mission_report('PREPARING', str(index))
            self.assertEqual(state.snapshot()['discoveries'], [])
            self.assertEqual(state.snapshot()['camera'], {'live': True})
            state.apply_mission_report('EXPLORING', str(index))
            state.add_discovery({'detection_id': f'{index}:bag'})
            state.apply_mission_report('COMPLETED', str(index))
            self.command('RESET')
            state.apply_mission_report('RESETTING', str(index))
            state.apply_mission_report('IDLE', '')
            self.assertEqual(state.snapshot()['observed_count'], 0)

    def test_bridge_clears_paths_and_markers_but_retains_slam_map(self):
        bridge = bridge_module.OdiBridgeNode.__new__(bridge_module.OdiBridgeNode)
        bridge._session_id = 'old'
        bridge._path = [(1, 2)]
        bridge._markers = {'old:bag': (1, 2, 'OBSERVE')}
        bridge._exploring_since = 1.0
        bridge._map_last = 12.0
        original_map = bridge._map_msg = object()
        bridge.on_mission(NS(state='PREPARING', session_id='new'))
        self.assertEqual(bridge._path, [])
        self.assertEqual(bridge._markers, {})
        self.assertIsNone(bridge._map_msg)
        self.assertFalse(bridge._is_current_detection('old:bag'))
        self.assertTrue(bridge._is_current_detection('new:bag'))
        state.apply_mission_report('RESETTING', 'new')
        self.assertFalse(bridge._is_current_detection('new:bag'))


class DetectorTests(unittest.TestCase):
    def setUp(self):
        cls = detector_module.YoloNode
        self.node = cls.__new__(cls)
        for key, value in dict(frame_count=0, process_every_n_frames=1,
                               confidence=0.5, device='cpu', detection_episode=0,
                               episode_active=False, lost_frame_count=0,
                               lost_frame_threshold=2, current_session_id='',
                               mission_state='IDLE', last_batch_sent_at=None,
                               batch_publish_interval_sec=1.0).items():
            setattr(self.node, key, value)
        xy = Mock()
        xy.cpu.return_value.numpy.return_value.astype.return_value = [10, 20, 110, 180]
        self.result = NS(boxes=[NS(xyxy=[xy], cls=[0], conf=[0.9])], plot=Mock())
        self.node.model = Mock(return_value=[self.result])
        self.node.model.names = {0: 'backpack'}
        self.node.bridge = Mock()
        self.node.bridge.compressed_imgmsg_to_cv2.return_value = NS(shape=(240, 320, 3))
        self.node.policy = CandidatePolicy(min_hits=1)
        self.node.label_identity_enabled = True
        self.node.turn_identity_enabled = True
        self.node.recent_detection_guards_enabled = True
        self.node.turn_gate = Mock()
        self.node.turn_gate.allowed.return_value = True
        self.node.turn_gate.can_link.return_value = False
        self.node.odom_pose = None
        self.node.odom_received = 0.0
        self.node.scan_points_in_camera = Mock(return_value=[])
        self.node.maximum_observation_distance = 2.0
        self.node.range_notice_at = -100.0
        for name in ('image_publisher', 'detection_publisher', 'batch_publisher'):
            setattr(self.node, name, Mock())
        self.node._publish_best_crop = Mock()
        self.message = NS(header=NS())

    def frame(self, now):
        with patch.object(detector_module.time, 'monotonic', return_value=now):
            self.node.image_callback(self.message)

    def mission(self, name, session='one'):
        self.node.mission_callback(NS(state=name, session_id=session))

    def test_idle_preview_does_not_consume_first_detection(self):
        self.frame(1)
        self.mission('PREPARING')
        self.frame(2)
        self.node.batch_publisher.publish.assert_not_called()
        self.assertEqual(self.node.image_publisher.publish.call_count, 2)
        self.mission('EXPLORING')
        self.frame(3)
        self.node.batch_publisher.publish.assert_called_once()

    def test_retry_keeps_id_then_next_session_rearms_visible_object(self):
        self.mission('EXPLORING')
        self.frame(10)
        self.frame(10.5)
        self.frame(11)
        calls = self.node.batch_publisher.publish.call_args_list
        self.assertEqual(len(calls), 2)
        first_id = calls[0].args[0].objects[0].detection_id
        self.assertEqual(first_id, calls[1].args[0].objects[0].detection_id)
        self.node._publish_best_crop.assert_called_once()
        self.mission('RETURNING')
        self.frame(12)
        self.assertEqual(self.node.batch_publisher.publish.call_count, 2)
        self.mission('EXPLORING', 'two')
        self.frame(12.1)
        second_id = self.node.batch_publisher.publish.call_args.args[0].objects[0].detection_id
        self.assertNotEqual(first_id, second_id)
        self.assertTrue(second_id.startswith('two:'))

    def test_target_loss_starts_new_episode(self):
        self.mission('EXPLORING')
        self.frame(1)
        boxes = self.result.boxes
        self.result.boxes = []
        for now in (2, 3, 4):
            self.frame(now)
        self.result.boxes = boxes
        self.frame(5)
        calls = self.node.batch_publisher.publish.call_args_list
        self.assertNotEqual(calls[0].args[0].objects[0].detection_id,
                            calls[-1].args[0].objects[0].detection_id)

    def test_far_projected_target_keeps_preview_but_sends_no_candidate(self):
        self.mission('EXPLORING')
        self.node.camera_info = NS(k=[100, 0, 60, 0, 100, 100, 0, 0, 1])
        self.node.scan_points_in_camera.return_value = [(0, 0, 3, 3.0)]*3
        self.frame(1)
        self.node.batch_publisher.publish.assert_not_called()
        self.node.image_publisher.publish.assert_called_once()
        self.node.scan_points_in_camera.return_value = [(0, 0, 1, 1.0)]*3
        self.frame(2)
        self.node.batch_publisher.publish.assert_called_once()


class BehaviorTests(unittest.TestCase):
    def setUp(self):
        cls = behavior_module.BehaviorExecutorNode
        self.node = cls.__new__(cls)
        self.node.blackboard = blackboard_module.OdiBlackboard()
        self.node.blackboard.mission_state = 'EXPLORING'
        self.node.blackboard.session_id = 'new'
        self.node.cancel_exploration = Mock()
        self.node.select_next_object = Mock()

    def test_retries_do_not_trigger_same_batch_twice_or_accept_old_session(self):
        def detection(id):
            return NS(detection_id=id, class_name='bag', confidence=0.9,
                      width=100, height=100)
        callback = self.node.detected_objects_callback
        callback(NS(objects=[detection('old:bag')]))
        self.node.cancel_exploration.assert_not_called()
        callback(NS(objects=[detection('new:bag')]))
        self.node.blackboard.detection_locked = False
        callback(NS(objects=[detection('new:bag')]))
        self.node.cancel_exploration.assert_called_once()
        self.node.blackboard.reset()
        self.assertEqual(self.node.blackboard.handled_detection_ids, set())

    def test_old_curiosity_response_cannot_clear_new_request(self):
        old_future, new_future = Mock(), Mock()
        self.node.curiosity_future = new_future
        self.node.curiosity_request_active = True
        self.node.curiosity_response_callback(old_future, 'old', 'old:bag')
        old_future.result.assert_not_called()
        self.assertIs(self.node.curiosity_future, new_future)
        self.assertTrue(self.node.curiosity_request_active)

    def test_curiosity_response_after_return_is_ignored(self):
        future = Mock()
        self.node.curiosity_future = future
        self.node.curiosity_request_active = True
        self.node.blackboard.mission_state = 'RETURNING'
        self.node.curiosity_response_callback(future, 'new', 'new:bag')
        future.result.assert_not_called()
        self.assertFalse(self.node.curiosity_request_active)


class ServiceFake:
    def __init__(self, response):
        self.response = response
        self.requests = []

    def wait_for_service(self, **kwargs):
        return True

    async def call_async(self, request):
        self.requests.append(request)
        return self.response


class ReflectionTests(unittest.TestCase):
    def setUp(self):
        cls = reflection_module.ReflectionNode
        self.node = cls.__new__(cls)
        self.node.openai_model = 'configured-model'
        self.node.generate_diary_with_openai = Mock(return_value='Generated diary')
        self.node.get_observations_client = ServiceFake(
            NS(success=True, observations=[], message='ok'))
        self.node.save_diary_client = ServiceFake(
            NS(success=True, diary_id='diary-one', message='saved'))
        self.goal = Mock(request=NS(session_id='one'), is_cancel_requested=False)

    def execute(self):
        return asyncio.run(self.node.execute_callback(self.goal))

    def test_empty_observations_generate_and_save_diary(self):
        result = self.execute()
        self.assertTrue(result.success)
        self.goal.succeed.assert_called_once()
        self.node.generate_diary_with_openai.assert_called_once_with([])
        request = self.node.save_diary_client.requests[0]
        self.assertEqual(request.session_id, 'one')
        self.assertEqual('Generated diary', request.diary_text)
        self.assertEqual(request.model_name, 'configured-model')

    def test_regular_diary_still_uses_model(self):
        self.node.get_observations_client.response.observations = [object()]
        result = self.execute()
        self.assertTrue(result.success)
        self.node.generate_diary_with_openai.assert_called_once()
        self.assertEqual(self.node.save_diary_client.requests[0].model_name,
                         'configured-model')

    def test_db_read_failure_is_not_treated_as_empty_mission(self):
        self.node.get_observations_client.response.success = False
        self.assertFalse(self.execute().success)
        self.assertEqual(self.node.save_diary_client.requests, [])
        self.goal.abort.assert_called_once()

    def test_empty_diary_save_failure_aborts(self):
        self.node.save_diary_client.response.success = False
        self.assertFalse(self.execute().success)
        self.goal.abort.assert_called_once()
        self.goal.succeed.assert_not_called()

    def test_canceled_goal_does_not_save_or_succeed(self):
        self.goal.is_cancel_requested = True
        self.assertFalse(self.execute().success)
        self.assertEqual(self.node.save_diary_client.requests, [])
        self.goal.canceled.assert_called_once()
        self.goal.succeed.assert_not_called()


HAS_WEB = all(importlib.util.find_spec(name) for name in ('flask', 'flask_sock', 'pymysql'))


@unittest.skipUnless(HAS_WEB, 'Install Flask, flask-sock and PyMySQL for HTTP tests')
class WebRouteTests(unittest.TestCase):
    def setUp(self):
        import config
        self.config_patch = patch.object(config, 'USE_FAKE', False)
        self.config_patch.start()
        self.addCleanup(self.config_patch.stop)
        from bridge.app import create_app
        state.reset()
        list(commands.drain())
        self.client = create_app().test_client()

    def test_home_reset_blocks_start_until_robot_acknowledges(self):
        state.apply_mission_report('COMPLETED', 'old')
        self.assertEqual(self.client.post('/sessions/home').status_code, 202)
        self.assertEqual(self.client.get('/state').json['mission'], 'RESETTING')
        self.assertEqual(self.client.post('/sessions').status_code, 409)
        state.apply_mission_report('RESETTING', 'old')
        state.apply_mission_report('IDLE', '')
        self.assertEqual(self.client.post('/sessions').status_code, 202)

    def test_home_from_old_diary_does_not_stop_active_mission(self):
        state.apply_mission_report('EXPLORING', 'running')
        response = self.client.post('/sessions/home')
        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.json['command'])
        self.assertEqual(list(commands.drain()), [])

    def test_start_without_robot_status_returns_503(self):
        self.assertEqual(self.client.post('/sessions').status_code, 503)
        self.assertEqual(state.snapshot()['mission'], 'IDLE')


if __name__ == '__main__':
    unittest.main()
