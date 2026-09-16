import unittest
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Odi_ws/src/odi_detection'))
from odi_detection.turn_gate import TurnGate
from test_session_lifecycle import DetectorTests

class TurnGateTests(unittest.TestCase):
    def test_turn_settle_and_hysteresis(self):
        g=TurnGate();self.assertFalse(g.allowed(0))
        g.update(-.6,0);g.update(.15,.1);self.assertFalse(g.allowed(.1))
        g.update(.05,.2);g.update(.05,.6);self.assertFalse(g.allowed(.6))
        g.update(.05,.71);self.assertTrue(g.allowed(.71))
        g.update(.15,.8);self.assertTrue(g.allowed(.8))
        g.update(.21,.9);self.assertFalse(g.allowed(.9))

    def test_stale_invalid_and_interrupted_settle(self):
        g=TurnGate();g.update(0,0);g.update(.15,.3);g.update(0,.4)
        self.assertFalse(g.allowed(.8));g.update(0,.91);self.assertTrue(g.allowed(.91))
        self.assertFalse(g.allowed(2))
        g.update(0,2);self.assertFalse(g.allowed(2))
        g.update(float('nan'),2.5);self.assertFalse(g.allowed(2.5))

class TurnGateIntegrationTests(unittest.TestCase):
    def test_preview_continues_but_turning_hits_do_not_trigger_observation(self):
        f=DetectorTests();f.setUp();n=f.node;n.turn_gate=TurnGate()
        n.policy.min_hits=3
        f.mission('EXPLORING')
        for t in (0,.1,.2):
            n.turn_gate.update(.6,t);f.frame(t)
        self.assertEqual(n.image_publisher.publish.call_count,3)
        self.assertEqual(n.detection_publisher.publish.call_count,3)
        n.batch_publisher.publish.assert_not_called()
        n.turn_gate.update(0,.3);f.frame(.3)
        for t in (.81,.91,1.01):
            n.turn_gate.update(0,t);f.frame(t)
            if t<1:n.batch_publisher.publish.assert_not_called()
        self.assertEqual(n.batch_publisher.publish.call_count,1)
