
from enum import Enum

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient

from odi_interfaces.msg import BehaviorState
from odi_interfaces.msg import MissionState
from odi_interfaces.msg import DetectedObjectArray
from odi_interfaces.action import FirstEncounter


from odi_behavior_executor.blackboard import(
    ObjectProcessStage,
    OdiBlackboard,
)

class BehaviorName(str, Enum):
    NONE = "NONE"
    PREPARE = "PREPARE"
    EXPLORE = "EXPLORE"
    FIRST_ENCOUNTER = "FIRST_ENCOUNTER"
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

        self.first_encounter_action_client = ActionClient(
            self,
            FirstEncounter,
            "/first_encounter",
        )
        self.first_encounter_goal_active = False
        self.first_encounter_goal_handle = None

        self.current_behavior = BehaviorName.NONE
        self.current_status = BehaviorStatus.IDLE
        self.current_detail = "Waiting for misstion"

        # mission manager의 미션 상태 구독
        self.mission_state_subscriber = self.create_subscription(
            MissionState,
            "/mission/state",
            self.mission_state_callback,
            10,
        )

        # 탐지 물체 배열 구독
        self.detected_objects_subscriber = self.create_subscription(
            DetectedObjectArray,
            "/perception/detected_objects",
            self.detected_objects_callback,
            10,
        )
        #현재 행동 상태 발행
        self.behavoir_state_publisher = self.create_publisher(
            BehaviorState,
            "/behavior/state",
            10,
        )
        #최상위 셀렉터 실행
        self.selector_timer = self.create_timer(
            0.2,
            self.run_selector,
        )
        #현재 행동 상태 주기적으로 발행
        self.state_publish_timer = self.create_timer(
            1.0,
            self.publish_current_behavior,
        )

        self.get_logger().info(
            "Behavior executor node is running"
        )
        self.publish_current_behavior()

    def mission_state_callback(
        self,
        msg:MissionState,
    ) -> None:
        # mission manager 의 상태를 blackboard에 저장한다.
        previous_state = self.blackboard.mission_state
        self.blackboard.mission_state = msg.state

        if previous_state == msg.state:
            return

        if msg.state == "IDLE":
            self.blackboard.reset()

    def detected_objects_callback(
            self,
            msg: DetectedObjectArray,
    ) -> None:
        if self.blackboard.mission_state != "EXPLORING":
            return
        if self.blackboard.detection_locked:
            return
        if not msg.objects:
            return
        valid_objects = [
            detected_object
            for detected_object in msg.objects
            if detected_object.confidence >= 0.5
        ]
        if not valid_objects:
            self.get_logger().info(
                "No valid detected objects"
            )
            return
        valid_objects.sort(
            key=lambda detected_object:
                abs(detected_object.center_x),
        )
        self.blackboard.detection_locked = True
        self.blackboard.exploration_paused = True

        self.blackboard.pending_objects.extend(
            valid_objects
        )
        self.get_logger().info(
            "::Detected object batch received::\n"
            f"{len(valid_objects)} object"
        )

        for detected_object in valid_objects:
            self.get_logger().info(
                "::Queued detected object::\n"
                f"id = {detected_object.detection_id}\n"
                f"class = {detected_object.class_name}\n"
                f"confidence = {detected_object.confidence:.2f}"
            )
        self.select_next_object()

    def select_next_object(self) -> bool:
        self.get_logger().info(
            "::select_next_object called::\n"
            f"current_object={self.blackboard.current_object}\n"
            f"pending_count={len(self.blackboard.pending_objects)}"
        )
        if self.blackboard.current_object is not None:
            self.get_logger().warning(
                "Can not select next object :"
                "current_object already exists"
            )
            return False
        if not self.blackboard.pending_objects:
            self.get_logger().warning(
                "Can not select next object : "
                "pending_objects is empty"
            )
            return False

        self.blackboard.current_object = (
            self.blackboard.pending_objects.pop(0)
        )
        self.blackboard.current_stage = (
            ObjectProcessStage.DETECTED
        )
        self.blackboard.encounter_result = None
        self.blackboard.curiosity_decision = None
        self.blackboard.observation_result = None

        current_object = self.blackboard.current_object

        self.get_logger().info(
            "::Next object selected::\n"
            f"id = {current_object.detection_id}\n"
            f"class = {current_object.class_name}"
        )

        return True

    def complete_current_object(self) -> None:
        current_object = self.blackboard.current_object
        if current_object is not None:
            self.get_logger().info(
                f"Object processing completed : {current_object.detection_id}"
            )
        self.blackboard.current_object = None
        self.blackboard.current_stage = (
            ObjectProcessStage.NONE
        )
        self.blackboard.encounter_result = None
        self.blackboard.curiosity_decision = None
        self.blackboard.observation_result = None

        if self.blackboard.pending_objects:
            self.select_next_object()
            return

        self.finish_detection_batch()

    def finish_detection_batch(self) -> None:
        self.blackboard.detection_locked = False
        self.blackboard.exploration_paused = False
        self.get_logger().info(
            "All detected objects processed\n"
            "Exploration will resume"
        )

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
        # 우선순위 3 : 현재 처리 중인 물체
        if self.blackboard.current_object is not None:
            self.select_object_behavior()
            return
        #대기중인 물체가 있는데 현재 물체가 없다면 다음 물체 선택
        if self.blackboard.pending_objects:
            self.select_next_object()
            return

        #미션 준비
        if self.blackboard.mission_state == "PREPARING":
            self.set_behavior(
                BehaviorName.PREPARE,
                BehaviorStatus.RUNNING,
                "Preparing robot system",
            )
            return

        #탐험
        if self.blackboard.mission_state == "EXPLORING":
            self.set_behavior(
                BehaviorName.EXPLORE,
                BehaviorStatus.RUNNING,
                "Exploring an unknown area"
            )
            return

        #일기 생성
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
    def select_object_behavior(self) -> None:
        stage = self.blackboard.current_stage
        if stage == ObjectProcessStage.DETECTED:
            self.start_first_encounter()
            return

        if stage == ObjectProcessStage.ENCOUNTERING:
            self.set_behavior(
                BehaviorName.FIRST_ENCOUNTER,
                BehaviorStatus.RUNNING,
                "First encounter is in progress",
            )
            return

        if stage == ObjectProcessStage.ENCOUNTER_COMPLETED:
            self.set_behavior(
                BehaviorName.EVALUATE_CURIOSITY,
                BehaviorStatus.RUNNING,
                "Evaluating curiosity from encounter result",
            )
            return

        if stage == ObjectProcessStage.EVALUATING_CURIOSITY:
            self.set_behavior(
                BehaviorName.EVALUATE_CURIOSITY,
                BehaviorStatus.RUNNING,
                "Curiosity evaluation is in progress",
            )
            return

        if stage == ObjectProcessStage.CURIOSITY_EVALUATED:
            self.handle_curiosity_decision()
            return

        if stage == ObjectProcessStage.OBSERVING:
            self.set_behavior(
                BehaviorName.OBSERVE,
                BehaviorStatus.RUNNING,
                "Detailed observation is in progress"
            )
            return

        if stage == ObjectProcessStage.OBSERVATION_COMPLETED:
            self.complete_current_object()
            return

        if stage == ObjectProcessStage.IGNORED:
            self.complete_current_object()
            return

        if stage == ObjectProcessStage.FINISHED:
            self.complete_current_object()
            return

        if stage == ObjectProcessStage.FAILED:
            self.set_behavior(
                BehaviorName.NONE,
                BehaviorStatus.FAILURE,
                "Object processing failed",
            )
            self.complete_current_object()
            return
        self.set_behavior(
            BehaviorName.NONE,
            BehaviorStatus.IDLE,
            "No object behavior selected",
        )

    def start_first_encounter(self) -> None:
        # encounter 액션 실행 함수
        if self.first_encounter_goal_active:
            return

        current_object = self.blackboard.current_object

        if current_object is None:
            self.get_logger().warning(
                "Can not start first_encounter : current object is missing"
            )
            self.blackboard.current_stage = (
                ObjectProcessStage.FAILED
            )
            return

        if not self.first_encounter_action_client.server_is_ready():
            self.get_logger().warning(
                "First Encounter action server is not ready"
            )
            self.set_behavior(
                BehaviorName.FIRST_ENCOUNTER,
                BehaviorStatus.IDLE,
                "Waiting for First Encounter action server",
            )
            return

        goal_msg = FirstEncounter.Goal()
        goal_msg.target = current_object

        self.first_encounter_goal_active = True
        self.blackboard.current_stage = (
            ObjectProcessStage.ENCOUNTERING
        )
        self.set_behavior(
            BehaviorName.FIRST_ENCOUNTER,
            BehaviorStatus.RUNNING,
            "First encounter goal requested",
        )
        self.get_logger().info(
            "::First encounter goal requested::\n"
            f"id = {current_object.detection_id}\n"
            f"class = {current_object.class_name}"
        )
        send_goal_future = (
            self.first_encounter_action_client.send_goal_async(
                goal_msg,
                feedback_callback=(
                    self.first_encounter_feedback_callback
                ),
            )
        )
        send_goal_future.add_done_callback(
            self.first_encounter_goal_response_callback
        )

    def first_encounter_goal_response_callback(self, future,) -> None:
        try:
            goal_handle = future.result()
        except Exception as error:
            self.get_logger().error(
                f"Failed to send First Encounter goal : {error}"
            )
            self.first_encounter_goal_active = False
            self.blackboard.current_stage = (
                ObjectProcessStage.FAILED
            )
            return

        if not goal_handle.accepted:
            self.get_logger().warning(
                "First Encounter goal was rejected"
            )
            self.first_encounter_goal_active = False
            self.blackboard.current_stage = (
                ObjectProcessStage.FAILED
            )
            return

        self.first_encounter_goal_handle = goal_handle
        self.get_logger().info(
            "First Encounter goal was accepted"
        )
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(
            self.first_encounter_result_callback
        )

    def first_encounter_feedback_callback(
            self,
            feedback_msg,
    ) -> None:
        # First Encounter의 중간 진행 상황을 처리한다.
        feedback = feedback_msg.feedback
        self.current_datail = (
            f"{feedback.stage} : {feedback.message} ({feedback.progress * 100.0:.0f}%)"
        )
        self.get_logger().info(
            "::First encounter feedback::\n"
            f"stage = {feedback.stage}\n"
            f"progress = {feedback.progress: .2f}\n"
            f"message = {feedback.message}"
        )

    def first_encounter_result_callback(
            self,
            future,
    ) -> None:
        # First Encounter의 최종 결과를  처리한다.
        self.first_encounter_goal_active = False
        self.first_encounter_goal_handle = None
        try:
            wrapped_result = future.result()
            encounter_result = wrapped_result.result.result
        except Exception as error:
            self.get_logger().error(
                f"Failed to receive first encounter result : {error}"
            )
            self.blackboard.current_stage = (
                ObjectProcessStage.FAILED
            )
            return
        self.blackboard.encounter_result = encounter_result

        if not encounter_result.success:
            self.get_logger().warning(
                "::First encounter failed::\n"
                f"detection_id = {encounter_result.detection_id}\n"
                f"reason = {encounter_result.failure_reason}"
            )
            self.blackboard.current_stage = (
                ObjectProcessStage.FAILED
            )
            return

        self.get_logger().info(
            "::First encounter completed::\n"
            f"detection_id = {encounter_result.detection_id}\n"
            f"image_path = {encounter_result.image_path}\n"
            f"object_name = {encounter_result.label.object_name}"
        )
        self.blackboard.current_stage = (
            ObjectProcessStage.ENCOUNTER_COMPLETED
        )

    def handle_curiosity_decision(self) -> None:
        decision = self.blackboard.curiosity_decision

        if decision is None:
            self.get_logger().warning(
                "Curiosity stage completed but decision is missing"
            )
            self.blackboard.current_stage = (
                ObjectProcessStage.FAILED
            )
            return

        if decision.action == "OBSERVE":
            self.blackboard.current_stage = (
                ObjectProcessStage.OBSERVING
            )
            self.set_behavior(
                BehaviorName.OBSERVE,
                BehaviorStatus.RUNNING,
                "Object selected for detailed observation",
            )
            return

        if decision.action == "IGNORE":
            self.blackboard.current_stage = (
                ObjectProcessStage.IGNORED
            )
            self.set_behavior(
                BehaviorName.NONE,
                BehaviorStatus.SUCCESS,
                "Object does not require detailed observation",
            )
            return
        self.get_logger().warning(
            f"Unknown curiosity action : {decision.action}"
        )
        self.blackboard.current_stage = (
            ObjectProcessStage.FAILED
        )

#행동 변동시 변경하고 바로 발행
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
            "::Behavior changed::\n"
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



