"""Read-only list query contract; runs without MySQL or ROS."""
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from bridge import db


class DiaryListTest(unittest.TestCase):
    def test_photo_and_empty_diary_keep_all_missions(self):
        connection = sqlite3.connect(':memory:')
        connection.row_factory = sqlite3.Row
        connection.executescript('''
            CREATE TABLE missions(session_id TEXT, started_at TEXT);
            CREATE TABLE diaries(session_id TEXT, diary_text TEXT);
            CREATE TABLE observations(session_id TEXT, memory_id INTEGER,
                                      representative_image_path TEXT);
            INSERT INTO missions VALUES ('with-photo', NULL), ('empty', NULL);
            INSERT INTO diaries VALUES ('with-photo', 'A & B'), ('empty', '');
            INSERT INTO observations VALUES ('with-photo', 1, ''),
                ('with-photo', 2, '/data/bag.jpg');
        ''')
        class Cursor:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def execute(self, query): self.rows = connection.execute(query)
            def fetchall(self): return [dict(row) for row in self.rows]
        class Connection:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def cursor(self): return Cursor()
        try:
            with patch.object(db, '_connect', return_value=Connection()):
                rows = {item['id']: item for item in db.list_sessions()}
            self.assertEqual(rows['with-photo']['photo_url'], '/media/obs/bag.jpg')
            self.assertEqual(rows['with-photo']['observed_count'], 2)
            self.assertEqual(rows['with-photo']['line'], 'A &amp; B')
            self.assertIsNone(rows['empty']['photo_url'])
            self.assertEqual(rows['empty']['line'], '')
            self.assertEqual(rows['empty']['observed_count'], 0)
        finally:
            connection.close()


if __name__ == '__main__':
    unittest.main()
