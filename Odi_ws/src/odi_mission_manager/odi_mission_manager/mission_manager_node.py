
import uuid
import time
import json
from enum import Enum

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from odi_interfaces.srv import PrepareMapping, SetHomePose

from odi_interfaces.msg import (
    MissionState,
    BehaviorEvent,
)


class MissionStatus(str, Enum):
    "오디 최상위 미션 상태"
    IDLE = "IDLE"
    PREPARING = "PREPARING"
    EXPLORING = "EXPLORING"
    RETURNING = "RETURNING"
    REFLECTING = "REFLECTING"
    COMPLETED = "COMPLETED"
    RESETTING = "RESETTING"
    ERROR = "ERROR"
    NORMAL = 'NORMAL'
    NORMAL_STOPPING = 'NORMAL_STOPPING'

class MissionManagerNode(Node):
    def __init__(self) -> None:
        super().__init__("mission_manager_node")

        self.current_state = MissionStatus.IDLE
        self.session_id = ''
        self.current_detail = 'Odi is waiting for order'
        self.state_updated_at = (
            self.get_clock().now().to_msg()
        )

        self.command_subscriber = self.create_subscription(
            String,
            "/mission/command",
            self.command_callback,
            10,
        )
        self.behavior_event_subscriber = self.create_subscription(
            BehaviorEvent,
            "/behavior/event",
            self.behavior_event_callback,
            10,
        )
        self.state_publisher = self.create_publisher(
            MissionState,
            "/mission/state",
            10,
        )
        self.state_timer = self.create_timer(
            1.0,
            self.publish_current_state,
        )

        # 준비 과정을 임시로 타이머로 대체를 위한 변수임
        self.preparing_timer = None
        self.mapping_client = self.create_client(PrepareMapping, '/odi/prepare_mapping')
        self.home_client = self.create_client(SetHomePose, '/return_home/set_home_pose')
        self.preparation_future = None
        self.preparation_phase = ''
        self.reset_acknowledged = False
        self.preparation_poll = self.create_timer(0.1, self.poll_preparation)
        self.normal_events = self.create_subscription(String, '/normal/event', self.normal_event, 10)
        #-----

        self.get_logger().info("Mission Manager Node is Running.")
        self.publish_state()


    def command_callback(self, msg: String) -> None:
        command = msg.data.strip().upper()
        self.get_logger().info(f"command updated = {command}")
        if command == 'NORMAL':
            if self.current_state == MissionStatus.IDLE:
                self.session_id = 'normal-' + str(uuid.uuid4())
                self.change_status(MissionStatus.NORMAL, 'Normal mode starting')
        elif command == "START":
            self.handle_start_command()
        elif command in ("STOP", "NORMAL_STOP"):
            self.handle_stop_command()
        elif command == "RESET":
            self.handle_reset_command()
        elif command == "PAUSE":
            self.get_logger().warning(
                "Pause command is inprogress"
            )
        elif command == "RESUME":
            self.get_logger().warning(
                "Resume command is inprogress"
            )
        else:
            self.get_logger().warning(
                f"{command} is unknown command"
            )



    def handle_start_command(self) -> None:
        if self.current_state != MissionStatus.IDLE:
            self.get_logger().warning(
                "State:Idle is required to start the exploring\n"
                f"Current State = {self.current_state.value}"
            )
            return

        self.session_id = str(uuid.uuid4())

        self.get_logger().info(
            f"\n New mission session created : {self.session_id}"
        )

        self.change_status(
            MissionStatus.PREPARING,
            "Checking systems for exploring.....",
        )
        self.preparation_phase = 'mapping'
        self.preparation_deadline = time.monotonic() + 120.0
        self.reset_acknowledged = False

    def poll_preparation(self) -> None:
        future = self.preparation_future
        if self.current_state != MissionStatus.PREPARING:
            # Keep the pending request until the supervisor has actually stopped.
            if future is not None and future.done():
                self.preparation_future = None
            if self.current_state == MissionStatus.RESETTING and self.reset_acknowledged:
                self.finish_reset_if_ready()
            return
        try:
            if time.monotonic() >= self.preparation_deadline:
                raise RuntimeError('Fresh map preparation timed out; check terminal 1')
            if future is None:
                client = self.mapping_client if self.preparation_phase == 'mapping' else self.home_client
                if not client.service_is_ready():
                    return
                if self.preparation_phase == 'mapping':
                    request = PrepareMapping.Request()
                    request.session_id = self.session_id
                else:
                    request = SetHomePose.Request()
                    request.session_id = self.session_id
                    request.pose = self.prepared_home_pose
                self.preparation_future = client.call_async(request)
                return
            if not future.done():
                return
            self.preparation_future = None
            result = future.result()
            if result is None or not result.success:
                raise RuntimeError(getattr(result, 'message', 'Preparation returned no result'))
            if self.preparation_phase == 'mapping':
                self.prepared_home_pose = result.home_pose
                self.preparation_phase = 'home'
            else:
                self.complete_preparing()
        except Exception as error:
            self.change_status(MissionStatus.ERROR, str(error))

    def complete_preparing(self) -> None:
        #준비 타이머 해제
        if self.preparing_timer is not None:
            self.preparing_timer.cancel()
            self.destroy_timer(self.preparing_timer)
            self.preparing_timer = None
        # -----
        if self.current_state != MissionStatus.PREPARING:
            return

        self.change_status(
            MissionStatus.EXPLORING,
            "Exploring start!",
        )

    def handle_stop_command(self) -> None:
        if self.current_state in (MissionStatus.NORMAL, MissionStatus.NORMAL_STOPPING):
            self.change_status(MissionStatus.NORMAL_STOPPING, 'Stopping normal mode and centering camera')
            return
        if self.current_state == MissionStatus.PREPARING:
            self.handle_reset_command()
            return
        if self.current_state not in {
            MissionStatus.PREPARING,
            MissionStatus.EXPLORING,
        }:
            self.get_logger().warning(
                "Stop command can't be treated in current state\n"
                f"Current State = {self.current_state.value}"
            )
            return
        # 준비 타이머 해제
        if self.preparing_timer is not None:
            self.preparing_timer.cancel()
            self.destroy_timer(self.preparing_timer)
            self.preparing_timer = None
        # -----

        self.change_status(
            MissionStatus.RETURNING,
            "Exploring canceled preparing for return.....",
        )

    def handle_reset_command(self) -> None:

        if self.current_state in (MissionStatus.NORMAL, MissionStatus.NORMAL_STOPPING):
            self.handle_stop_command()
            return

        if self.current_state == MissionStatus.RESETTING:
            return
        self.reset_acknowledged = False

        # 준비 타이머 해제
        if self.preparing_timer is not None:
            self.preparing_timer.cancel()
            self.destroy_timer(self.preparing_timer)
            self.preparing_timer = None
        # -----
        self.change_status(
            MissionStatus.RESETTING,
            "Reset requested",
        )

    def behavior_event_callback(
            self,
            msg: BehaviorEvent,
    ) -> None:

        event = msg.event.strip().upper()

        self.get_logger().info(
            "\n::Behavior event received::\n"
            f"event = {event}\n"
            f"detail = {msg.detail}"
        )

        if event == "EXPLORATION_FINISHED":
            self.handle_exploration_finished()
            return
        if event == "RETURN_HOME_COMPLETED":
            self.handle_return_home_completed()
            return
        if event == "REFLECTION_COMPLETED":
            self.handle_reflection_completed()
            return
        if event == "RESET_COMPLETED":
            self.handle_reset_completed()
            return

        if event == "EXPLORATION_FAILED":
            self.handle_exploration_failed(msg.detail)
            return
        if event == "REFLECTION_FAILED":
            self.handle_reflection_failed(msg.detail)
            return
        if event == "RETURN_HOME_FAILED":
            self.handle_return_home_failed(msg.detail)
            return

        self.get_logger().warning(
            f"Unknown behavior event : {event}"
        )

    def normal_event(self, message):
        try:
            event = json.loads(message.data)
        except (ValueError, TypeError):
            return
        if (event.get('session_id') != self.session_id or self.current_state not in
                (MissionStatus.NORMAL, MissionStatus.NORMAL_STOPPING)):
            return
        if event.get('event') == 'FAULT':
            self.change_status(MissionStatus.NORMAL_STOPPING, event.get('detail', 'Normal mode fault'))
        elif event.get('event') == 'STOPPED':
            self.session_id = ''
            self.change_status(MissionStatus.IDLE, event.get('detail', 'Normal mode stopped'))

    def handle_exploration_finished(self) -> None:
        if self.current_state != MissionStatus.EXPLORING:
            self.get_logger().warning(
                "\nEXPLORATION_FINISHED\n"
                f"Current state = {self.current_state.value}"
            )
            return
        self.change_status(
            MissionStatus.RETURNING,
            "\nExploration completed. Returning home.",
        )

    def handle_return_home_completed(self) -> None:
        if self.current_state != MissionStatus.RETURNING:
            self.get_logger().warning(
                "\nRETURN_HOME_COMPLETED\n"
                f"Current State = {self.current_state.value}"
            )
            return
        self.change_status(
            MissionStatus.REFLECTING,
            "\nReturned home. Starting reflecting",
        )
    def handle_reflection_completed(self) -> None:
        if self.current_state != MissionStatus.REFLECTING:
            self.get_logger().warning(
                "\nREFLECTION_COMPLETED\n"
                f"Current State = {self.current_state.value}"
            )
            return
        self.change_status(
            MissionStatus.COMPLETED,
            "Exploration diary completed",
        )

    def handle_reset_completed(self) -> None:
        if self.current_state != MissionStatus.RESETTING:
            self.get_logger().warning(
                "\nRESET_COMPLETED\n"
                f"Current state = {self.current_state.value}"
            )
            return

        self.reset_acknowledged = True
        self.finish_reset_if_ready()

    def finish_reset_if_ready(self) -> None:
        if self.preparation_future is not None:
            return
        completed_session_id = self.session_id
        self.session_id = ''

        self.change_status(
            MissionStatus.IDLE,
            "Mission reset completed",
        )
        self.get_logger().info(
            f"\n Mission session cleard : {completed_session_id}"
        )


