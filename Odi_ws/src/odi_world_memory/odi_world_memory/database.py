import os

import pymysql
from pymysql.cursors import DictCursor


class Database:

    def __init__(self):
        self.host = os.getenv('ODI_DB_HOST') or 'localhost'
        self.port = int(os.getenv('ODI_DB_PORT') or '3306')
        self.database = os.getenv('ODI_DB_NAME') or 'odi_db'
        self.user = os.getenv('ODI_DB_USER') or 'odi_user'

        password = os.getenv('ODI_DB_PASSWORD')

        if not password:
            raise RuntimeError(
                'ODI_DB_PASSWORD environment variable is not set.'
            )

        self.password = password

    def connect(self):
        return pymysql.connect(
            host=self.host,
            port=self.port,
            user=self.user,
            password=self.password,
            database=self.database,
            charset='utf8mb4',
            cursorclass=DictCursor,
            autocommit=False,
            connect_timeout=5,
        )

    def test_connection(self):
        with self.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    'SELECT DATABASE() AS database_name'
                )
                result = cursor.fetchone()

        if result is None:
            raise RuntimeError(
                'Database connection test returned no result.'
            )

        return result['database_name']
