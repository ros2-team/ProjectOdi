import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'Odi_ws/src/odi_detection'))
from odi_detection.candidate_policy import CandidatePolicy

class LabelFlickerTests(unittest.TestCase):
    def test_label_change_keeps_handled_id(self):
        p=CandidatePolicy(min_hits=1)
        box=(40,80,140,200)
        first=p.update([(box,'suitcase')],320,240,0)[0]
        p.handled(first[2],.1)
        for t,name in ((.2,'cell phone'),(.4,'suitcase')):
            nxt=p.update([(box,name)],320,240,t)[0]
            self.assertEqual(nxt[2],first[2])
            self.assertFalse(nxt[3])

    def test_distant_or_stale_different_label_is_not_linked(self):
        for box,t in (((180,80,280,200),.2),((40,80,140,200),1.0)):
            p=CandidatePolicy(min_hits=1)
            old=p.update([((40,80,140,200),'suitcase')],320,240,0)[0]
            new=p.update([(box,'cell phone')],320,240,t)[0]
            self.assertNotEqual(old[2],new[2])

    def test_ambiguous_boxes_are_not_cross_linked(self):
        p=CandidatePolicy(min_hits=1)
        box=(40,80,140,200)
        old=p.update([(box,'suitcase')],320,240,0)[0]
        new=p.update([(box,'cell phone'),((42,82,142,202),'book')],320,240,.2)
        self.assertTrue(all(x[2]!=old[2] for x in new))
        self.assertEqual(len(set(x[2] for x in new)),2)

    def test_cooldown_lasts_ninety_seconds_and_new_mission_resets(self):
        p=CandidatePolicy(min_hits=1);box=(40,80,140,200)
        old=p.update([(box,'bottle')],320,240,0,(0,0))[0];p.handled(old[2],0)
        self.assertFalse(p.update([(box,'bottle')],320,240,89,(0,0))[0][3])
        self.assertTrue(p.update([(box,'bottle')],320,240,91,(0,0))[0][3])
        p.reset('next')
        self.assertTrue(p.update([(box,'bottle')],320,240,92,(0,0))[0][3])
