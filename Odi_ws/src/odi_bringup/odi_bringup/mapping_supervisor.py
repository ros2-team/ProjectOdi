"""Restart the local SLAM/Nav2 stack before each mission; keep robot sensors up."""

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
        self.slam = OwnedProcess(['ros2', 'launch', 'turtlebot3_cartographer',
                                 'cartographer.launch.py', f'use_sim_time:={sim_time}'])
        self.nav = OwnedProcess(['ros2', 'launch', 'nav2_bringup', 'navigation_launch.py',
                                f'use_sim_time:={sim_time}', 'autostart:=true'])
        self.busy = threading.Lock()
        self.booted = False
        self.group = ReentrantCallbackGroup()
        self.mission = None
        self.motion = None
        self.latest_map = None
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.create_subscription(MissionState, '/mission/state', self.on_mission, 10,
                                 callback_group=self.group)
        self.create_subscription(Odometry, '/odom', self.on_odom, qos_profile_sensor_data,
                                 callback_group=self.group)
        self.create_subscription(OccupancyGrid, '/map', self.on_map,
                                 QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL),
                                 callback_group=self.group)
        self.navigation = ActionClient(self, NavigateToPose, '/navigate_to_pose',
                                       callback_group=self.group)
        self.lifecycle = [self.create_client(GetState, f'/{name}/get_state',
                                            callback_group=self.group)
                          for name in ('bt_navigator', 'planner_server', 'controller_server')]
        self.create_service(PrepareMapping, '/odi/prepare_mapping', self.prepare,
                            callback_group=self.group)
        self.boot_timer = self.create_timer(0.1, self.boot)

    def boot(self):
        if not self.busy.acquire(blocking=False):
            return
        try:
            self.boot_timer.cancel()
            if self.booted:
                return
            self.booted = True
            self.slam.start()
            self.nav.start()
        finally:
            self.busy.release()

    def on_mission(self, message):
        self.mission = message

    def on_odom(self, message):
        twist = message.twist.twist
        self.motion = (time.monotonic(), math.hypot(twist.linear.x, twist.linear.y),
                       abs(twist.angular.z))

    def on_map(self, message):
        self.latest_map = message

    def authorized(self, session):
        return (self.mission is not None and self.mission.session_id == session
                and self.mission.state == 'PREPARING')

    def stop_stack(self):
        # Stop motion planning before removing its map/TF source.
        try:
            self.nav.stop()
        finally:
            self.slam.stop()

    def prepare(self, request, response):
        response.success = False
        if not request.session_id or not self.busy.acquire(blocking=False):
            response.message = 'Mapping supervisor is busy or session is empty'
            return response
        restarting = False
        try:
            # MissionState and the service request travel on different channels.
            deadline = time.monotonic() + 2.0
            while rclpy.ok() and not self.authorized(request.session_id) and time.monotonic() < deadline:
                time.sleep(0.05)
            if not self.authorized(request.session_id):
                raise RuntimeError('Map reset requires the current PREPARING mission')
            motion = self.motion
            if (motion is None or time.monotonic()-motion[0] > 0.5
                    or motion[1] > 0.02 or motion[2] > 0.05):
                raise RuntimeError('Robot must be stationary with fresh odometry before map reset')
            restarting = True
            self.booted = True
            self.boot_timer.cancel()
            self.get_logger().info(f'Preparing a fresh map for session {request.session_id}')
            self.stop_stack()
            self.latest_map = None
            # Recreate listeners so old map TF is discarded and static TF replays.
            self.tf_listener.unregister()
            self.tf_buffer = Buffer()
            self.tf_listener = TransformListener(self.tf_buffer, self)
            cutoff = self.get_clock().now().nanoseconds
            self.slam.start()
            self.nav.start()
            response.home_pose = self.wait_ready(request.session_id, cutoff)
            response.success = True
            response.message = 'Fresh map, robot TF and Nav2 are ready'
            self.get_logger().info(response.message)
        except Exception as error:
            response.message = str(error)
            self.get_logger().error(response.message)
            if restarting:
                try:
                    self.stop_stack()
                except Exception as stop_error:
                    response.message += f'; cleanup failed: {stop_error}'
        finally:
            self.busy.release()
        return response

    def wait_ready(self, session, cutoff):
        deadline = time.monotonic() + self.ready_timeout
        lifecycle_names = ('bt_navigator', 'planner_server', 'controller_server')
        checks = None
        checks_started_at = None
        lifecycle_state_text = 'not requested'
        last_log = 0.0

        while rclpy.ok() and time.monotonic() < deadline:
            if not self.authorized(session):
                raise RuntimeError('Fresh-map preparation canceled')
            if any(p.process is None or p.process.poll() is not None for p in (self.slam, self.nav)):
                raise RuntimeError('SLAM or Nav2 exited during preparation')

            lifecycle_ready = all(c.service_is_ready() for c in self.lifecycle)
            if checks is None and lifecycle_ready:
                checks = [c.call_async(GetState.Request()) for c in self.lifecycle]
                checks_started_at = time.monotonic()
                lifecycle_state_text = 'request pending'

            active = False
            if checks is not None:
                if all(f.done() for f in checks):
                    state_parts = []
                    state_ids = []
                    for name, future in zip(lifecycle_names, checks):
                        try:
                            result = future.result()
                            state_id = None if result is None else result.current_state.id
                            state_label = 'no response' if result is None else result.current_state.label
                        except Exception as error:
                            state_id = None
                            state_label = f'error:{error}'
                        state_ids.append(state_id)
                        state_parts.append(f'{name}={state_label}')

                    active = all(state_id == 3 for state_id in state_ids)
                    lifecycle_state_text = ', '.join(state_parts)
                    if not active:
                        # Nav2 is still transitioning. Request a fresh snapshot on
                        # the next loop instead of reusing results from startup.
                        checks = None
                        checks_started_at = None
                elif (checks_started_at is not None
                      and time.monotonic() - checks_started_at >= 1.0):
                    # A service request can be sent just before the old Nav2
                    # process disappears during restart. Such a Future may never
                    # complete even after the replacement node is ACTIVE. Drop
                    # that stale snapshot and retry against the current nodes.
                    lifecycle_state_text = 'request timeout; retrying'
                    checks = None
                    checks_started_at = None

            message = self.latest_map
            publisher_count = self.count_publishers('/map')
            if publisher_count > 1:
                raise RuntimeError('Multiple map publishers; stop the separately launched SLAM')

            map_ready = (message is not None and message.info.width > 0 and message.info.height > 0
                         and Time.from_msg(message.header.stamp).nanoseconds >= cutoff
                         and any(0 <= cell < 50 for cell in message.data))
            action_ready = self.navigation.server_is_ready()

            tf_found = False
            tf_stamp_after_cutoff = False
            tf_age = None
            tf_error = None

            if map_ready and active and action_ready:
                try:
                    frame = self.get_parameter('map_frame').value
                    transform = self.tf_buffer.lookup_transform(
                        frame, self.get_parameter('robot_frame').value, Time())
                    tf_found = True
                    stamp = Time.from_msg(transform.header.stamp).nanoseconds
                    tf_age = (self.get_clock().now().nanoseconds-stamp)*1e-9
                    tf_stamp_after_cutoff = stamp >= cutoff
                    if tf_stamp_after_cutoff and 0 <= tf_age <= 1.0:
                        pose = PoseStamped()
                        pose.header.frame_id = frame
                        pose.header.stamp = transform.header.stamp
                        pose.pose.position.x = transform.transform.translation.x
                        pose.pose.position.y = transform.transform.translation.y
                        pose.pose.orientation = copy.deepcopy(transform.transform.rotation)
                        return pose
                except Exception as error:
                    tf_error = str(error)

            now = time.monotonic()
            if now - last_log >= 2.0:
                age_text = 'n/a' if tf_age is None else f'{tf_age:.3f}s'
                self.get_logger().info(
                    'Preparation check: '
                    f'map_ready={map_ready}, '
                    f'lifecycle_services={lifecycle_ready}, '
                    f'nav2_active={active}, '
                    f'lifecycle_states=[{lifecycle_state_text}], '
                    f'navigate_to_pose={action_ready}, '
                    f'tf_found={tf_found}, '
                    f'tf_stamp_after_cutoff={tf_stamp_after_cutoff}, '
                    f'tf_age={age_text}, '
                    f'map_publishers={publisher_count}'
                )
                if tf_error is not None:
                    self.get_logger().warn(f'TF lookup failed: {tf_error}')
                last_log = now

            time.sleep(0.1)

        raise RuntimeError('Fresh map, current TF or active Nav2 did not become ready in time')


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
