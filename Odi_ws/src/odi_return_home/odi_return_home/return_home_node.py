"""Return the robot to the pose captured when this node starts."""

import copy
import math
import threading
import time

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import (
    ActionClient,
    ActionServer,
    CancelResponse,
    GoalResponse,
)
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.duration import Duration
from rclpy.executors import MultiThreadedExecutor
from rclpy.node import Node
from rclpy.time import Time
from tf2_ros import Buffer, TransformListener

from odi_interfaces.action import ReturnHome


class ReturnHomeNode(Node):
    """Provide the /return_home action backed by Nav2 navigation."""

    def __init__(self) -> None:
        super().__init__('return_home_node')

        self.callback_group = ReentrantCallbackGroup()
        self.goal_lock = threading.Lock()
        self.home_lock = threading.Lock()

        self.goal_reserved = False
        self.active_navigation_goal = None
        self.home_pose = None

        self._declare_parameters()
        self._read_parameters()

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        self.navigation_client = ActionClient(
            self,
            NavigateToPose,
            self.navigation_action_name,
            callback_group=self.callback_group,
        )

        if self.use_configured_home:
            self.home_pose = self._configured_home_pose()

        self.home_capture_timer = self.create_timer(
            0.5,
            self._capture_initial_pose,
            callback_group=self.callback_group,
        )

        self.action_server = ActionServer(
            self,
            ReturnHome,
            '/return_home',
            execute_callback=self.execute_callback,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self.callback_group,
        )

        self.get_logger().info('Return Home Action Server is running')

    def _declare_parameters(self) -> None:
        """Declare home-pose, TF, and Nav2 parameters."""
        self.declare_parameter('map_frame', 'map')
        self.declare_parameter('robot_frame', 'base_footprint')
        self.declare_parameter('navigation_action_name', '/navigate_to_pose')
        self.declare_parameter('use_configured_home', False)
        self.declare_parameter('home_x', 0.0)
        self.declare_parameter('home_y', 0.0)
        self.declare_parameter('home_yaw', 0.0)
        self.declare_parameter('home_wait_timeout_sec', 10.0)
        self.declare_parameter('navigation_server_timeout_sec', 5.0)
        self.declare_parameter('navigation_timeout_sec', 180.0)

    def _read_parameters(self) -> None:
        """Read declared parameters into ordinary attributes."""
        self.map_frame = self.get_parameter('map_frame').value
        self.robot_frame = self.get_parameter('robot_frame').value
        self.navigation_action_name = self.get_parameter(
            'navigation_action_name'
        ).value
        self.use_configured_home = self.get_parameter(
            'use_configured_home'
        ).value
        self.home_x = self.get_parameter('home_x').value
        self.home_y = self.get_parameter('home_y').value
        self.home_yaw = self.get_parameter('home_yaw').value
        self.home_wait_timeout_sec = self.get_parameter(
            'home_wait_timeout_sec'
        ).value
        self.navigation_server_timeout_sec = self.get_parameter(
            'navigation_server_timeout_sec'
        ).value
        self.navigation_timeout_sec = self.get_parameter(
            'navigation_timeout_sec'
        ).value

    def _configured_home_pose(self) -> PoseStamped:
        """Create a home pose from configured coordinates."""
        pose = PoseStamped()
        pose.header.frame_id = self.map_frame
        pose.pose.position.x = float(self.home_x)
        pose.pose.position.y = float(self.home_y)
        pose.pose.orientation.z = math.sin(self.home_yaw / 2.0)
        pose.pose.orientation.w = math.cos(self.home_yaw / 2.0)
        return pose

    def _capture_initial_pose(self) -> None:
        """Capture the first available map-to-robot transform as home."""
        with self.home_lock:
            if self.home_pose is not None:
                self.home_capture_timer.cancel()
                return

        try:
            transform = self.tf_buffer.lookup_transform(
                self.map_frame,
                self.robot_frame,
                Time(),
                timeout=Duration(seconds=0.2),
            )
        except Exception:  # noqa: BLE001
            return

        pose = PoseStamped()
        pose.header.frame_id = self.map_frame
        pose.header.stamp = self.get_clock().now().to_msg()
        pose.pose.position.x = transform.transform.translation.x
        pose.pose.position.y = transform.transform.translation.y
        pose.pose.position.z = transform.transform.translation.z
        pose.pose.orientation = transform.transform.rotation

        with self.home_lock:
            if self.home_pose is None:
                self.home_pose = pose

        self.home_capture_timer.cancel()
        self.get_logger().info(
            '\n::Home pose captured::'
            f'\nx = {pose.pose.position.x:.2f}'
            f'\ny = {pose.pose.position.y:.2f}'
        )

    def goal_callback(self, request: ReturnHome.Goal) -> GoalResponse:
        """Reserve the server for one return request at a time."""
        with self.goal_lock:
            if self.goal_reserved:
                self.get_logger().warning(
                    'Return Home goal rejected: another goal is active'
                )
                return GoalResponse.REJECT
            self.goal_reserved = True

        self.get_logger().info(
            '\n::Return Home goal received::'
            f'\nreason = {request.reason}'
        )
        return GoalResponse.ACCEPT

    def cancel_callback(self, _goal_handle) -> CancelResponse:
        """Accept cancellation and allow execution to stop Nav2."""
        self.get_logger().info('Return Home cancellation requested')
        return CancelResponse.ACCEPT

    def execute_callback(self, goal_handle) -> ReturnHome.Result:
        """Navigate to the stored home pose and return the action result."""
        try:
            self._publish_feedback(
                goal_handle,
                'PREPARING',
                0.10,
                'Loading the mission start pose',
            )

            home_pose = self._wait_for_home_pose(goal_handle)
            if home_pose is None:
                return self._finish_canceled(
                    goal_handle,
                    'Return Home canceled while waiting for home pose',
                )

            if not self.navigation_client.wait_for_server(
                timeout_sec=self.navigation_server_timeout_sec,
            ):
                return self._finish_aborted(
                    goal_handle,
                    'NavigateToPose action server is unavailable',
                )

            navigation_goal = NavigateToPose.Goal()
            navigation_goal.pose = copy.deepcopy(home_pose)
            navigation_goal.pose.header.stamp = (
                self.get_clock().now().to_msg()
            )

            initial_distance = self._distance_to_home(home_pose)

            self._publish_feedback(
                goal_handle,
                'NAVIGATING',
                0.20,
                'Moving to the mission start pose',
            )

            send_future = self.navigation_client.send_goal_async(
                navigation_goal,
                feedback_callback=lambda message: (
                    self._navigation_feedback(
                        goal_handle,
                        message,
                        initial_distance,
                    )
                ),
            )

            send_deadline = (
                time.monotonic()
                + self.navigation_server_timeout_sec
            )
            while rclpy.ok() and not send_future.done():
                if time.monotonic() >= send_deadline:
                    return self._finish_aborted(
                        goal_handle,
                        'NavigateToPose goal response timed out',
                    )
                time.sleep(0.05)

            if not send_future.done():
                return self._finish_aborted(
                    goal_handle,
                    'ROS shutdown while sending return navigation goal',
                )

            navigation_goal_handle = send_future.result()
            if (
                navigation_goal_handle is None
                or not navigation_goal_handle.accepted
            ):
                return self._finish_aborted(
                    goal_handle,
                    'NavigateToPose goal was rejected',
                )

            with self.goal_lock:
                self.active_navigation_goal = navigation_goal_handle

            if goal_handle.is_cancel_requested:
                self._cancel_navigation(navigation_goal_handle)
                return self._finish_canceled(
                    goal_handle,
                    'Return Home canceled before navigation',
                )

            result_future = navigation_goal_handle.get_result_async()
            navigation_deadline = (
                time.monotonic() + self.navigation_timeout_sec
            )

            while rclpy.ok() and not result_future.done():
                if goal_handle.is_cancel_requested:
                    self._cancel_navigation(navigation_goal_handle)
                    return self._finish_canceled(
                        goal_handle,
                        'Return Home canceled during navigation',
                    )

                if time.monotonic() >= navigation_deadline:
                    self._cancel_navigation(navigation_goal_handle)
                    return self._finish_aborted(
                        goal_handle,
                        'Return Home navigation timed out',
                    )

                time.sleep(0.05)

            if not result_future.done():
                return self._finish_aborted(
                    goal_handle,
                    'ROS shutdown while waiting for return result',
                )

            wrapped_result = result_future.result()
            if wrapped_result is None:
                return self._finish_aborted(
                    goal_handle,
                    'NavigateToPose returned no result',
                )

            if wrapped_result.status != GoalStatus.STATUS_SUCCEEDED:
                return self._finish_aborted(
                    goal_handle,
                    'Return navigation failed: '
                    f'status={wrapped_result.status}',
                )

            self._publish_feedback(
                goal_handle,
                'ARRIVED',
                1.0,
                'Robot arrived at the mission start pose',
            )
            result = ReturnHome.Result()
            result.success = True
            result.message = 'Return Home completed successfully'
            goal_handle.succeed()
            return result
        except Exception as error:  # noqa: BLE001
            self.get_logger().error(f'Return Home failed: {error}')
            return self._finish_aborted(goal_handle, str(error))
        finally:
            with self.goal_lock:
                self.active_navigation_goal = None
                self.goal_reserved = False

    def _wait_for_home_pose(self, goal_handle) -> PoseStamped | None:
        """Wait a bounded time for automatic home-pose capture."""
        deadline = time.monotonic() + self.home_wait_timeout_sec
        while rclpy.ok() and time.monotonic() < deadline:
            if goal_handle.is_cancel_requested:
                return None
            with self.home_lock:
                if self.home_pose is not None:
                    return copy.deepcopy(self.home_pose)
            time.sleep(0.05)
        raise RuntimeError(
            'Home pose was not captured; check map-to-robot TF'
        )

    def _distance_to_home(self, home_pose: PoseStamped) -> float:
        """Estimate the starting distance for progress feedback."""
        try:
            transform = self.tf_buffer.lookup_transform(
                self.map_frame,
                self.robot_frame,
                Time(),
                timeout=Duration(seconds=0.5),
            )
            return math.hypot(
                home_pose.pose.position.x
                - transform.transform.translation.x,
                home_pose.pose.position.y
                - transform.transform.translation.y,
            )
        except Exception:  # noqa: BLE001
            return 0.0

    def _navigation_feedback(
        self,
        goal_handle,
        feedback_message,
        initial_distance: float,
    ) -> None:
        """Convert Nav2 distance feedback into ReturnHome progress."""
        if goal_handle.is_cancel_requested:
            return

        distance_remaining = feedback_message.feedback.distance_remaining
        if initial_distance > 0.05:
            fraction = 1.0 - distance_remaining / initial_distance
            progress = 0.20 + max(0.0, min(1.0, fraction)) * 0.75
        else:
            progress = 0.50

        self._publish_feedback(
            goal_handle,
            'NAVIGATING',
            progress,
            f'Distance remaining: {distance_remaining:.2f} m',
        )

    @staticmethod
    def _publish_feedback(
        goal_handle,
        stage: str,
        progress: float,
        message: str,
    ) -> None:
        """Publish ReturnHome action feedback."""
        feedback = ReturnHome.Feedback()
        feedback.stage = stage
        feedback.progress = float(progress)
        feedback.message = message
        goal_handle.publish_feedback(feedback)

    def _cancel_navigation(self, navigation_goal_handle) -> None:
        """Send a bounded cancellation request to the active Nav2 goal."""
        cancel_future = navigation_goal_handle.cancel_goal_async()
        deadline = time.monotonic() + 3.0
        while rclpy.ok() and not cancel_future.done():
            if time.monotonic() >= deadline:
                self.get_logger().warning(
                    'Return navigation cancellation response timed out'
                )
                return
            time.sleep(0.05)

    @staticmethod
    def _finish_canceled(
        goal_handle,
        message: str,
    ) -> ReturnHome.Result:
        """Return a canceled ReturnHome result."""
        result = ReturnHome.Result()
        result.success = False
        result.message = message
        goal_handle.canceled()
        return result

    @staticmethod
    def _finish_aborted(
        goal_handle,
        message: str,
    ) -> ReturnHome.Result:
        """Return an aborted ReturnHome result."""
        result = ReturnHome.Result()
        result.success = False
        result.message = message
        goal_handle.abort()
        return result

    def destroy_node(self) -> None:
        """Destroy action resources before the ROS node."""
        self.navigation_client.destroy()
        self.action_server.destroy()
        super().destroy_node()


def main(args=None) -> None:
    """Run the Return Home node with concurrent action callbacks."""
    rclpy.init(args=args)
    node = ReturnHomeNode()
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
