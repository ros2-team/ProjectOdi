"""Explore unknown space through frontier goals and Nav2 navigation."""

import math
import json
import threading
import time

import rclpy
from geometry_msgs.msg import PoseStamped
from nav_msgs.msg import OccupancyGrid
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import (
    DurabilityPolicy,
    QoSProfile,
    ReliabilityPolicy,
)
from rclpy.time import Time
from tf2_ros import Buffer, TransformListener

from odi_interfaces.action import Explore
from odi_interfaces.msg import MissionState
from std_msgs.msg import String

from odi_exploration.frontier_detector import FrontierDetector
from odi_exploration.roam_corridor import RoamCorridor
from odi_exploration.navigation_manager import (
    NavigationManager,
    NavigationOutcome,
)


class ExplorationNode(Node):
    """Provide the /explore action used by the Behavior Executor."""

    def __init__(self) -> None:
        super().__init__('exploration_node')

        self.callback_group = ReentrantCallbackGroup()
        self.goal_lock = threading.Lock()
        self.map_lock = threading.Lock()

        self.goal_reserved = False
        self.latest_map = None
        self.current_session_id = ''
        self.visited_goals: list[tuple[float, float]] = []
        self.failed_goals: list[tuple[float, float]] = []
        self.normal_lease = ('', 0.0)
        self.mission_report = ('', '', 0.0)
        self.create_subscription(String, '/normal/status', self.on_normal_status, 10,
                                 callback_group=self.callback_group)
        self.create_subscription(MissionState, '/mission/state', self.on_mission_report, 10,
                                 callback_group=self.callback_group)

        self._declare_parameters()
        self._read_parameters()

        self.frontier_detector = FrontierDetector(
            minimum_frontier_size=self.minimum_frontier_size,
            information_gain_weight=(
                self.frontier_information_gain_weight
            ),
            distance_weight=self.frontier_distance_weight,
        )

        map_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.map_subscription = self.create_subscription(
            OccupancyGrid,
            self.map_topic,
            self.map_callback,
            map_qos,
            callback_group=self.callback_group,
        )

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.navigation = NavigationManager(
            node=self,
            callback_group=self.callback_group,
            action_name=self.navigation_action_name,
            server_timeout_sec=self.navigation_server_timeout_sec,
            navigation_timeout_sec=self.navigation_timeout_sec,
        )

        self.action_server = ActionServer(
            self,
            Explore,
            '/explore',
            execute_callback=self.execute_callback,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self.callback_group,
        )

        self.get_logger().info(
            'Exploration Action Server is running'
        )

    def on_normal_status(self, msg):
        try:
            data = json.loads(msg.data)
            self.normal_lease = (data['session_id'], time.monotonic())
        except (ValueError, KeyError, TypeError):
            pass

    def on_mission_report(self, msg):
        self.mission_report = (msg.session_id, msg.state, time.monotonic())

    def normal_authorized(self, session):
        now = time.monotonic()
        return (self.normal_lease[0] == session and now-self.normal_lease[1] < 3
                and self.mission_report[0] == session and self.mission_report[1] == 'NORMAL'
                and now-self.mission_report[2] < 3)

    def _declare_parameters(self) -> None:
        """Declare configurable exploration and navigation values."""
        self.declare_parameter('map_topic', '/map')
        self.declare_parameter('robot_frame', 'base_footprint')
        self.declare_parameter('navigation_action_name', '/navigate_to_pose')
        self.declare_parameter('minimum_frontier_size', 3)
        self.declare_parameter('visited_goal_radius', 0.35)
        self.declare_parameter('failed_goal_radius', 0.35)
        self.declare_parameter('minimum_goal_distance', 0.5)
        self.declare_parameter('maximum_goal_distance', 5.0)
        self.declare_parameter('frontier_goal_offset', 0.3)
        self.declare_parameter('frontier_empty_retry_count', 4)
        self.declare_parameter('frontier_retry_delay_sec', 1.0)
        self.declare_parameter('frontier_information_gain_weight', 1.0)
        self.declare_parameter('frontier_distance_weight', 0.35)
        self.declare_parameter('obstacle_clearance', 0.25)
        self.declare_parameter('map_wait_timeout_sec', 10.0)
        self.declare_parameter('navigation_server_timeout_sec', 5.0)
        self.declare_parameter('navigation_timeout_sec', 120.0)
        self.declare_parameter('maximum_navigation_failures', 5)
        self.declare_parameter('roam_sampling_step', 5)
        self.declare_parameter('roam_minimum_goal_distance', 1.0)
        self.declare_parameter('roam_maximum_goal_distance', 3.0)
        self.declare_parameter('roam_direction_weight', 0.8)

    def _read_parameters(self) -> None:
        """Read declared parameters into ordinary attributes."""
        self.map_topic = self.get_parameter('map_topic').value
        self.robot_frame = self.get_parameter('robot_frame').value
        self.navigation_action_name = self.get_parameter(
            'navigation_action_name'
        ).value
        self.minimum_frontier_size = self.get_parameter(
            'minimum_frontier_size'
        ).value
        self.visited_goal_radius = self.get_parameter(
            'visited_goal_radius'
        ).value
        self.failed_goal_radius = self.get_parameter(
            'failed_goal_radius'
        ).value
        self.minimum_goal_distance = self.get_parameter(
            'minimum_goal_distance'
        ).value
        self.maximum_goal_distance = self.get_parameter(
            'maximum_goal_distance'
        ).value
        self.frontier_goal_offset = self.get_parameter(
            'frontier_goal_offset'
        ).value
        self.frontier_empty_retry_count = self.get_parameter(
            'frontier_empty_retry_count'
        ).value
        self.frontier_retry_delay_sec = self.get_parameter(
            'frontier_retry_delay_sec'
        ).value
        self.frontier_information_gain_weight = self.get_parameter(
            'frontier_information_gain_weight'
        ).value
        self.frontier_distance_weight = self.get_parameter(
            'frontier_distance_weight'
        ).value
        self.obstacle_clearance = self.get_parameter(
            'obstacle_clearance'
        ).value
        self.map_wait_timeout_sec = self.get_parameter(
            'map_wait_timeout_sec'
        ).value
        self.navigation_server_timeout_sec = self.get_parameter(
            'navigation_server_timeout_sec'
        ).value
        self.navigation_timeout_sec = self.get_parameter(
            'navigation_timeout_sec'
        ).value
        self.maximum_navigation_failures = self.get_parameter(
            'maximum_navigation_failures'
        ).value
        self.roam_sampling_step = self.get_parameter(
            'roam_sampling_step'
        ).value
        self.roam_minimum_goal_distance = self.get_parameter(
            'roam_minimum_goal_distance'
        ).value
        self.roam_maximum_goal_distance = self.get_parameter(
            'roam_maximum_goal_distance'
        ).value
        self.roam_direction_weight = self.get_parameter(
            'roam_direction_weight'
        ).value

    def map_callback(self, message: OccupancyGrid) -> None:
        """Store the newest SLAM occupancy map."""
        with self.map_lock:
            self.latest_map = message

    def goal_callback(self, request: Explore.Goal) -> GoalResponse:
        """Validate and reserve an incoming exploration goal."""
        session_id = request.session_id.strip()
        mode = request.mode.strip().upper()

        if not session_id:
            self.get_logger().warning(
                'Explore goal rejected: session_id is empty'
            )
            return GoalResponse.REJECT

        if mode not in {'FRONTIER', 'ROAM', 'SHORT_ROAM'}:
            self.get_logger().warning(
                f'Explore goal rejected: unsupported mode={mode}'
            )
            return GoalResponse.REJECT

        with self.goal_lock:
            if self.goal_reserved:
                self.get_logger().warning(
                    'Explore goal rejected: another goal is active'
                )
                return GoalResponse.REJECT
            self.goal_reserved = True

            if session_id != self.current_session_id:
                self.current_session_id = session_id
                self.visited_goals.clear()
                self.failed_goals.clear()

        self.get_logger().info(
            '\n::Explore goal received::'
            f'\nsession_id = {session_id}'
            f'\nmode = {mode}'
        )
        return GoalResponse.ACCEPT

    def cancel_callback(self, _goal_handle) -> CancelResponse:
        """Accept cancellation; execution will also cancel the Nav2 goal."""
        self.get_logger().info('Explore cancellation requested')
        return CancelResponse.ACCEPT

    def execute_callback(self, goal_handle) -> Explore.Result:
        """Select and visit goals until exhausted or externally canceled."""
        request = goal_handle.request
        mode = request.mode.strip().upper()
        last_area_id = ''
        navigation_failures = 0
        empty_frontier_checks = 0

        try:
            if not self._wait_for_map(goal_handle):
                return self._finish_canceled(
                    goal_handle,
                    last_area_id,
                    'Exploration canceled while waiting for a map',
                )

            while rclpy.ok():
                if (goal_handle.is_cancel_requested or
                        (mode == 'SHORT_ROAM' and not self.normal_authorized(request.session_id))):
                    self.navigation.cancel_active_goal()
                    return self._finish_canceled(
                        goal_handle,
                        last_area_id,
                        'Exploration canceled by Behavior Executor',
                    )

                try:
                    robot_x, robot_y, robot_yaw = (
                        self._get_robot_pose()
                    )
                except Exception as error:  # noqa: BLE001
                    return self._finish_aborted(
                        goal_handle,
                        last_area_id,
                        f'Robot TF is unavailable: {error}',
                    )

                if mode == 'FRONTIER':
                    selected = self._select_frontier_goal(
                        robot_x,
                        robot_y,
                    )
                    if selected is None:
                        empty_frontier_checks += 1
                        if (
                            empty_frontier_checks
                            <= self.frontier_empty_retry_count
                        ):
                            self.get_logger().info(
                                'No frontier candidate; waiting for '
                                'a newer map '
                                f'({empty_frontier_checks}/'
                                f'{self.frontier_empty_retry_count})'
                            )
                            time.sleep(self.frontier_retry_delay_sec)
                            continue
                        return self._finish_succeeded(
                            goal_handle,
                            status='FRONTIER_EXHAUSTED',
                            visited_area_id=last_area_id,
                            message='No unvisited frontier remains',
                        )
                    empty_frontier_checks = 0
                    area_id, goal_pose = selected
                else:
                    selected = self._select_roam_goal(
                        robot_x,
                        robot_y,
                        robot_yaw,
                        short=(mode == 'SHORT_ROAM'),
                    )
                    if selected is None:
                        if mode == 'SHORT_ROAM':
                            self.visited_goals.clear()  # Revisit only after the next rest interval.
                            return self._finish_succeeded(goal_handle, status='NO_GOAL',
                                visited_area_id='', message='No nearby safe goal')
                        self.visited_goals.clear()
                        time.sleep(0.5)
                        continue
                    area_id, goal_pose = selected

                last_area_id = area_id
                self._publish_feedback(
                    goal_handle,
                    area_id,
                    goal_pose,
                )

                self.get_logger().info(
                    '\n::Exploration navigation requested::'
                    f'\narea = {area_id}'
                    f'\nx = {goal_pose.pose.position.x:.2f}'
                    f'\ny = {goal_pose.pose.position.y:.2f}'
                )

                outcome, message = self.navigation.navigate(
                    goal_pose,
                    strict=(mode == 'SHORT_ROAM'),
                    cancel_requested=lambda: (
                        goal_handle.is_cancel_requested or
                        (mode == 'SHORT_ROAM' and not self.normal_authorized(request.session_id))
                    ),
                )

                if outcome == NavigationOutcome.CANCELED:
                    return self._finish_canceled(
                        goal_handle,
                        last_area_id,
                        message,
                    )

                if outcome == NavigationOutcome.ERROR:
                    return self._finish_aborted(
                        goal_handle,
                        last_area_id,
                        message,
                    )

                if outcome == NavigationOutcome.SUCCEEDED:
                    self.visited_goals.append(
                        (
                            goal_pose.pose.position.x,
                            goal_pose.pose.position.y,
                        )
                    )
                    if mode == 'SHORT_ROAM':
                        return self._finish_succeeded(goal_handle, status='STEP_COMPLETED',
                            visited_area_id=last_area_id, message='Short movement completed')
                    navigation_failures = 0
                    self.get_logger().info(
                        f'Exploration area reached: {area_id}'
                    )
                    time.sleep(0.3)
                    continue

                if mode == 'SHORT_ROAM':
                    return self._finish_aborted(goal_handle, last_area_id, message)
                self.failed_goals.append(
                    (
                        goal_pose.pose.position.x,
                        goal_pose.pose.position.y,
                    )
                )
                if len(self.failed_goals) > 100:
                    self.failed_goals = self.failed_goals[-100:]
                navigation_failures += 1
                self.get_logger().warning(message)

                if (
                    navigation_failures
                    >= self.maximum_navigation_failures
                ):
                    if mode == 'FRONTIER':
                        return self._finish_succeeded(
                            goal_handle,
                            status='FRONTIER_EXHAUSTED',
                            visited_area_id=last_area_id,
                            message=(
                                'Frontier candidates were unreachable: '
                                f'{message}'
                            ),
                        )
                    return self._finish_aborted(
                        goal_handle,
                        last_area_id,
                        'Repeated roam navigation failures: '
                        f'{message}',
                    )

            return self._finish_aborted(
                goal_handle,
                last_area_id,
                'ROS shutdown during exploration',
            )
        except Exception as error:  # noqa: BLE001
            self.get_logger().error(
                f'Unexpected exploration failure: {error}'
            )
            return self._finish_aborted(
                goal_handle,
                last_area_id,
                f'Unexpected exploration failure: {error}',
            )
        finally:
            with self.goal_lock:
                self.goal_reserved = False

    def _wait_for_map(self, goal_handle) -> bool:
        """Wait a bounded time for the first map message."""
        deadline = time.monotonic() + self.map_wait_timeout_sec
        while rclpy.ok() and time.monotonic() < deadline:
            if goal_handle.is_cancel_requested:
                return False
            with self.map_lock:
                if self.latest_map is not None:
                    return True
            time.sleep(0.05)
        if self.latest_map is None:
            raise RuntimeError(
                f'No map received from {self.map_topic}'
            )
        return True

    def _get_robot_pose(self) -> tuple[float, float, float]:
        """Read the robot position and yaw in the map frame from TF."""
        transform = self.tf_buffer.lookup_transform(
            'map',
            self.robot_frame,
            Time(),
            timeout=Duration(seconds=1.0),
        )
        rotation = transform.transform.rotation
        yaw = math.atan2(
            2.0 * (
                rotation.w * rotation.z
                + rotation.x * rotation.y
            ),
            1.0 - 2.0 * (
                rotation.y * rotation.y
                + rotation.z * rotation.z
            ),
        )
        return (
            transform.transform.translation.x,
            transform.transform.translation.y,
            yaw,
        )

    def _select_frontier_goal(
        self,
        robot_x: float,
        robot_y: float,
    ) -> tuple[str, PoseStamped] | None:
        """Choose the highest-scoring safe unvisited frontier."""
        map_message = self._get_latest_map()
        candidates = self.frontier_detector.detect(
            map_message,
            robot_x,
            robot_y,
        )

        for candidate in candidates:
            approach = self._find_frontier_approach(
                map_message,
                candidate.cell_x,
                candidate.cell_y,
                candidate.world_x,
                candidate.world_y,
                robot_x,
                robot_y,
            )
            if approach is None:
                continue
            goal_x, goal_y = approach
            goal_distance = math.hypot(
                goal_x - robot_x,
                goal_y - robot_y,
            )
            if not self._distance_is_allowed(goal_distance):
                continue
            if self._was_attempted(goal_x, goal_y):
                continue

            area_id = f'frontier_{candidate.cell_x}_{candidate.cell_y}'
            pose = self._make_goal_pose(
                goal_x,
                goal_y,
                robot_x,
                robot_y,
            )
            return area_id, pose

        return None

    def _select_roam_goal(
        self,
        robot_x: float,
        robot_y: float,
        robot_yaw: float,
        short: bool = False,
    ) -> tuple[str, PoseStamped] | None:
        """Choose an open local corridor, avoiding goals behind walls."""
        map_message = self._get_latest_map()
        width = map_message.info.width
        height = map_message.info.height
        data = map_message.data
        candidates = []
        corridor = RoamCorridor(map_message, self.obstacle_clearance)
        step = max(1, int(self.roam_sampling_step))

        minimum = 0.5 if short else self.roam_minimum_goal_distance
        maximum = 1.2 if short else self.roam_maximum_goal_distance
        for cell_y in range(0, height, step):
            for cell_x in range(0, width, step):
                index = cell_y * width + cell_x
                if data[index] != FrontierDetector.FREE:
                    continue
                world_x, world_y = FrontierDetector.cell_to_world(
                    cell_x,
                    cell_y,
                    map_message,
                )
                distance = math.hypot(
                    world_x - robot_x,
                    world_y - robot_y,
                )
                if not (
                    minimum
                    <= distance
                    <= maximum
                ):
                    continue
                if self._was_attempted(world_x, world_y):
                    continue

                openness = corridor.score(robot_x, robot_y, world_x, world_y)
                if openness is None:
                    continue

                target_distance = (
                    minimum
                    + maximum
                ) / 2.0
                distance_span = max(
                    maximum
                    - minimum,
                    0.1,
                )
                distance_score = max(
                    0.0,
                    1.0
                    - abs(distance - target_distance)
                    / distance_span,
                )
                goal_heading = math.atan2(
                    world_y - robot_y,
                    world_x - robot_x,
                )
                heading_score = (
                    1.0
                    + math.cos(goal_heading - robot_yaw)
                ) / 2.0
                score = (
                    distance_score
                    + self.roam_direction_weight
                    * heading_score
                    + 1.2 * openness
                )
                candidates.append(
                    (score, cell_x, cell_y, world_x, world_y)
                )

        if not candidates:
            return None

        _, cell_x, cell_y, world_x, world_y = max(candidates)
        area_id = f'roam_{cell_x}_{cell_y}'
        pose = self._make_goal_pose(
            world_x,
            world_y,
            robot_x,
            robot_y,
        )
        self.get_logger().info(
            f'Roam corridor selected: {area_id}, distance='
            f'{math.hypot(world_x-robot_x, world_y-robot_y):.2f} m, '
            f'openness={corridor.score(robot_x, robot_y, world_x, world_y):.2f}')
        return area_id, pose

    def _get_latest_map(self) -> OccupancyGrid:
        """Return the newest map after the initial wait has completed."""
        with self.map_lock:
            map_message = self.latest_map
        if map_message is None:
            raise RuntimeError('Map is unavailable')
        return map_message

    def _distance_is_allowed(self, distance: float) -> bool:
        """Check whether a candidate lies in the configured range."""
        return (
            self.minimum_goal_distance
            <= distance
            <= self.maximum_goal_distance
        )

    def _was_visited(self, world_x: float, world_y: float) -> bool:
        """Check whether a nearby goal was reached this session."""
        return any(
            math.hypot(
                world_x - visited_x,
                world_y - visited_y,
            ) < self.visited_goal_radius
            for visited_x, visited_y in self.visited_goals
        )

    def _was_attempted(self, world_x: float, world_y: float) -> bool:
        """Reject goals near previously reached or failed destinations."""
        if self._was_visited(world_x, world_y):
            return True
        return any(
            math.hypot(
                world_x - failed_x,
                world_y - failed_y,
            ) < self.failed_goal_radius
            for failed_x, failed_y in self.failed_goals
        )

    def _find_frontier_approach(
        self,
        map_message: OccupancyGrid,
        frontier_cell_x: int,
        frontier_cell_y: int,
        frontier_x: float,
        frontier_y: float,
        robot_x: float,
        robot_y: float,
    ) -> tuple[float, float] | None:
        """Find a fully known safe goal slightly inside a frontier."""
        resolution = map_message.info.resolution
        width = map_message.info.width
        height = map_message.info.height
        to_robot_x = robot_x - frontier_x
        to_robot_y = robot_y - frontier_y
        robot_distance = math.hypot(to_robot_x, to_robot_y)

        if robot_distance < 0.001:
            return None

        unit_x = to_robot_x / robot_distance
        unit_y = to_robot_y / robot_distance
        desired_x = frontier_x + unit_x * self.frontier_goal_offset
        desired_y = frontier_y + unit_y * self.frontier_goal_offset
        search_radius = max(
            1,
            math.ceil(
                (
                    self.frontier_goal_offset
                    + self.obstacle_clearance
                )
                / resolution
            ),
        )
        safe_cells = []

        for cell_y in range(
            frontier_cell_y - search_radius,
            frontier_cell_y + search_radius + 1,
        ):
            for cell_x in range(
                frontier_cell_x - search_radius,
                frontier_cell_x + search_radius + 1,
            ):
                if not (0 <= cell_x < width and 0 <= cell_y < height):
                    continue
                index = cell_y * width + cell_x
                if map_message.data[index] != FrontierDetector.FREE:
                    continue
                if not self._cell_has_clearance(
                    map_message,
                    cell_x,
                    cell_y,
                    allow_unknown=False,
                ):
                    continue

                world_x, world_y = FrontierDetector.cell_to_world(
                    cell_x,
                    cell_y,
                    map_message,
                )
                inward_projection = (
                    (world_x - frontier_x) * unit_x
                    + (world_y - frontier_y) * unit_y
                )
                if inward_projection <= 0.0:
                    continue
                score = math.hypot(
                    world_x - desired_x,
                    world_y - desired_y,
                )
                safe_cells.append((score, world_x, world_y))

        if not safe_cells:
            return None

        _, goal_x, goal_y = min(safe_cells)
        return goal_x, goal_y

    def _cell_has_clearance(
        self,
        map_message: OccupancyGrid,
        cell_x: int,
        cell_y: int,
        allow_unknown: bool,
    ) -> bool:
        """Reject cells too close to obstacles or unsafe map boundaries."""
        width = map_message.info.width
        height = map_message.info.height
        resolution = map_message.info.resolution
        radius = max(
            1,
            math.ceil(self.obstacle_clearance / resolution),
        )

        for y in range(cell_y - radius, cell_y + radius + 1):
            for x in range(cell_x - radius, cell_x + radius + 1):
                if not (0 <= x < width and 0 <= y < height):
                    return False
                value = map_message.data[y * width + x]
                if value >= 50:
                    return False
                if not allow_unknown and value == FrontierDetector.UNKNOWN:
                    return False
        return True

    def _make_goal_pose(
        self,
        goal_x: float,
        goal_y: float,
        robot_x: float,
        robot_y: float,
    ) -> PoseStamped:
        """Construct a map-frame goal facing the direction of travel."""
        yaw = math.atan2(goal_y - robot_y, goal_x - robot_x)
        pose = PoseStamped()
        pose.header.frame_id = 'map'
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.pose.position.x = goal_x
        pose.pose.position.y = goal_y
        pose.pose.orientation.z = math.sin(yaw / 2.0)
        pose.pose.orientation.w = math.cos(yaw / 2.0)
        return pose

    def _publish_feedback(
        self,
        goal_handle,
        area_id: str,
        goal_pose: PoseStamped,
    ) -> None:
        """Publish the selected exploration area and approximate progress."""
        feedback = Explore.Feedback()
        feedback.current_area_id = area_id
        feedback.current_goal = goal_pose
        feedback.progress = float(
            min(0.95, 0.05 + len(self.visited_goals) * 0.05)
        )
        goal_handle.publish_feedback(feedback)

    @staticmethod
    def _finish_succeeded(
        goal_handle,
        status: str,
        visited_area_id: str,
        message: str,
    ) -> Explore.Result:
        """Return a successful Explore action result."""
        result = Explore.Result()
        result.status = status
        result.visited_area_id = visited_area_id
        result.message = message
        goal_handle.succeed()
        return result

    @staticmethod
    def _finish_canceled(
        goal_handle,
        visited_area_id: str,
        message: str,
    ) -> Explore.Result:
        """Return a canceled Explore action result."""
        result = Explore.Result()
        result.status = 'CANCELED'
        result.visited_area_id = visited_area_id
        result.message = message
        goal_handle.canceled()
        return result

    @staticmethod
    def _finish_aborted(
        goal_handle,
        visited_area_id: str,
        message: str,
    ) -> Explore.Result:
        """Return an aborted Explore action result."""
        result = Explore.Result()
        result.status = 'FAILED'
        result.visited_area_id = visited_area_id
        result.message = message
        goal_handle.abort()
        return result

    def destroy_node(self) -> None:
        """Destroy action resources before the ROS node."""
        self.navigation.destroy()
        self.action_server.destroy()
        super().destroy_node()


def main(args=None) -> None:
    """Run the exploration node with concurrent action callbacks."""
    rclpy.init(args=args)
    node = ExplorationNode()
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(node)

    try:
        executor.spin()
    except KeyboardInterrupt:
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
