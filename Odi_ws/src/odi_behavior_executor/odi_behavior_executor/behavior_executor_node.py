
from enum import Enum

import rclpy
from rclpy.node import Node

from odi_interfaces.msg import BehaviorState
from odi_interfaces.msg import MissionState

from odi_behavior_executor.blackboard import OdiBlackboard

class BehaviorName(str, Enum):

    NONE = "NONE"
    PREPARE = "PREPARE"
    EXPLORE = "EXPLORE"
    EVALUATE_CURIOSITY = "EVALUATE_CURIOSITY"
    OBSERVE = "OBSERVE"
    RETURN_HOME = "RETURN_HOME"
    REFLECT = "REFLECT"
    EMERGENCY_STOP = "EMERGENCY_STOP"

class BehaviorStatus(str, Enum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"
    CANCELED = "CANCELED"

class BehaviorExecutorNode(Node):
    def __init__(self) -> None:
        super().__init__("behavior_executor_node")
        self.blackboard = OdiBlackboard()
        self.current_behavior = BehaviorName.NONE
        self.current_status = BehaviorStatus.IDLE
        self.current_detail = "Waiting for misstion"
        self.mission_state_subscriber = self.create_subscription(
            MissionState,
            "/mission/state",
            self.mission_state_callback,
            10,
        )
        self.behavoir_state_publisher = self.create_publisher(
            BehaviorState,
            "/behavior/state",
            10,
        )
        self.selector_timer = self.create_timer(
            0.5,
            self.run_selector,
        )
        self.state_timer = self.create_timer(
            1.0,
            self.publish_current_behavior,
        )

    def mission_state_callback(
        self,
        msg:MissionState,
    ) -> None:
        # mission manager 의 상태를 blackboard에 저장한다.
        previous_state = self.blackboard.mission_state
        self.blackboard.mission_state = msg.state

        if previous_state == msg.state:
            return

        self.get_logger().info(
            "::Mission state updated::\n"
            f"{previous_state} -> {msg.state}"
        )

        if msg.state == "IDLE":
            self.blackboard.reset_runtime_state()

    def run_selector(self) -> None:
        # 우선순위 1 : 비상 상황
        if self.blackboard.emergency:
            self.set_behavior(
                BehaviorName.EMERGENCY_STOP,
                BehaviorStatus.RUNNING,
                "Emergency detected"
            )
            return
        # 우선순위 2 : 배터리 부족 또는 복귀 요청
        if(self.blackboard.battery_low
           or self.blackboard.return_requested
           or self.blackboard.mission_state == "RETURNING"):
            self.set_behavior(
                BehaviorName.RETURN_HOME,
                BehaviorStatus.RUNNING,
                "Returning to the home position"
            )
            return
        # 우선순위 3 : 진행 중인 관찰
        if self.blackboard.Observation_active:
            self.set_behavior(
                BehaviorName.OBSERVE,
                BehaviorStatus.RUNNING,
                "Observing the selected object"
            )
            return
        # 우선순위 4 : 호기심 판단이 완료된 물체 후보
        if(self.blackboard.has_candidate()
           and self.blackboard.has_curiosity_decision()):
            decision = self.blackboard.curiosity_decision
            if decision.action != "IGNORE":
                self.set_behavior(
                    BehaviorName.OBSERVE,
                    BehaviorStatus.RUNNING,
                    "Interesting object selected for observation"
                )
                return
            self.blackboard.clear_candidate()
        #우선순위 5 : 판단하지 않은 새 물체 후보
        if self.blackboard.has_candidate():
            self.set_behavior(
                BehaviorName.EVALUATE_CURIOSITY,
                BehaviorStatus.RUNNING,
                "Evaluating curiosity for a new object",
            )
            return
        #미션 준비
        if self.blackboard.mission_state == "PREPARING":
            self.set_behavior(
                BehaviorName.PREPARE,
                BehaviorStatus.RUNNING,
                "Preparing robot system",
            )
            return
        #일반 탐험
        if self.blackboard.mission_state == "EXPLORING":
            self.set_behavior(
                BehaviorName.EXPLORE,
                BehaviorStatus.RUNNING,
                "Exploring an univerited area"
            )
            return
        #탐험 기록 정리
        if self.blackboard.mission_state == "REFLECTING":
            self.set_behavior(
                BehaviorName.REFLECT,
                BehaviorStatus.RUNNING,
                "Generating an exploration diary",
            )
            return
        #미션 완료
        if self.blackboard.mission_state == "COMPLETED":
            self.set_behavior(
                BehaviorName.NONE,
                BehaviorStatus.SUCCESS,
                "Mission completed",
            )
            return

        self.set_behavior(
            BehaviorName.NONE,
            BehaviorStatus.IDLE,
            "Waiting for mission",
            )

    def set_behavior(
            self,
            behavior: BehaviorName,
            status: BehaviorStatus,
            detail: str,
    ) -> None:
        if(behavior == self.current_behavior
           and status == self.current_status
           and detail == self.current_detail):
            return
        previous_behavior = self.current_behavior

        self.current_behavior = behavior
        self.current_status = status
        self.current_detail = detail

        self.get_logger().info(
            "::Behavior changed::"
            f"{previous_behavior.value} -> {behavior.value}"
        )
        self.publish_current_behavior()

    def publish_current_behavior(self) -> None:
        msg = BehaviorState()
        msg.behavior = self.current_behavior.value
        msg.status = self.current_status.value
        msg.detail = self.current_detail
        msg.updated_at = self.get_clock().now().to_msg()

        self.behavoir_state_publisher.publish(msg)

def main(args=None) -> None:
    rclpy.init(args=args)
    node = BehaviorExecutorNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info(
            "Behavior Executor node is terminated"
        )
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()




