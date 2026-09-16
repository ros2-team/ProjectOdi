"""Ensure rotation tuning preserves the rest of the navigation stack."""
import sys
import unittest
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Odi_ws/src/odi_bringup'))
from odi_bringup.navigation_config import merge_navigation_config


class NavigationConfigTests(unittest.TestCase):
    def test_overlay_retains_costmaps_dwb_and_recovery(self):
        base = {'controller_server': {'ros__parameters': {
            'FollowPath': {'plugin': 'dwb_core::DWBLocalPlanner',
                           'max_vel_x': .26, 'critics': ['BaseObstacle']},
            'progress_checker': {'plugin': 'nav2_controller::SimpleProgressChecker'}}},
            'local_costmap': {'robot_radius': .22, 'inflation_radius': .55},
            'behavior_server': {'behavior_plugins': ['spin', 'backup']}}
        overrides = yaml.safe_load((ROOT / 'Odi_ws/src/odi_bringup/config/navigation_overrides.yaml').read_text())
        result = merge_navigation_config(base, overrides)
        c = result['controller_server']['ros__parameters']
        self.assertEqual(c['FollowPath']['primary_controller'], 'dwb_core::DWBLocalPlanner')
        self.assertEqual(c['FollowPath']['critics'], ['BaseObstacle'])
        self.assertEqual(c['FollowPath']['max_vel_x'], .26)
        self.assertEqual(result['local_costmap'], base['local_costmap'])
        self.assertEqual(result['behavior_server'], base['behavior_server'])
        self.assertEqual(base['controller_server']['ros__parameters']['FollowPath']['plugin'], 'dwb_core::DWBLocalPlanner')
        # A 180-degree turn (~5.3s at .6 rad/s) has bounded time to complete.
        self.assertGreater(c['progress_checker']['movement_time_allowance'], 3.1416/.6 + 3)

    def test_incompatible_base_fails_instead_of_silently_replacing_controller(self):
        with self.assertRaises(ValueError):
            merge_navigation_config({'controller_server': {'ros__parameters': {
                'FollowPath': {'plugin': 'other'}}}}, {})
