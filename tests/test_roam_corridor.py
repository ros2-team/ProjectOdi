import math
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'Odi_ws/src/odi_exploration/odi_exploration'))
from roam_corridor import RoamCorridor


def grid():
    return NS(info=NS(width=100, height=100, resolution=0.05,
        origin=NS(position=NS(x=0., y=0.), orientation=NS(x=0., y=0., z=0., w=1.))),
        data=[0]*10000)


def wall(g, x, low=0, high=100, value=100):
    for y in range(low, high):
        g.data[y*100+x] = value


class TestRoamCorridor(unittest.TestCase):
    def test_open_corridor(self):
        self.assertAlmostEqual(RoamCorridor(grid(), .25).score(1, 2, 3, 2), 1)

    def test_wall_between_free_endpoints(self):
        g=grid(); wall(g, 50)
        self.assertIsNone(RoamCorridor(g, .25).score(1, 2, 3, 2))

    def test_unknown_between_free_endpoints(self):
        g=grid(); wall(g, 50, value=-1)
        self.assertIsNone(RoamCorridor(g, .25).score(1, 2, 3, 2))

    def test_short_wall_detour_is_not_local_roam(self):
        g=grid(); wall(g, 50, 35, 65)
        self.assertIsNone(RoamCorridor(g, .25).score(1, 2.5, 3, 2.5))

    def test_open_doorway(self):
        g=grid(); wall(g, 50, 0, 30); wall(g, 50, 70, 100)
        self.assertIsNotNone(RoamCorridor(g, .25).score(1, 2.5, 3, 2.5))

    def test_narrow_doorway(self):
        g=grid(); wall(g, 50, 0, 47); wall(g, 50, 53, 100)
        self.assertIsNone(RoamCorridor(g, .25).score(1, 2.5, 3, 2.5))

    def test_open_space_scores_above_wall_side(self):
        g=grid(); wall(g, 20)
        c=RoamCorridor(g, .25)
        self.assertGreater(c.score(1.325, 2, 3, 2), c.score(1.325, 2, 1.325, 3))

    def test_start_near_wall_can_move_away(self):
        g=grid(); wall(g, 20)
        self.assertIsNotNone(RoamCorridor(g, .25).score(1.175, 2, 2.5, 2))

    def test_start_near_wall_cannot_move_closer(self):
        g=grid(); wall(g, 20)
        self.assertIsNone(RoamCorridor(g, .25).score(1.175, 2, 1.075, 3))

    def test_start_near_wall_cannot_follow_wall_indefinitely(self):
        g=grid(); wall(g, 20)
        self.assertIsNone(RoamCorridor(g, .25).score(1.175, 2, 1.175, 3))

    def test_occupied_start(self):
        g=grid(); wall(g, 20)
        self.assertIsNone(RoamCorridor(g, .25).score(1.025, 2, 2.5, 2))

    def test_map_edge(self):
        self.assertIsNone(RoamCorridor(grid(), .25).score(1, 2, 5, 2))

    def test_rotated_map_origin(self):
        g=grid(); wall(g, 50)
        g.info.origin.position.x=10
        g.info.origin.orientation.z=math.sin(math.pi/4)
        g.info.origin.orientation.w=math.cos(math.pi/4)
        self.assertIsNone(RoamCorridor(g, .25).score(8, 1, 8, 3))


class TestSelectorIntegration(unittest.TestCase):
    def selector(self, g):
        import ast
        source_path = Path(__file__).with_name('exploration_node.py')
        if not source_path.exists():
            source_path = Path(__file__).resolve().parents[1] / 'Odi_ws/src/odi_exploration/odi_exploration/exploration_node.py'
        tree = ast.parse(source_path.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'ExplorationNode')
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == '_select_roam_goal')
        method.returns = None
        for arg in method.args.args:
            arg.annotation = None
        namespace = {'math': math, 'RoamCorridor': RoamCorridor,
            'FrontierDetector': NS(FREE=0, cell_to_world=lambda x,y,m: ((x+.5)*.05, (y+.5)*.05))}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<selector>', 'exec'), namespace)
        node = NS(_get_latest_map=lambda:g, obstacle_clearance=.25,
            roam_sampling_step=5, roam_minimum_goal_distance=1.,
            roam_maximum_goal_distance=3., roam_direction_weight=.8,
            _was_attempted=lambda x,y:False,
            _make_goal_pose=lambda x,y,rx,ry:(x,y),
            get_logger=lambda:NS(info=lambda text:None))
        return lambda x,y,yaw,short=False: namespace['_select_roam_goal'](node,x,y,yaw,short)

    def test_facing_wall_selects_same_side(self):
        g=grid(); wall(g,50)
        result = self.selector(g)(2,2,0)
        self.assertIsNotNone(result)
        self.assertLess(result[1][0], 2.5)

    def test_short_roam_stays_within_step_range(self):
        result = self.selector(grid())(2,2,0,True)
        self.assertIsNotNone(result)
        distance=math.hypot(result[1][0]-2,result[1][1]-2)
        self.assertGreaterEqual(distance,.5)
        self.assertLessEqual(distance,1.2)

if __name__ == '__main__':
    unittest.main()
