"""Explore unknown space through frontier goals and Nav2 navigation."""

import math
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

from odi_exploration.frontier_detector import FrontierDetector
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

        self._declare_parameters()
        self._read_parameters()

        self.frontier_detector = FrontierDetector(
            minimum_frontier_size=self.minimum_frontier_size,
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

    def _declare_parameters(self) -> None:
        """Declare configurable exploration and navigation values."""
        self.declare_parameter('map_topic', '/map')
        self.declare_parameter('robot_frame', 'base_footprint')
        self.declare_parameter('navigation_action_name', '/navigate_to_pose')
        self.declare_parameter('minimum_frontier_size', 5)
        self.declare_parameter('visited_goal_radius', 0.6)
        self.declare_parameter('minimum_goal_distance', 0.5)
        self.declare_parameter('maximum_goal_distance', 5.0)
        self.declare_parameter('obstacle_clearance', 0.25)
        self.declare_parameter('map_wait_timeout_sec', 10.0)
        self.declare_parameter('navigation_server_timeout_sec', 5.0)
        self.declare_parameter('navigation_timeout_sec', 120.0)
        self.declare_parameter('maximum_navigation_failures', 5)
        self.declare_parameter('roam_sampling_step', 8)

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
        self.minimum_goal_distance = self.get_parameter(
            'minimum_goal_distance'
        ).value
        self.maximum_goal_distance = self.get_parameter(
            'maximum_goal_distance'
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

        if mode not in {'FRONTIER', 'ROAM'}:
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

        try:
            if not self._wait_for_map(goal_handle):
                return self._finish_canceled(
                    goal_handle,
                    last_area_id,
                    'Exploration canceled while waiting for a map',
                )

            while rclpy.ok():
                if goal_handle.is_cancel_requested:
                    self.navigation.cancel_active_goal()
                    return self._finish_canceled(
                        goal_handle,
                        last_area_id,
                        'Exploration canceled by Behavior Executor',
                    )

                try:
                    robot_x, robot_y = self._get_robot_position()
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
                        return self._finish_succeeded(
                            goal_handle,
                            status='FRONTIER_EXHAUSTED',
                            visited_area_id=last_area_id,
                            message='No unvisited frontier remains',
                        )
                    area_id, goal_pose = selected
                else:
                    selected = self._select_roam_goal(
                        robot_x,
                        robot_y,
                    )
                    if selected is None:
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
                    cancel_requested=lambda: (
                        goal_handle.is_cancel_requested
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

                self.visited_goals.append(
                    (
                        goal_pose.pose.position.x,
                        goal_pose.pose.position.y,
                    )
                )

                if outcome == NavigationOutcome.SUCCEEDED:
                    navigation_failures = 0
                    self.get_logger().info(
                        f'Exploration area reached: {area_id}'
                    )
                    time.sleep(0.3)
                    continue

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

    def _get_robot_position(self) -> tuple[float, float]:
        """Read the robot position in the map frame from TF."""
        transform = self.tf_buffer.lookup_transform(
            'map',
            self.robot_frame,
            Time(),
            timeout=Duration(seconds=1.0),
        )
        return (
            transform.transform.translation.x,
            transform.transform.translation.y,
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
            if not self._distance_is_allowed(candidate.distance):
                continue
            if self._was_visited(candidate.world_x, candidate.world_y):
                continue
            if not self._cell_has_clearance(
                map_message,
                candidate.cell_x,
                candidate.cell_y,
                allow_unknown=True,
            ):
                continue

            area_id = f'frontier_{candidate.cell_x}_{candidate.cell_y}'
            pose = self._make_goal_pose(
                candidate.world_x,
                candidate.world_y,
                robot_x,
                robot_y,
            )
            return area_id, pose

        return None

    def _select_roam_goal(
        self,
        robot_x: float,
        robot_y: float,
    ) -> tuple[str, PoseStamped] | None:
        """Choose a distant safe free cell when no frontier remains."""
        map_message = self._get_latest_map()
        width = map_message.info.width
        height = map_message.info.height
        data = map_message.data
        candidates = []
        step = max(1, int(self.roam_sampling_step))

        for cell_y in range(0, height, step):
            for cell_x in range(0, width, step):
                index = cell_y * width + cell_x
                if data[index] != FrontierDetector.FREE:
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
                distance = math.hypot(
                    world_x - robot_x,
                    world_y - robot_y,
                )
                if not self._distance_is_allowed(distance):
                    continue
                if self._was_visited(world_x, world_y):
                    continue
                candidates.append(
                    (distance, cell_x, cell_y, world_x, world_y)
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
        """Check whether a nearby goal was already attempted this session."""
        return any(
            math.hypot(
                world_x - visited_x,
                world_y - visited_y,
            ) < self.visited_goal_radius
            for visited_x, visited_y in self.visited_goals
        )

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
