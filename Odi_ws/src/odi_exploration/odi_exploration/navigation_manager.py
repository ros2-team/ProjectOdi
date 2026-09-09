"""Synchronous control wrapper around the Nav2 NavigateToPose action."""

import threading
import time

from enum import Enum
from typing import Callable

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient


class NavigationOutcome(str, Enum):
    """Possible outcomes of one navigation request."""

    SUCCEEDED = 'SUCCEEDED'
    CANCELED = 'CANCELED'
    REJECTED = 'REJECTED'
    FAILED = 'FAILED'
    TIMEOUT = 'TIMEOUT'
    ERROR = 'ERROR'


class NavigationManager:
    """Send navigation goals and coordinate timeout and cancellation."""

    def __init__(
        self,
        node,
        callback_group,
        action_name: str = '/navigate_to_pose',
        server_timeout_sec: float = 5.0,
        navigation_timeout_sec: float = 120.0,
    ) -> None:
        self.node = node
        self.server_timeout_sec = server_timeout_sec
        self.navigation_timeout_sec = navigation_timeout_sec

        self._goal_lock = threading.Lock()
        self._active_goal_handle = None

        self.client = ActionClient(
            node,
            NavigateToPose,
            action_name,
            callback_group=callback_group,
        )

    def navigate(
        self,
        pose: PoseStamped,
        cancel_requested: Callable[[], bool],
        strict: bool = False,
    ) -> tuple[NavigationOutcome, str]:
        """Navigate to a pose while observing an external cancel request."""
        if strict:
            return self._navigate_strict(pose, cancel_requested)
        if not self.client.wait_for_server(
            timeout_sec=self.server_timeout_sec,
        ):
            return (
                NavigationOutcome.ERROR,
                'NavigateToPose action server is unavailable',
            )

        goal = NavigateToPose.Goal()
        goal.pose = pose
        goal.pose.header.stamp = self.node.get_clock().now().to_msg()

        send_future = self.client.send_goal_async(goal)
        send_deadline = time.monotonic() + self.server_timeout_sec

        while rclpy.ok() and not send_future.done():
            if time.monotonic() >= send_deadline:
                return (
                    NavigationOutcome.ERROR,
                    'NavigateToPose goal response timed out',
                )
            time.sleep(0.05)

        if not send_future.done():
            return (
                NavigationOutcome.ERROR,
                'ROS shutdown while sending navigation goal',
            )

        try:
            goal_handle = send_future.result()
        except Exception as error:  # noqa: BLE001
            return (
                NavigationOutcome.ERROR,
                f'Failed to send NavigateToPose goal: {error}',
            )

        if goal_handle is None or not goal_handle.accepted:
            return (
                NavigationOutcome.REJECTED,
                'NavigateToPose goal was rejected',
            )

        with self._goal_lock:
            self._active_goal_handle = goal_handle

        try:
            if cancel_requested():
                self._cancel_goal(goal_handle)
                return (
                    NavigationOutcome.CANCELED,
                    'Navigation canceled before movement',
                )

            result_future = goal_handle.get_result_async()
            deadline = time.monotonic() + self.navigation_timeout_sec

            while rclpy.ok() and not result_future.done():
                if cancel_requested():
                    self._cancel_goal(goal_handle)
                    return (
                        NavigationOutcome.CANCELED,
                        'Navigation canceled during movement',
                    )

                if time.monotonic() >= deadline:
                    self._cancel_goal(goal_handle)
                    return (
                        NavigationOutcome.TIMEOUT,
                        'NavigateToPose navigation timed out',
                    )

                time.sleep(0.05)

            if not result_future.done():
                return (
                    NavigationOutcome.ERROR,
                    'ROS shutdown while waiting for navigation result',
                )

            wrapped_result = result_future.result()
            if wrapped_result is None:
                return (
                    NavigationOutcome.ERROR,
                    'NavigateToPose returned no result',
                )

            if wrapped_result.status == GoalStatus.STATUS_SUCCEEDED:
                return (
                    NavigationOutcome.SUCCEEDED,
                    'Navigation completed successfully',
                )

            if wrapped_result.status == GoalStatus.STATUS_CANCELED:
                return (
                    NavigationOutcome.CANCELED,
                    'Navigation was canceled',
                )

            return (
                NavigationOutcome.FAILED,
                f'NavigateToPose failed: status={wrapped_result.status}',
            )
        except Exception as error:  # noqa: BLE001
            return (
                NavigationOutcome.ERROR,
                f'Navigation processing failed: {error}',
            )
        finally:
            with self._goal_lock:
                if self._active_goal_handle is goal_handle:
                    self._active_goal_handle = None

    def _navigate_strict(self, pose, cancel_requested):
        """Normal mode retains ownership through late acceptance and terminal result.

        A lost response intentionally blocks completion rather than allowing head
        motion or another mission while an unconfirmed navigation goal exists.
        """
        if not self.client.wait_for_server(timeout_sec=self.server_timeout_sec):
            return NavigationOutcome.ERROR, 'Nav2 unavailable'
        if cancel_requested():
            return NavigationOutcome.CANCELED, 'Canceled before sending navigation'
        goal = NavigateToPose.Goal()
        goal.pose = pose
        goal.pose.header.stamp = self.node.get_clock().now().to_msg()
        sent = self.client.send_goal_async(goal)
        limit = time.monotonic()+self.server_timeout_sec
        stopping = False
        while rclpy.ok() and not sent.done():
            if time.monotonic() > limit or cancel_requested():
                if not stopping:
                    self.node.get_logger().warning('Waiting for late Nav2 acceptance before canceling')
                stopping = True
            time.sleep(.05)
        if not sent.done():
            return NavigationOutcome.ERROR, 'Shutdown before Nav2 response'
        handle = sent.result()
        if handle is None or not handle.accepted:
            return NavigationOutcome.REJECTED, 'Nav2 rejected short movement'
        with self._goal_lock:
            self._active_goal_handle = handle
        result = handle.get_result_async()
        deadline = time.monotonic()+self.navigation_timeout_sec
        cancel = None
        cancel_at = float('-inf')
        while rclpy.ok():
            stopping = stopping or cancel_requested() or time.monotonic() > deadline
            if result.done():
                try:
                    wrapped = result.result()
                    if wrapped is not None and wrapped.status in (4, 5, 6):
                        with self._goal_lock:
                            self._active_goal_handle = None
                        if stopping or wrapped.status == 5:
                            return NavigationOutcome.CANCELED, 'Nav2 reached terminal state after cancel'
                        if wrapped.status == 4:
                            return NavigationOutcome.SUCCEEDED, 'Short movement completed'
                        return NavigationOutcome.FAILED, 'Short movement aborted by Nav2'
                except Exception as error:
                    self.node.get_logger().error('Waiting for Nav2 terminal confirmation: '+str(error))
                stopping = True
                result = handle.get_result_async()
            if stopping and time.monotonic()-cancel_at > 1 and (cancel is None or cancel.done()):
                try:
                    cancel = handle.cancel_goal_async()
                except Exception as error:
                    self.node.get_logger().warning('Retrying Nav2 cancellation: '+str(error))
                cancel_at = time.monotonic()
            time.sleep(.05)
        handle.cancel_goal_async()
        return NavigationOutcome.ERROR, 'Shutdown while waiting for Nav2 termination'

    def cancel_active_goal(self) -> None:
        """Request cancellation of the currently active Nav2 goal."""
        with self._goal_lock:
            goal_handle = self._active_goal_handle

        if goal_handle is not None:
            self._cancel_goal(goal_handle)

    def _cancel_goal(self, goal_handle) -> None:
        """Send a bounded asynchronous cancellation request to Nav2."""
        try:
            cancel_future = goal_handle.cancel_goal_async()
        except Exception as error:  # noqa: BLE001
            self.node.get_logger().warning(
                f'Failed to request navigation cancellation: {error}'
            )
            return

        deadline = time.monotonic() + 3.0
        while rclpy.ok() and not cancel_future.done():
            if time.monotonic() >= deadline:
                self.node.get_logger().warning(
                    'Navigation cancellation response timed out'
                )
                return
            time.sleep(0.05)

    def destroy(self) -> None:
        """Destroy the underlying action client."""
        self.client.destroy()
