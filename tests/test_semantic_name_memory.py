"""Offline retrieval and identity regressions; no ROS or live MySQL required."""
import ast
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace as NS
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'Odi_ws/src/odi_world_memory'))
from odi_world_memory.object_names import memory_name_aliases
# Load the production class without requiring the unused MySQL transport.
db_path = ROOT/'Odi_ws/src/odi_world_memory/odi_world_memory/database.py'
db_tree = ast.parse(db_path.read_text())
db_ns = {'memory_name_aliases': memory_name_aliases, 'json': __import__('json')}
exec(compile(ast.Module(body=[n for n in db_tree.body if isinstance(n,ast.ClassDef)],
                        type_ignores=[]),str(db_path),'exec'),db_ns)
Database = db_ns['Database']


class NameMemoryTests(unittest.TestCase):
    def test_bidirectional_aliases_and_formatting(self):
        expected = memory_name_aliases('doll')
        for name in ('plush doll', ' PLUSH DOLL ', 'plush-doll', 'plush_doll', '봉제 인형'):
            self.assertEqual(memory_name_aliases(name), expected)

    def test_unlisted_names_are_not_broadly_grouped(self):
        for name in ('toy car', 'car', 'doll house', 'bottle'):
            self.assertEqual(memory_name_aliases(name), (name,))

    def test_query_reads_existing_aliases_without_rewriting_names(self):
        db = Database.__new__(Database)
        cursor = Mock()
        connection = Mock()
        from unittest.mock import MagicMock
        context = MagicMock()
        context.__enter__.return_value = cursor
        connection.cursor.return_value = context
        db.connect = Mock(return_value=connection)
        cursor.fetchall.return_value = []
        db.get_similar_observations('plush doll', 20)
        query, params = cursor.execute.call_args.args
        connection.close.assert_called_once()
        # Exercise SQL filtering over old rows; only DB placeholder syntax differs.
        columns = ['memory_id','session_id','detection_id','success','object_name',
                   'object_primary_color','object_secondary_color','object_material',
                   'object_shape','object_condition','object_special_features','raw_json',
                   'image_paths','representative_image_path','diary_summary',
                   'started_at','completed_at','stored_at','failure_reason']
        conn = sqlite3.connect(':memory:')
        self.addCleanup(conn.close)
        conn.execute('CREATE TABLE observations (' + ','.join(columns) + ')')
        for i, name in enumerate(('doll', 'Plush Doll', 'plush-doll', 'car', 'doll house')):
            conn.execute('INSERT INTO observations (object_name,stored_at) VALUES (?,?)',(name,i))
        rows = conn.execute(query.replace('%s','?'),params).fetchall()
        self.assertEqual([r[4] for r in rows], ['plush-doll','Plush Doll','doll'])
        cursor.reset_mock()
        db.get_similar_observations("unknown' OR 1=1 --",20)
        query, params = cursor.execute.call_args.args
        self.assertNotIn("unknown'",query)
        self.assertEqual(params, (*memory_name_aliases("unknown' OR 1=1 --"),20))


def engine(records):
    path = ROOT/'Odi_ws/src/odi_curiosity_engine/odi_curiosity_engine/curiosity_engine_node.py'
    tree = ast.parse(path.read_text())
    body = ast.parse('from __future__ import annotations').body
    body += [n for n in tree.body if isinstance(n,ast.ClassDef)]
    ns = dict(Node=object, W=NS(IDENTITY_THRESHOLD=.8,MAX_SIMILAR_RESULTS=20,WORLD_MEMORY_TIMEOUT=2),
              MemoryInfo=NS,GetSimilarObservations=NS(Request=NS))
    exec(compile(ast.Module(body=body,type_ignores=[]),str(path),'exec'),ns)
    cls = ns['CuriosityEngineNode']; n = cls.__new__(cls)
    n.cli_similar = Mock()
    n.cli_similar.call_async.return_value.result.return_value = NS(success=True,observations=records)
    n.wait_future = Mock(return_value=True)
    n.get_logger = Mock(return_value=Mock())
    n.stored_to_memory = lambda r:r
    n.calculator = Mock()
    n.calculator.calculate_similarity.side_effect = lambda c,r:r.score
    return n


class IdentityMemoryTests(unittest.TestCase):
    def test_unrelated_latest_record_is_not_change_baseline(self):
        other = NS(memory_id='other',score=.1)
        same = NS(memory_id='same',score=.9)
        older = NS(memory_id='older',score=.85)
        result = engine([other,same,older]).get_memory(NS(),NS())
        self.assertEqual(result.memory_id,'same')
        self.assertEqual(result.visit_count,2)
        self.assertEqual(result.compared_record_count,3)
        self.assertFalse(result.is_new)

    def test_same_name_but_different_features_remains_new(self):
        result = engine([NS(memory_id='other',score=.2)]).get_memory(NS(),NS())
        self.assertTrue(result.is_new)
        self.assertEqual(result.visit_count,0)

    def test_no_previous_memory_remains_new(self):
        self.assertTrue(engine([]).get_memory(NS(),NS()).is_new)

if __name__ == '__main__':
    unittest.main()
