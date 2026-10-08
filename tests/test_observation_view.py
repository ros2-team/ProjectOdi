"""Full-frame ROI filtering must preserve bottom targets and coordinates."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'Odi_ws/src/odi_detection'))
from odi_detection.candidate_policy import CandidatePolicy

class ObservationViewTests(unittest.TestCase):
    def test_top_band_boundary_and_excluded_classes(self):
        p = CandidatePolicy(ignored_top_ratio=.3)
        self.assertFalse(p.in_observation_view((0,0,100,100), 'bottle', 240))
        self.assertTrue(p.in_observation_view((0,44,100,100), 'bottle', 240))
        for name in ('person','chair','tv','laptop'):
            self.assertFalse(p.in_observation_view((0,100,100,220), name, 240))

    def test_small_target_requires_repeated_detections(self):
        p = CandidatePolicy(min_area=.01, min_hits=3, ignored_top_ratio=.3)
        box = (100,150,130,180)
        for t in (0,.2):
            self.assertFalse(p.update([(box,'bottle')],320,240,t)[0][3])
        item = p.update([(box,'bottle')],320,240,.4)[0]
        self.assertTrue(item[3])
        self.assertEqual(item[0], box)
