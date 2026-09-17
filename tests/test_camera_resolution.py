"""Check coordinate behavior when restoring the 640x480 camera stream."""
import math
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock
import unittest
import yaml
from test_session_lifecycle import load_classes
from test_normal_mode import Attention, tracking_angles

ROOT = Path(__file__).resolve().parents[1]

class CameraResolutionTests(unittest.TestCase):
    def test_locator_bearings_preserve_previous_field_of_view(self):
        class FakeNode:
            def __init__(self, *args): pass
            def create_subscription(self, *args): pass
            def create_publisher(self, *args): return Mock()
        module = load_classes(
            ROOT/'Odi_ws/src/odi_observation/odi_observation/observation_locator.py',
            Node=FakeNode, math=math, tf2_ros=Mock(),
            LaserScan=object, DetectedObject=object, PoseStamped=object,
            qos_profile_sensor_data=object())
        locator = module.ObservationLocator()
        for old_x in (0, 80, 157.2, 240, 319):
            expected = math.atan2(157.2-old_x, 270.2)
            self.assertAlmostEqual(locator.pixel_to_bearing(old_x*2), expected)

    def test_normal_mode_accepts_right_half_and_preserves_tracking_angles(self):
        config = yaml.safe_load((ROOT/'Odi_ws/src/odi_bringup/config/odi.yaml').read_text())
        params = config['normal_node']['ros__parameters']
        w,h = params['image_width'],params['image_height']
        policy = Attention(width=w,height=h)
        target = NS(detection_id='one',class_name='bottle',confidence=.95,
                    center_x=480,center_y=240,width=100,height=120)
        for t in (0,.1,.2):
            accepted = policy.observe(target,t)
        self.assertTrue(accepted)
        old = NS(center_x=240,center_y=120)
        self.assertEqual(tracking_angles(target,w,h,90,90,-1,1,(40,140),(0,100)),
                         tracking_angles(old,320,240,90,90,-1,1,(40,140),(0,100)))
