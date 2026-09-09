
import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy.callback_groups import ReentrantCallbackGroup

from datetime import timezone

from odi_interfaces.msg import (
    MissionState,
    StoredObservation,
)

from odi_interfaces.srv import (
    GetMissionObservations,
    GetSimilarObservations,
    SaveDiary,
    SaveObservation,
)
from odi_world_memory.database import Database

class WorldMemoryNode(Node):

    TERMINAL_MISSION_STATES = {
        'COMPLETED',
        'ERROR',
        'RESETTING',
    }

    def __init__(self):
        super().__init__('world_memory_node')

        self.database = Database()
        database_name = self.database.test_connection()
        self.get_logger().info(
            f"Connected to Mysql database : {database_name}"
        )

        self.callback_group = ReentrantCallbackGroup()

        self.mission_state_subscription = self.create_subscription(
            MissionState,
            '/mission/state',
            self.mission_state_callback,
            10,
            callback_group = self.callback_group,
        )
        self.save_observation_service = self.create_service(
            SaveObservation,
            '/world_memory/save_observation',
            self.save_observation_callback,
            callback_group = self.callback_group,
        )
        self.get_mission_observations_service = self.create_service(
            GetMissionObservations,
            '/world_memory/get_mission_observations',
            self.get_mission_observations_callback,
            callback_group = self.callback_group,
        )
        self.get_similar_observation_service = self.create_service(
            GetSimilarObservations,
            '/world_memory/get_similar_observations',
            self.get_similar_observation_callback,
            callback_group = self.callback_group,
        )
        self.save_diary_service = self.create_service(
            SaveDiary,
            '/world_memory/save_diary',
            self.save_diary_callback,
            callback_group = self.callback_group,
        )

        self.get_logger().info("Odi world memory node is running")

    def mission_state_callback(
            self,
            message
    ):

        if message.session_id.startswith('normal-'):
            return  # Normal mode does not create exploration diary sessions.
        if not message.session_id:
            self.get_logger().debug(
                "\n MissionState ignored : session_id is empty"
            )
            return

        if message.state == 'IDLE':
            return

        is_terminal = (
            message.state
            in self.TERMINAL_MISSION_STATES
        )

        updated_at = self.database.ros_time_to_datetime(
            message.updated_at
        )

        try:
            self.database.upsert_mission(
                session_id = message.session_id,
                status = message.state,
                detail = message.detail,
                updated_at = updated_at,
                is_terminal = is_terminal,
            )

            self.get_logger().info(
                f"\n :: Mission state saved ::"
                f"\n session = {message.session_id}"
                f"\n state = {message.state}"
            )

        except Exception as error:
            self.get_logger().error(
                f"\n Failed to save mission state : {error}"
            )



    def save_observation_callback(
            self,
            request,
            response
    ):
        observation = request.observation

        if not request.session_id:
            response.success = False
            response.message = 'session_id is empty'
            return response

        if not observation.detection_id:
            response.success = False
            response.message = 'detection_id is empty'
            return response

        if not observation.success:
            response.success = False
            response.message = (
                'Failed observation results are not stored'
            )
            return response

        if not observation.detailed_label.object_name:
            response.success = False
            response.message = 'object_name is empty'
            return response

        try:
            memory_id = self.database.save_observation(
                request.session_id,
                observation,
            )

            response.success = True
            response.memory_id = memory_id
            response.message = 'Observation saved successfully'
            self.get_logger().info(
                f'Observation saved : {memory_id}'
            )
        except Exception as error:
            response.success = False
            response.memory_id = ''
            response.message = f'Database error : {error}'
            self.get_logger().error(response.message)

        return response

    def save_diary_callback(
            self,
            request,
            response,
    ):
        if not request.session_id:
            response.success = False
            response.message = 'session_id is empty'
            return response

        if not request.diary_text.strip():
            response.success = False
            response.message = 'diary_text is empty'
            return response

        model_name = request.model_name.strip()

        if not model_name:
            model_name = 'unknown'

        try:
            diary_id = self.database.save_diary(
                request.session_id,
                request.diary_text,
                model_name,
            )
            response.success = True
            response.diary_id = diary_id
            response.message = 'Diary saved successfully'

            self.get_logger().info(
                f"\n ::Diary saved::"
                f"\n session_id = {request.session_id}"
                f"\n diary_id = {diary_id}"
            )

        except Exception as error:
            response.success = False
            response.diary_id = ''
            response.message = f"Database error : {error}"

            self.get_logger().error(response.message)

        return response

    def get_mission_observations_callback(
            self,
            request,
            response,
    ):

        if not request.session_id:
            response.success = False
            response.message = 'session_id is empty'
            return response

        try:
            records = self.database.get_mission_observations(request.session_id)

            response.observations = [
                self.record_to_stored_observation(record)
                for record in records
            ]

            response.success = True

            if records:
                response.message = (
                    f'{len(records)} observation(s) found'
                )

            else:
                response.message = 'No observation found'

            self.get_logger().info(
                f"Mission observation requested : "
                f"{request.session_id}, count = {len(records)}"
            )

        except Exception as error:
            response.success = False
            response.observations = []
            response.message = f'Database error : {error}'
            self.get_logger().error(response.message)

        return response

    def get_similar_observation_callback(
            self,
            request,
            response,
    ):
        encounter = request.encounter

        if not encounter.success:
            response.success = False
            response.message = "Encounter result was not successful"
            return response

        if not encounter.label.object_name:
            response.success = False
            response.message = "object_name is empty"

        max_results = request.max_results

        if max_results <= 0:
            max_results = 20
        elif max_results > 100:
            max_results = 100

        try:
            records = self.database.get_similar_observations(
                encounter.label.object_name,
                max_results,
            )

            response.observations = [
                self.record_to_stored_observation(record)
                for record in records
            ]

            response.success = True

            if records:
                response.message = (
                    f'{len(records)} similar observation(s) found'
                )
            else:
                response.message = (
                    'No similar observations found'
                )
            self.get_logger().info(
                f'similar observations requested : '
                f'object = {encounter.label.object_name}, count = {len(records)}'
            )

        except Exception as error:
            response.success = False
            response.observations = []
            response.message = f'Database error : {error}'

            self.get_logger().error(response.message)

        return response

    def record_to_stored_observation(
            self,
            record,
    ) -> StoredObservation:

        stored = StoredObservation()
        observation = stored.observation
        label = observation.detailed_label

        stored.memory_id = record['memory_id']
        stored.session_id = record['session_id']

        observation.detection_id = record['detection_id']
        observation.success = bool(record['success'])

        observation.image_paths = record['image_paths']
        observation.representative_image_path = record['representative_image_path'] or ''

        label.object_name = record['object_name']
        label.object_primary_color = record['object_primary_color'] or ''
        label.object_secondary_color = record['object_secondary_color'] or ''
        label.object_material = record['object_material'] or ''
        label.object_shape = record['object_shape'] or ''
        label.object_condition = record['object_condition'] or ''
        label.object_special_features = record['object_special_features'] or []
        label.raw_json = record['raw_json'] or ''

        observation.diary_summary = record['diary_summary'] or ''
        observation.saved_to_database = True
        observation.memory_id = record['memory_id']
        observation.failure_reason = record['failure_reason'] or ''

        self.datetime_to_ros_time(
            record['started_at'],
            observation.started_at,
        )
        self.datetime_to_ros_time(
            record['completed_at'],
            observation.completed_at,
        )
        self.datetime_to_ros_time(
            record['stored_at'],
            stored.stored_at,
        )

        return stored

    @staticmethod
    def datetime_to_ros_time(
        datetime_value,
        ros_time,
    ) -> None:

        if datetime_value is None:
            return

        if datetime_value.tzinfo is None:
            datetime_value = datetime_value.replace(
                tzinfo = timezone.utc
            )

        else:
            datetime_value = datetime_value.astimezone(
                timezone.utc
            )

        ros_time.sec = int(datetime_value.timestamp())
        ros_time.nanosec = datetime_value.microsecond * 1000

def main(args=None):
    rclpy.init(args=args)

    node = WorldMemoryNode()
    executor = MultiThreadedExecutor()
    executor.add_node(node)

    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
