from enum import Enum

import rclpy
from rclpy.node import Node
from std_msgs.msg import String

from odi_interfaces.msg import MissionState
from odi_interfaces.msg import BehaviorEvent


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

class MissionManagerNode(Node):
    def __init__(self) -> None:
        super().__init__("mission_manager_node")

        self.current_state = MissionStatus.IDLE

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
        #-----
        self.get_logger().info("Mission Manager Node is Running.")
        self.publish_state("Odi is waitting for order.....")

    def command_callback(self, msg: String) -> None:
        command = msg.data.strip().upper()
        self.get_logger().info(f"command updated = {command}")
        if command == "START":
            self.handle_start_command()
        elif command == "STOP":
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

        self.change_status(
            MissionStatus.PREPARING,
            "Checking systems for exploring.....",
        )
        #센서 준비 과정을 지금은 타이머로만 설정해 놓음
        self.preparing_timer = self.create_timer(
            2.0,
            self.complete_preparing,
        )

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

        self.change_status(
            MissionStatus.IDLE,
            "Mission reset completed",
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

        self.get_logger().info(
            f"\n::MissionStatus updated::\n"
            f"{previous_state.value} -> {next_state.value}"
        )
        self.publish_state(detail)

    def publish_current_state(self) -> None:
        self.publish_state(
            f"Current Mission State : {self.current_state.value}"
        )

    def publish_state(self, detail:str) -> None:
        msg = MissionState()
        msg.state = self.current_state.value
        msg.detail = detail
        msg.updated_at = self.get_clock().now().to_msg()

        self.state_publisher.publish(msg)

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






