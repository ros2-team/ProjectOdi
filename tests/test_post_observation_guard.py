import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch
import test_session_lifecycle as lifecycle
from odi_detection.candidate_policy import CandidatePolicy

A = (10, 40, 90, 200)
B = (220, 40, 300, 200)

class CompletionGuardTests(unittest.TestCase):
    def test_two_hits_are_required(self):
        p = CandidatePolicy()
        self.assertFalse(p.update([(A,'bottle')],320,240,0)[0][3])
        self.assertTrue(p.update([(A,'bottle')],320,240,.2)[0][3])

    def test_latest_box_not_initial_box_and_fixed_expiry(self):
        p = CandidatePolicy(min_hits=1)
        key = p.update([(A,'bottle')],320,240,0)[0][2]
        p.handled(key,0)
        p.update([(B,'bottle')],320,240,.5,turn_link=True)
        self.assertTrue(p.observation_completed(key,.6))
        rows = p.update([(B,'book'),(A,'cup')],320,240,.7,label_link=False)
        self.assertFalse(rows[0][3])
        self.assertTrue(rows[1][3])
        self.assertNotEqual(rows[0][2],key)
        # Repeated result must not extend the completion window.
        self.assertFalse(p.observation_completed(key,2))
        for t in (1.5, 2.5, 3.5, 4.5, 5.5, 6.5, 7.5, 8.5, 9.5, 10.5):
            self.assertFalse(p.update([(B,'book')],320,240,t)[0][3])
        self.assertTrue(p.update([(B,'book')],320,240,10.61)[0][3])

    def test_label_and_box_size_change_follow_latest_box(self):
        p = CandidatePolicy(min_hits=1)
        key = p.update([(A,'bottle')],320,240,0)[0][2]
        p.observation_completed(key,.1)
        # IoU < .3; center and size still satisfy the bounded fallback.
        shifted = (70,80,110,160)
        self.assertFalse(p.update([(shifted,'phone'),(B,'cup')],320,240,.2,
                                  label_link=False)[1][3])
        self.assertEqual(p.completion_guards[0]['box'],shifted)
        moved = (85,80,125,160)
        rows = p.update([(moved,'book'),(B,'cup')],320,240,.4,label_link=False)
        by_name = {name: eligible for _,name,_,eligible in rows}
        self.assertFalse(by_name['book'])
        self.assertTrue(by_name['cup'])
        self.assertEqual(p.completion_guards[0]['box'],moved)

    def test_two_second_absence_releases_guard(self):
        p = CandidatePolicy(min_hits=1)
        key = p.update([(A,'bottle')],320,240,0)[0][2]
        p.observation_completed(key,.1)
        p.update([],320,240,1)
        self.assertTrue(p.update([(A,'book')],320,240,2,label_link=False)[0][3])
        self.assertEqual(p.completion_guards,[])

    def test_ambiguous_boxes_release_guard(self):
        p = CandidatePolicy(min_hits=1)
        key = p.update([(A,'bottle')],320,240,0)[0][2]
        p.observation_completed(key,.1)
        rows = p.update([(A,'book'),((12,40,92,200),'cup')],320,240,.2,
                        label_link=False)
        self.assertTrue(all(row[3] for row in rows))
        self.assertEqual(p.completion_guards,[])

    def test_stale_or_missing_target_does_not_block_old_screen_region(self):
        p = CandidatePolicy(min_hits=1)
        key = p.update([(A,'bottle')],320,240,0)[0][2]
        self.assertFalse(p.observation_completed(key,5))
        self.assertFalse(p.observation_completed('missing',5))
        self.assertTrue(p.update([(A,'book')],320,240,5.1)[0][3])

    def test_small_overlap_and_new_session_are_not_blocked(self):
        p = CandidatePolicy(min_hits=1)
        key = p.update([(A,'bottle')],320,240,0)[0][2]
        p.observation_completed(key,.1)
        self.assertTrue(p.update([((80,40,160,200),'book')],320,240,.2)[0][3])
        p.reset('new')
        self.assertTrue(p.update([(A,'bottle')],320,240,.3)[0][3])

    def test_callback_guards_only_success_in_current_session(self):
        f = lifecycle.DetectorTests(); f.setUp()
        n=f.node
        n.recent_detection_guards_enabled=False
        n.label_identity_enabled=False
        f.mission('EXPLORING');f.frame(1)
        key=next(iter(n.policy.tracks))
        with patch.object(lifecycle.detector_module.time,'monotonic',return_value=1.1):
            n.observation_callback(NS(success=False,detection_id=key))
            n.observation_callback(NS(success=True,detection_id='other:track_0'))
            self.assertEqual(n.policy.completion_guards,[])
            n.observation_callback(NS(success=True,detection_id=key))
        n.batch_publisher.publish.reset_mock()
        n.model.names[0]='book'
        f.frame(2)
        n.batch_publisher.publish.assert_not_called()
        n.image_publisher.publish.assert_called()
        f.frame(4.2)
        n.batch_publisher.publish.assert_called_once()
