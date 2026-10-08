"""Startup diagnostics without ROS or serial hardware."""
import ast
import time
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / 'Odi_ws/src/odi_normal/odi_normal/normal_node.py'
cls = next(n for n in ast.parse(source.read_text()).body
           if isinstance(n, ast.ClassDef) and n.name == 'NormalModeNode')
methods = [n for n in cls.body if isinstance(n, ast.FunctionDef)
           and n.name in ('startup_problem', 'fault', 'stop_tick')]
namespace = {'time': time}
exec(compile(ast.Module(body=methods, type_ignores=[]), str(source), 'exec'), namespace)

class StartupTests(unittest.TestCase):
    def node(self):
        return NS(head_seen=time.monotonic(), session='one',
                  head=dict(ready=True, session_id='one'), stationary=lambda:True)

    def problem(self, node):
        return namespace['startup_problem'](node)

    def test_no_head_response(self):
        n=self.node(); n.head_seen=0
        self.assertIn('응답이 없어요', self.problem(n))

    def test_stale_head_response(self):
        n=self.node(); n.head_seen-=2
        self.assertIn('응답이 없어요', self.problem(n))

    def test_disabled(self):
        n=self.node(); n.head['enabled']=False
        self.assertIn('비활성화', self.problem(n))

    def test_serial_disconnected(self):
        n=self.node(); n.head.update(enabled=True, connected=False)
        self.assertIn('연결하지 못했어요', self.problem(n))

    def test_session_mismatch(self):
        n=self.node(); n.head['session_id']='old'
        self.assertIn('일치하지', self.problem(n))

    def test_firmware_not_ready(self):
        n=self.node(); n.head['ready']=False
        self.assertIn('준비되지', self.problem(n))

    def test_odometry_not_stationary(self):
        n=self.node(); n.stationary=lambda:False
        self.assertIn('정지 상태', self.problem(n))

    def test_previous_bridge_protocol_still_works(self):
        self.assertEqual(self.problem(self.node()), '')

    def test_fault_survives_stopped_event(self):
        n=self.node(); n.stop_requested=False
        n.get_logger=lambda:Mock(); n.event=Mock()
        namespace['fault'](n, 'USB disconnected')
        n.event.assert_called_with('FAULT', '[NORMAL_FAULT] USB disconnected')
        n.cancel_navigation=Mock(); n.nav_pending=lambda:False
        n.head_touched=False; n.set_stage=Mock()
        namespace['stop_tick'](n)
        n.event.assert_called_with('STOPPED', '[NORMAL_FAULT] USB disconnected')
        n.set_stage.assert_called_with('OFF')

if __name__ == '__main__':
    unittest.main()
