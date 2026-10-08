"""Exploration sounds must not alter motion or replay periodic state reports."""
import json
import time
import uuid
import unittest
from collections import deque
from types import SimpleNamespace as NS
from unittest.mock import Mock
from test_session_lifecycle import SRC, load_classes, blackboard_module
from test_normal_mode import head

behavior = load_classes(SRC/'odi_behavior_executor/odi_behavior_executor/behavior_executor_node.py',
    json=json, uuid=uuid, String=NS, ObjectProcessStage=blackboard_module.ObjectProcessStage)

class SoundTests(unittest.TestCase):
    def bridge(self):
        n = head.HeadBridge.__new__(head.HeadBridge)
        n.mission, n.session = 'EXPLORING', 'one'
        n.mission_at = n.last_rx = time.monotonic()
        n.ready = n.enabled = True
        n.connection = Mock()
        n.write = Mock()
        n.sound_recent = deque(maxlen=64)
        n.pending, n.done = (20, 'servo'), 'previous'
        return n

    def command(self, n, identifier='a', sound=4, session='one'):
        n.sound_command(NS(data=json.dumps(dict(id=identifier, session_id=session, sound=sound))))

    def executor(self):
        n = behavior.BehaviorExecutorNode.__new__(behavior.BehaviorExecutorNode)
        n.blackboard = NS(mission_state='EXPLORING', session_id='one')
        n.sound_publisher = Mock()
        n.current_behavior = behavior.BehaviorName.EXPLORE
        n.current_status = behavior.BehaviorStatus.RUNNING
        n.current_detail = ''
        n.publish_current_behavior = Mock()
        return n

    def test_sound_only_command_and_duplicate_delivery(self):
        n = self.bridge()
        self.command(n)
        self.command(n)
        n.write.assert_called_once_with('B 4')
        self.assertEqual(n.pending, (20, 'servo'))
        self.assertEqual(n.done, 'previous')

    def test_wrong_session_normal_mode_stale_or_unready_are_silent(self):
        n = self.bridge()
        self.command(n, session='old')
        n.mission = 'NORMAL'
        self.command(n)
        n.mission = 'EXPLORING'
        n.mission_at -= 5
        self.command(n, identifier='b')
        n.mission_at = time.monotonic()
        n.ready = False
        self.command(n, identifier='c')
        n.write.assert_not_called()

    def test_invalid_payloads_are_ignored(self):
        n = self.bridge()
        for data in ('null', '[]', '{}', 'not json', '{"sound":7}', '{"sound":true}'):
            n.sound_command(NS(data=data))
        self.command(n, sound=7)
        n.write.assert_not_called()

    def test_departure_and_arrival_are_transition_only(self):
        n = self.bridge()
        n.mission = 'PREPARING'
        msg = NS(state='EXPLORING', session_id='one')
        n.on_mission(msg)
        n.on_mission(msg)
        self.assertEqual([c.args[0] for c in n.write.call_args_list], ['H', 'B 1'])
        n.mission = 'RETURNING'
        n.write.reset_mock()
        msg.state = 'REFLECTING'
        n.on_mission(msg)
        n.on_mission(msg)
        self.assertEqual([c.args[0] for c in n.write.call_args_list], ['H', 'B 7'])

    def test_late_bridge_start_does_not_replay_arrival(self):
        n = self.bridge()
        n.mission = ''
        n.on_mission(NS(state='REFLECTING', session_id='one'))
        n.write.assert_called_once_with('H')

    def test_detail_and_status_repeats_do_not_repeat_discovery(self):
        n = self.executor()
        for detail in ('start', 'start', 'aligning', 'photo'):
            n.set_behavior(behavior.BehaviorName.FIRST_ENCOUNTER,
                           behavior.BehaviorStatus.RUNNING, detail)
        n.sound_publisher.publish.assert_called_once()
        self.assertEqual(json.loads(n.sound_publisher.publish.call_args.args[0].data)['sound'], 4)
        n.set_behavior(behavior.BehaviorName.OBSERVE, behavior.BehaviorStatus.RUNNING, 'observe')
        self.assertEqual(json.loads(n.sound_publisher.publish.call_args.args[0].data)['sound'], 5)

    def test_goodbye_only_for_successful_observation_once(self):
        for stage, count in [('OBSERVATION_COMPLETED', 1), ('FAILED', 0), ('IGNORED', 0)]:
            n = self.executor()
            n.blackboard.current_object = NS(detection_id='obj')
            n.blackboard.current_stage = getattr(blackboard_module.ObjectProcessStage, stage)
            n.blackboard.pending_objects = []
            n.complete_current_object()
            n.complete_current_object()
            self.assertEqual(n.sound_publisher.publish.call_count, count)
            if count:
                self.assertEqual(json.loads(n.sound_publisher.publish.call_args.args[0].data)['sound'], 6)

    def test_sound_publication_failure_does_not_abort_behavior(self):
        n = self.executor()
        n.sound_publisher.publish.side_effect = RuntimeError('offline')
        n.set_behavior(behavior.BehaviorName.OBSERVE, behavior.BehaviorStatus.RUNNING, 'observe')
        n.publish_current_behavior.assert_called_once()

if __name__ == '__main__':
    unittest.main()
