
import json
import os
import uuid
from datetime import datetime, timezone

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

    @staticmethod
    def ros_time_to_datetime(time_message):
        if time_message.sec == 0 and time_message.nanosec == 0:
            return None

        timestamp = (
            time_message.sec
            + time_message.nanosec / 1_000_000_000
        )

        return datetime.fromtimestamp(
            timestamp,
            tz=timezone.utc,
        ).replace(tzinfo=None)

    def save_observation(self, session_id, observation):
        new_memory_id = str(uuid.uuid4())
        label = observation.detailed_label

        connection = self.connect()

        try:
            with connection.cursor() as cursor:
                # 단독 서비스 테스트에서도 FK 오류가 발생하지 않도록
                # 세션이 없으면 임시 EXPLORING 세션을 생성한다.
                cursor.execute(
                    """
                    INSERT INTO missions (
                        session_id,
                        status
                    )
                    VALUES (%s, 'EXPLORING')
                    ON DUPLICATE KEY UPDATE
                        updated_at = CURRENT_TIMESTAMP(6)
                    """,
                    (session_id,),
                )

                cursor.execute(
                    """
                    INSERT INTO observations (
                        memory_id,
                        session_id,
                        detection_id,
                        success,

                        object_name,
                        object_primary_color,
                        object_secondary_color,
                        object_material,
                        object_shape,
                        object_condition,
                        object_special_features,
                        raw_json,

                        image_paths,
                        representative_image_path,
                        diary_summary,

                        started_at,
                        completed_at,
                        failure_reason
                    )
                    VALUES (
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s,
                        %s, %s, %s
                    )
                    ON DUPLICATE KEY UPDATE
                        success = VALUES(success),

                        object_name = VALUES(object_name),
                        object_primary_color =
                            VALUES(object_primary_color),
                        object_secondary_color =
                            VALUES(object_secondary_color),
                        object_material = VALUES(object_material),
                        object_shape = VALUES(object_shape),
                        object_condition = VALUES(object_condition),
                        object_special_features =
                            VALUES(object_special_features),
                        raw_json = VALUES(raw_json),

                        image_paths = VALUES(image_paths),
                        representative_image_path =
                            VALUES(representative_image_path),
                        diary_summary = VALUES(diary_summary),

                        started_at = VALUES(started_at),
                        completed_at = VALUES(completed_at),
                        failure_reason = VALUES(failure_reason),
                        stored_at = CURRENT_TIMESTAMP(6)
                    """,
                    (
                        new_memory_id,
                        session_id,
                        observation.detection_id,
                        observation.success,

                        label.object_name,
                        label.object_primary_color,
                        label.object_secondary_color,
                        label.object_material,
                        label.object_shape,
                        label.object_condition,
                        json.dumps(
                            list(label.object_special_features),
                            ensure_ascii=False,
                        ),
                        label.raw_json,

                        json.dumps(
                            list(observation.image_paths),
                            ensure_ascii=False,
                        ),
                        observation.representative_image_path,
                        observation.diary_summary,

                        self.ros_time_to_datetime(
                            observation.started_at
                        ),
                        self.ros_time_to_datetime(
                            observation.completed_at
                        ),
                        observation.failure_reason,
                    ),
                )

                # 같은 session_id와 detection_id가 다시 들어오면
                # 기존 memory_id를 반환한다.
                cursor.execute(
                    """
                    SELECT memory_id
                    FROM observations
                    WHERE session_id = %s
                      AND detection_id = %s
                    """,
                    (
                        session_id,
                        observation.detection_id,
                    ),
                )

                saved_record = cursor.fetchone()

            if saved_record is None:
                raise RuntimeError(
                    "Saved observation could not be found"
                )
            connection.commit()
            return saved_record['memory_id']

        except Exception:
            connection.rollback()
            raise

        finally:
            connection.close()

    def get_mission_observations(self, session_id):
        connection = self.connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        memory_id,
                        session_id,
                        detection_id,
                        success,

                        object_name,
                        object_primary_color,
                        object_secondary_color,
                        object_material,
                        object_shape,
                        object_condition,
                        object_special_features,
                        raw_json,

                        image_paths,
                        representative_image_path,
                        diary_summary,

                        started_at,
                        completed_at,
                        stored_at,
                        failure_reason

                    FROM observations
                    WHERE session_id = %s
                    ORDER BY completed_at ASC, stored_at ASC
                    """,
                    (session_id,),
                )

                records = cursor.fetchall()

            for record in records:
                special_features = record['object_special_features']
                image_paths = record['image_paths']
                record['object_special_features'] = (
                    json.loads(special_features)
                    if special_features
                    else []
                )
                record['image_paths'] = (
                    json.loads(image_paths)
                    if image_paths
                    else []
                )
            return records

        finally:
            connection.close()

    def get_similar_observations(
            self,
            object_name,
            max_results,
    ):

        connection = self.connect()

        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        memory_id,
                        session_id,
                        detection_id,
                        success,

                        object_name,
                        object_primary_color,
                        object_secondary_color,
                        object_material,
                        object_shape,
                        object_condition,
                        object_special_features,
                        raw_json,

                        image_paths,
                        representative_image_path,
                        diary_summary,

                        started_at,
                        completed_at,
                        stored_at,
                        failure_reason

                    FROM observations
                    WHERE object_name = %s
                    ORDER BY stored_at DESC
                    LIMIT %s
                    """,
                    (
                        object_name,
                        max_results,
                    ),
                )

                records = cursor.fetchall()

            for record in records:
                special_features = record['object_special_features']
                image_paths = record['image_paths']

                record['object_special_features'] = (
                    json.loads(special_features)
                    if special_features
                    else []
                )
                record['image_paths'] = (
                    json.loads(image_paths)
                    if image_paths
                    else []
                )

            return records

        finally:
            connection.close()



