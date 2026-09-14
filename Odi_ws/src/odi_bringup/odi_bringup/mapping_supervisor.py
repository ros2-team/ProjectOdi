"""Keep local SLAM/Nav2 running and capture the current home pose per mission.

This test variant intentionally avoids restarting Cartographer and Nav2 during
PREPARING.  The stack is started once when the robot layer boots; START only
checks that the existing stack is usable and captures the current map pose as
this mission's home pose.
"""

import copy
import math
import threading
import time

import rclpy
from geometry_msgs.msg import PoseStamped
from lifecycle_msgs.srv import GetState
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import OccupancyGrid, Odometry
from rclpy.action import ActionClient
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor, ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import QoSProfile, DurabilityPolicy, qos_profile_sensor_data
from rclpy.time import Time
from tf2_ros import Buffer, TransformListener

from odi_interfaces.msg import MissionState
from odi_interfaces.srv import PrepareMapping
from odi_bringup.owned_process import OwnedProcess


class MappingSupervisor(Node):
    def __init__(self):
        super().__init__('mapping_supervisor')
        self.declare_parameter('mapping_ready_timeout_sec', 60.0)
        self.declare_parameter('map_frame', 'map')
        self.declare_parameter('robot_frame', 'base_footprint')
        self.ready_timeout = float(self.get_parameter('mapping_ready_timeout_sec').value)

        sim_time = str(self.get_parameter('use_sim_time').value).lower()
        self.slam = OwnedProcess([
            'ros2', 'launch', 'turtlebot3_cartographer',
            'cartographer.launch.py', f'use_sim_time:={sim_time}'
        ])
        self.nav = OwnedProcess([
            'ros2', 'launch', 'nav2_bringup', 'navigation_launch.py',
            f'use_sim_time:={sim_time}', 'autostart:=true'
        ])

        self.busy = threading.Lock()
        self.booted = False
        self.group = ReentrantCallbackGroup()
        self.mission = None
        self.motion = None
        self.latest_map = None

        # Keep one TF listener for the lifetime of the supervisor.  The previous
        # implementation destroyed/recreated this listener during PREPARING,
        # which could race with MultiThreadedExecutor callbacks during cleanup.
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.create_subscription(
            MissionState,
            '/mission/state',
            self.on_mission,
            10,
            callback_group=self.group,
        )
        self.create_subscription(
            Odometry,
            '/odom',
            self.on_odom,
            qos_profile_sensor_data,
            callback_group=self.group,
        )
        self.create_subscription(
            OccupancyGrid,
            '/map',
            self.on_map,
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL),
            callback_group=self.group,
        )

        self.navigation = ActionClient(
            self,
            NavigateToPose,
            '/navigate_to_pose',
            callback_group=self.group,
        )
        self.lifecycle = [
            self.create_client(
                GetState,
                f'/{name}/get_state',
                callback_group=self.group,
            )
            for name in ('bt_navigator', 'planner_server', 'controller_server')
        ]

        self.create_service(
            PrepareMapping,
            '/odi/prepare_mapping',
            self.prepare,
            callback_group=self.group,
        )
        self.boot_timer = self.create_timer(0.1, self.boot)

    def boot(self):
        """Start Cartographer and Nav2 once for the robot session."""
        if not self.busy.acquire(blocking=False):
            return
        try:
            self.boot_timer.cancel()
            if self.booted:
                return
            self.booted = True
            self.get_logger().info('Starting persistent Cartographer/Nav2 stack')
            self.slam.start()
            self.nav.start()
        finally:
            self.busy.release()

    def on_mission(self, message):
        self.mission = message

    def on_odom(self, message):
        twist = message.twist.twist
        self.motion = (
            time.monotonic(),
            math.hypot(twist.linear.x, twist.linear.y),
            abs(twist.angular.z),
        )

    def on_map(self, message):
        self.latest_map = message

    def authorized(self, session):
        return (
            self.mission is not None
            and self.mission.session_id == session
            and self.mission.state == 'PREPARING'
        )

    def stop_stack(self):
        """Stop only the stack owned by this supervisor."""
        try:
            self.nav.stop()
        finally:
            self.slam.stop()

    def prepare(self, request, response):
        """Validate the existing stack and capture the current mission home pose."""
        response.success = False
        if not request.session_id or not self.busy.acquire(blocking=False):
            response.message = 'Mapping supervisor is busy or session is empty'
            return response

        try:
            # MissionState and the service request travel on different channels,
            # so briefly allow the PREPARING state message to arrive first.
            deadline = time.monotonic() + 2.0
            while (
                rclpy.ok()
                and not self.authorized(request.session_id)
                and time.monotonic() < deadline
            ):
                time.sleep(0.05)

            if not self.authorized(request.session_id):
                raise RuntimeError('Preparation requires the current PREPARING mission')

            motion = self.motion
            if (
                motion is None
                or time.monotonic() - motion[0] > 0.5
                or motion[1] > 0.02
                or motion[2] > 0.05
            ):
                raise RuntimeError(
                    'Robot must be stationary with fresh odometry before preparation'
                )

            self.get_logger().info(
                f'Checking existing map/Nav2 for session {request.session_id}'
            )
            response.home_pose = self.wait_ready(request.session_id)
            response.success = True
            response.message = 'Existing map, robot TF and Nav2 are ready'
            self.get_logger().info(response.message)
        except Exception as error:
            response.message = str(error)
            self.get_logger().error(response.message)
        finally:
            self.busy.release()

        return response

    def wait_ready(self, session):
        """Wait until the already-running map, Nav2 and robot TF are usable."""
        deadline = time.monotonic() + self.ready_timeout
        checks = None
        last_log = 0.0

        while rclpy.ok() and time.monotonic() < deadline:
            if not self.authorized(session):
                raise RuntimeError('Preparation canceled')

            if any(
                process.process is None or process.process.poll() is not None
                for process in (self.slam, self.nav)
            ):
                raise RuntimeError('SLAM or Nav2 is not running')

            lifecycle_ready = all(client.service_is_ready() for client in self.lifecycle)
            if checks is None and lifecycle_ready:
                checks = [client.call_async(GetState.Request()) for client in self.lifecycle]

            nav2_active = False
            if checks is not None and all(future.done() for future in checks):
                nav2_active = all(
                    future.result() is not None
                    and future.result().current_state.id == 3
                    for future in checks
                )
                if not nav2_active:
                    checks = None

            message = self.latest_map
            publisher_count = self.count_publishers('/map')
            if publisher_count > 1:
                raise RuntimeError(
                    'Multiple map publishers; stop the separately launched SLAM'
                )

            map_ready = (
                message is not None
                and message.info.width > 0
                and message.info.height > 0
                and any(0 <= cell < 50 for cell in message.data)
            )
            action_ready = self.navigation.server_is_ready()

            tf_ready = False
            transform = None
            if map_ready and nav2_active and action_ready:
                try:
                    transform = self.tf_buffer.lookup_transform(
                        self.get_parameter('map_frame').value,
                        self.get_parameter('robot_frame').value,
                        Time(),
                    )
                    tf_ready = True
                except Exception:
                    tf_ready = False

            if map_ready and nav2_active and action_ready and tf_ready:
                pose = PoseStamped()
                pose.header.frame_id = self.get_parameter('map_frame').value
                pose.header.stamp = self.get_clock().now().to_msg()
                pose.pose.position.x = transform.transform.translation.x
                pose.pose.position.y = transform.transform.translation.y
                pose.pose.position.z = transform.transform.translation.z
                pose.pose.orientation = copy.deepcopy(transform.transform.rotation)
                return pose

            now = time.monotonic()
            if now - last_log >= 2.0:
                self.get_logger().info(
                    'Preparation check: '
                    f'map={map_ready}, '
                    f'lifecycle_services={lifecycle_ready}, '
                    f'nav2_active={nav2_active}, '
                    f'navigate_to_pose={action_ready}, '
                    f'tf={tf_ready}, '
                    f'map_publishers={publisher_count}'
                )
                last_log = now

            time.sleep(0.1)

        raise RuntimeError(
            'Existing map, current TF or active Nav2 did not become ready in time'
        )


def main(args=None):
    rclpy.init(args=args)
    node = MappingSupervisor()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.shutdown()
        try:
            node.stop_stack()
        finally:
            node.destroy_node()
            if rclpy.ok():
                rclpy.shutdown()
