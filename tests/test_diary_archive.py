"""Diary generation, persistence and HTTP replay without robot or paid API calls."""
import base64
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'web_ws'))
import config
from bridge import db, mapper, route_archive
from test_session_lifecycle import load_classes

reflection = load_classes(ROOT/'Odi_ws/src/odi_reflection/odi_reflection/odi_reflection_node.py', json=json)

class DiaryContentTests(unittest.TestCase):
    def node(self, output):
        n=reflection.ReflectionNode.__new__(reflection.ReflectionNode)
        n.openai_model='test'; n.openai_client=Mock()
        n.openai_client.responses.create.return_value.output_text=output
        n.build_observation_data=Mock(return_value=[])
        return n

    def test_generated_closing_round_trip(self):
        n=self.node(json.dumps(dict(opening='오늘의 기록',closing='다음엔 무엇을 만날까.')))
        saved=n.generate_diary_with_openai([])
        self.assertEqual(db.diary_parts(saved), ('오늘의 기록','다음엔 무엇을 만날까.'))
        n.openai_client.responses.create.assert_called_once()

    def test_missing_closing_is_not_saved(self):
        with self.assertRaises(ValueError):
            self.node('{"opening":"본문"}').generate_diary_with_openai([])

    def test_bad_json_is_not_saved(self):
        with self.assertRaises(ValueError):
            self.node('not json').generate_diary_with_openai([])

    def test_legacy_text(self):
        self.assertEqual(db.diary_parts('기존 일기\n둘째 줄'),('기존 일기\n둘째 줄',''))

    def test_html_is_escaped(self):
        self.assertEqual(db._web_text('<script>x</script>'), '&lt;script&gt;x&lt;/script&gt;')

class RouteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.patch=patch.object(config,'DATASET_DIR',Path(self.temp.name))
        self.patch.start(); self.addCleanup(self.patch.stop)
        info=NS(width=50,height=50,resolution=.1,
            origin=NS(position=NS(x=0,y=0),orientation=NS(x=0,y=0,z=0,w=1)))
        self.png=Path(self.temp.name)/'live.png'
        self.view=mapper.render(NS(info=info,data=[0]*2500),self.png)

    def save(self, session='one',final=False,path=None):
        route_archive.save(session,self.view,self.png,path or [(1,1),(1.2,1.2)],(1.2,1.2),final)

    def test_snapshot_survives_live_map_overwrite_and_other_session(self):
        self.save(final=True)
        old=route_archive.public('one')
        from PIL import Image
        Image.new('RGB',(50,50),'blue').save(self.png); self.save('two')
        self.assertEqual(old,route_archive.public('one'))
        self.assertTrue(base64.b64decode(old['image'].split(',')[1]).startswith(b'\x89PNG'))

    def test_completed_snapshot_is_immutable(self):
        self.save(final=True); old=route_archive.load('one')
        self.save(path=[(3,3)])
        self.assertEqual(old,route_archive.load('one'))

    def test_partial_checkpoint_can_finalize(self):
        self.save(); self.assertFalse(route_archive.load('one')['complete'])
        self.save(final=True); self.assertTrue(route_archive.load('one')['complete'])

    def test_coordinate_jump_breaks_line(self):
        self.save(path=[(1,1),(1.1,1.1),(3,3),(3.1,3.1)])
        self.assertEqual(len(route_archive.load('one')['segments']),2)

    def test_start_and_end_use_same_map_geometry(self):
        self.save(); data=route_archive.load('one')
        self.assertEqual(data['start'],self.view.to_px(1,1))
        self.assertEqual(data['end'],self.view.to_px(1.2,1.2))

    def test_path_traversal_cannot_escape_archive_directory(self):
        self.save('../../outside')
        self.assertEqual(route_archive.archive_path('../../outside').parent,config.DATASET_DIR/'routes')

    def test_missing_or_corrupt_archive(self):
        self.assertIsNone(route_archive.public('missing'))
        self.save(); route_archive.archive_path('one').write_text('{')
        self.assertIsNone(route_archive.public('one'))

    def test_http_replays_saved_session_and_missing_map(self):
        from bridge import app
        self.save(final=True)
        with patch.object(config,'USE_FAKE',False), patch.object(app.diary_source,'get_session',return_value={'id':'one'}), patch.object(app.diary_source,'get_observations',return_value=[]):
            client=app.create_app().test_client()
            data=client.get('/api/sessions/one').get_json()
            self.assertTrue(data['session']['route']['complete'])
            self.assertIsNone(client.get('/api/sessions/old').get_json()['session']['route'])

    def test_png_file_contains_route_pixels_and_matches_replay(self):
        from PIL import Image
        from io import BytesIO
        self.save(path=[(1,1),(1.4,1),(1.8,1)])
        png=route_archive.archive_path('one').with_suffix('.png').read_bytes()
        self.assertEqual(png,base64.b64decode(route_archive.public('one')['image'].split(',')[1]))
        with Image.open(BytesIO(png)) as img:
            colors=set(img.getdata())
        self.assertIn((212,154,36),colors)  # Existing gold route line.
        self.assertIn((84,139,89),colors)   # Start marker.
        self.assertIn((199,123,40),colors)  # Last-position marker.

    def test_old_vector_archive_replays_as_png(self):
        self.save()
        target=route_archive.archive_path('one')
        data=route_archive.load('one');data['version']=1
        data['image']='data:image/png;base64,'+base64.b64encode(self.png.read_bytes()).decode()
        target.write_text(json.dumps(data))
        replay=route_archive.public('one')
        self.assertNotIn('segments',replay)
        self.assertNotEqual(replay['image'],data['image'])

    def test_restore_reads_world_points_from_disk(self):
        self.save()
        self.assertEqual(route_archive.load('one')['world_path'],[[1,1],[1.2,1.2]])


class RouteLifecycleTests(unittest.TestCase):
    def node(self):
        from bridge import state
        module=load_classes(ROOT/'web_ws/bridge/ros_link.py', state=state,
                            route_archive=NS(load=lambda session:None))
        n=module.OdiBridgeNode.__new__(module.OdiBridgeNode)
        n._session_id='one'; n._path=[(1,1)]; n._markers={}; n._pose=(1,1)
        n._map_msg=object(); n._map_last=0; n._exploring_since=None
        n.render_map=Mock(side_effect=lambda **kw: self.calls.append((state.snapshot()['session_id'],kw)))
        self.calls=[]; state.reset();state.apply_mission_report('RETURNING','one')
        return n,state

    def test_final_flush_precedes_reflection_state(self):
        n,state=self.node();n.on_mission(NS(state='REFLECTING',session_id='one',detail=''))
        self.assertEqual(self.calls,[('one',dict(force=True,final=True))])
        self.assertEqual(state.snapshot()['mission'],'REFLECTING')

    def test_new_mission_flushes_old_session_before_clear(self):
        n,state=self.node();n.on_mission(NS(state='PREPARING',session_id='two',detail=''))
        self.assertEqual(self.calls,[('one',dict(force=True,final=False))])
        self.assertEqual(n._path,[])
        self.assertIsNone(n._map_msg)

if __name__ == '__main__':
    unittest.main()