#실패처리 구간
    def handle_exploration_failed(
            self,
            detail: str,
    ) -> None:
        if self.current_state != MissionStatus.EXPLORING:
            self.get_logger().warning(
                "\nEXPLORATION_FAILED\n"
                f"Current state = {self.current_state.value}"
            )
            return

        self.change_status(
            MissionStatus.ERROR,
            f"Exploration failed {detail}",
        )

    def handle_return_home_failed(
            self,
            detail: str,
    ) -> None:
        if self.current_state != MissionStatus.RETURNING:
            return
        self.change_status(
            MissionStatus.ERROR,
            f"Return home failed : {detail}",
        )

    def handle_reflection_failed(
            self,
            detail: str,
    ) -> None:
        if self.current_state != MissionStatus.REFLECTING:
            return
        self.change_status(
            MissionStatus.ERROR,
            f"Reflection failed : {detail}",
        )

    def change_status(
            self,
            next_state : MissionStatus,
            detail : str,
    ) -> None:

        previous_state = self.current_state

        self.current_state = next_state
        self.current_detail = detail
        self.state_updated_at = self.get_clock().now().to_msg()

        self.get_logger().info(
            f"\n :: MissionStatus updated :: "
            f"\n {previous_state.value} -> {next_state.value}"
        )

        self.publish_state()


    def publish_current_state(self) -> None:
        self.publish_state()

    def publish_state(self) -> None:
        message = MissionState()

        message.session_id = self.session_id
        message.state = self.current_state.value
        message.detail = self.current_detail
        message.updated_at = self.state_updated_at

        self.state_publisher.publish(message)

def main(args = None) -> None:
    rclpy.init(args=args)
    node = MissionManagerNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info(
            "Mission Manager Node terminated"
        )
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()




