
from enum import Enum

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from action_msgs.msg import GoalStatus

from odi_interfaces.msg import BehaviorState
from odi_interfaces.msg import MissionState
from odi_interfaces.msg import DetectedObjectArray
from odi_interfaces.msg import BehaviorEvent

from odi_interfaces.srv import EvaluateCuriosity

from odi_interfaces.action import Explore
from odi_interfaces.action import FirstEncounter
from odi_interfaces.action import ObserveObject
from odi_interfaces.action import ReturnHome
from odi_interfaces.action import Reflect



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

        self.current_behavior = BehaviorName.NONE
        self.current_status = BehaviorStatus.IDLE
        self.current_detail = "Waiting for mission"

        # 탐험 액션 클라이언트
        self.exploration_action_client = ActionClient(
            self,
            Explore,
            "/explore",
        )
        self.exploration_goal_active = False
        self.exploration_goal_handle = None
        self.exploration_cancel_requested = False
        self.exploration_mode = "FRONTIER"

        #인카운터 액션 클라이언트
        self.first_encounter_action_client = ActionClient(
            self,
            FirstEncounter,
            "/first_encounter",
        )
        self.first_encounter_goal_active = False
        self.first_encounter_goal_handle = None
        self.first_encounter_cancel_requested = False

        #귀가 액션 클라이언트
        self.return_home_action_client = ActionClient(
            self,
            ReturnHome,
            "/return_home",
        )
        self.return_home_goal_active = False
        self.return_home_goal_handle = None
        self.return_home_prepared = False


        #호기심 판단 서비스 서버
        self.curiosity_client = self.create_client(
            EvaluateCuriosity,
            "/evaluate_curiosity",
        )
        self.curiosity_request_active = False

        #관찰 액션 클라이언트
        self.observation_action_client = ActionClient(
            self,
            ObserveObject,
            "/observe_object",
        )
        self.observation_goal_active = False
        self.observation_goal_handle = None
        self.observation_cancel_requested = False

        #반영 액션 클라이언트
        self.reflection_action_client = ActionClient(
            self,
            Reflect,
            "/reflect",
        )
        self.reflection_goal_active = False
        self.reflection_goal_handle = None

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
        self.behavior_state_publisher = self.create_publisher(
            BehaviorState,
            "/behavior/state",
            10,
        )
        #이벤트 결과 발행
        self.behavior_event_publisher = self.create_publisher(
            BehaviorEvent,
            "/behavior/event",
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
            self.exploration_mode = "FRONTIER"
            self.return_home_prepared = False

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

        self.pause_exploration()

        self.blackboard.pending_objects.extend(
            valid_objects
        )
        self.get_logger().info(
            "\n::Detected object batch received::\n"
            f"{len(valid_objects)} object"
        )

        for detected_object in valid_objects:
            self.get_logger().info(
                "\n::Queued detected object::\n"
                f"id = {detected_object.detection_id}\n"
                f"class = {detected_object.class_name}\n"
                f"confidence = {detected_object.confidence:.2f}"
            )
        self.select_next_object()

    def select_next_object(self) -> bool:
        self.get_logger().info(
            "\n::select_next_object called::\n"
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
            "\n::Next object selected::\n"
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
        if(
            self.blackboard.battery_low
            or self.blackboard.return_requested
            or self.blackboard.mission_state == "RETURNING"
        ):
            if not self.return_home_prepared:
                self.return_home_preparation()
                return

            self.set_behavior(
                BehaviorName.RETURN_HOME,
                BehaviorStatus.RUNNING,
                "Returning to the home position"
            )

            self.start_return_home()
            return

        # 우선순위 3 : 탐험 종료 조건
        if (
            self.blackboard.mission_state == "EXPLORING"
            and not self.blackboard.exploration_finished_requested
            and self.exploration_is_finished()
        ):
            self.finish_exploration()
            return

        # 현재 처리 중인 물체
        if self.blackboard.current_object is not None:
            self.object_behavior_selector()
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
            if self.blackboard.exploration_finished_requested:
                return

            self.set_behavior(
                BehaviorName.EXPLORE,
                BehaviorStatus.RUNNING,
                "Exploring an unknown area"
            )

            self.start_exploration()
            return

        #일기 생성
        if self.blackboard.mission_state == "REFLECTING":
            self.set_behavior(
                BehaviorName.REFLECT,
                BehaviorStatus.RUNNING,
                "Generating an exploration diary",
            )
            self.start_reflection()
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

    def object_behavior_selector(self) -> None:
        stage = self.blackboard.current_stage

        if stage == ObjectProcessStage.DETECTED:
            self.set_behavior(
                BehaviorName.FIRST_ENCOUNTER,
                BehaviorStatus.RUNNING,
                "First encounter start!"
            )
            self.start_first_encounter()
            return

        if stage == ObjectProcessStage.ENCOUNTERING:

            return

        if stage == ObjectProcessStage.ENCOUNTER_COMPLETED:
            self.set_behavior(
                BehaviorName.EVALUATE_CURIOSITY,
                BehaviorStatus.RUNNING,
                "Evaluate curiosity start!"
            )
            self.start_curiosity_evaluation()
            return

        if stage == ObjectProcessStage.EVALUATING_CURIOSITY:

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
            self.start_observation()
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

    def start_exploration(self) -> None:
        if self.exploration_goal_active:
            return
        if self.blackboard.exploration_paused:
            return
        if not self.exploration_action_client.server_is_ready():
            self.get_logger().warning(
                "Exploration action server is not ready"
            )
            return

        goal_msg = Explore.Goal()
        goal_msg.session_id = "odi_exploration"
        goal_msg.mode = self.exploration_mode

        self.exploration_goal_active = True
        self.blackboard.exploration_active = True

        self.get_logger().info(
            "\n::Explore goal requested\n"
            f"session_id = {goal_msg.session_id}\n"
            f"mode = {goal_msg.mode}"
        )

        if self.blackboard.exploration_started_at is None:
            self.blackboard.exploration_started_at = (
                self.get_clock().now().nanoseconds / 1e9
            )

        send_goal_future = (
            self.exploration_action_client.send_goal_async(
                goal_msg,
                feedback_callback=(
                    self.exploration_feedback_callback
                ),
            )
        )

        send_goal_future.add_done_callback(
            self.exploration_goal_response_callback
        )

    def exploration_goal_response_callback(
            self,
            future,
    ) -> None:
        try:
            goal_handle = future.result()
        except Exception as error:
            self.get_logger().error(
                f"Failed to send Explore goal : {error}"
            )
            self.exploration_goal_active = False
            self.blackboard.exploration_active = False
            return

        if not goal_handle.accepted:
            self.get_logger().warning(
                "Explore goal was rejected"
            )
            self.exploration_goal_active = False
            self.blackboard.exploration_active = False
            return

        self.exploration_goal_handle = goal_handle

        self.get_logger().info(
            "Explore goal was accepted"
        )

        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(
            self.exploration_result_callback
        )
        if self.blackboard.exploration_paused:
            self.pause_exploration()

    def exploration_feedback_callback(
            self,
            feedback_msg,
    ) -> None:

        feedback = feedback_msg.feedback
        self.current_detail = (
            f"\n::Exploring area : {feedback.current_area_id}"
            f"( {feedback.progress * 100.0:.0f}% )"
        )
        self.get_logger().info(
            "\n::Explore feedback::\n"
            f"area = {feedback.current_area_id}\n"
            f"progress = {feedback.progress:.2f}"
        )

    def exploration_result_callback(
            self,
            future,
    ) -> None:

        self.exploration_goal_active = False
        self.exploration_goal_handle = None
        self.exploration_cancel_requested = False
        self.blackboard.exploration_active = False

        try:
            wrapped_result = future.result()
            explore_result = wrapped_result.result

        except Exception as error:
            self.get_logger().error(
                f"Failed to receive Explore result : {error}"
            )
            return

        if wrapped_result.status == GoalStatus.STATUS_CANCELED:
            self.get_logger().info(
                "\n::Explore canceled::\n"
                f"message = {explore_result.message}"
            )
            self.blackboard.exploration_completed = False
            return

        if wrapped_result.status == GoalStatus.STATUS_SUCCEEDED:
            if explore_result.status == "FRONTIER_EXHAUSTED":
                self.get_logger().info(
                    "\n::Frontier exploration exhausted::\n"
                    f"motivation = {self.blackboard.motivation}"
                )
                self.blackboard.exploration_completed = False

                if not self.exploration_is_finished():
                    self.exploration_mode = "ROAM"
                    self.get_logger().info(
                        "Exploration mode changed : FRONTIER -> ROAM"
                    )
                    return

                self.finish_exploration()
                return

            if explore_result.status == "COMPLETED":
                self.get_logger().info(
                    "\n::Explore complete::\n"
                    f"mode = {self.exploration_mode}\n"
                    f"message = {explore_result.message}"
                )
                self.blackboard.exploration_completed = True
                return

        self.get_logger().warning(
            "\n::Explore ended unexpectedly::\n"
            f"goal_status = {wrapped_result.status}\n"
            f"message = {explore_result.message}"
        )

        self.blackboard.exploration_completed = False

    def pause_exploration(self) -> None:
        if not self.exploration_goal_active:
            return
        if self.exploration_goal_handle is None:
            return
        if self.exploration_cancel_requested:
            return

        self.exploration_cancel_requested = True

        self.get_logger().info(
            "Exploration cancel requested"
        )
        cancel_future = (
            self.exploration_goal_handle.cancel_goal_async()
        )
        cancel_future.add_done_callback(
            self.exploration_cancel_callback
        )

    def exploration_cancel_callback(
            self,
            future,
    ) -> None:

        try:
            cancel_response = future.result()
        except Exception as error:
            self.get_logger().error(
                f"Failed to cancel explore goal : {error}"
            )
            self.exploration_cancel_requested = False
            return

        if len(cancel_response.goals_canceling) == 0:
            self.get_logger().warning(
                "Explore goal cancel was rejected"
            )
            self.exploration_cancel_requested = False
            return

        self.get_logger().info(
            "Explore goal cancel was accepted"
        )

    def exploration_is_finished(self) -> bool:

        motivation_empty = (
            self.blackboard.motivation <= 0
        )

        enough_observations = (
            self.blackboard.observation_count
            >= self.blackboard.minimum_observation_count
        )

        timeout = (
            self.exploration_is_timeout()
        )

        if timeout:
            return True

        return (
            motivation_empty
            and enough_observations
        )

    def finish_exploration(self) -> None:

        self.blackboard.exploration_finished_requested = True

        started_at = self.blackboard.exploration_started_at
        elapsed_time = 0.0
        if started_at is not None:
            now = self.get_clock().now().nanoseconds / 1e9
            elapsed_time = now - started_at

        self.get_logger().info(
            "\n::Exploration finish condition met::\n"
            f"motivation = {self.blackboard.motivation}\n"
            f"observation_count = {self.blackboard.observation_count}\n"
            f"elapsed_time = {elapsed_time:.1f}s"
        )

        if self.exploration_goal_active:
            self.pause_exploration()

        self.publish_behavior_event(
            "EXPLORATION_FINISHED",
            (
                f"motivation = {self.blackboard.motivation}\n"
                f"observation_count = {self.blackboard.observation_count}"
            ),
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
            return

        goal_msg = FirstEncounter.Goal()
        goal_msg.target = current_object

        self.first_encounter_goal_active = True
        self.blackboard.current_stage = (
            ObjectProcessStage.ENCOUNTERING
        )
        self.get_logger().info(
            "\n::First encounter goal requested::\n"
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
        self.current_detail = (
            f"{feedback.stage} : {feedback.message} ({feedback.progress * 100.0:.0f}%)"
        )
        self.get_logger().info(
            "\n::First encounter feedback::\n"
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
        self.first_encounter_cancel_requested = False

        try:
            wrapped_result = future.result()

            if wrapped_result.status == GoalStatus.STATUS_CANCELED:

                self.first_encounter_goal_active = False
                self.first_encounter_goal_handle = None
                self.first_encounter_cancel_requested = False

                self.get_logger().info(
                    "\nFirst_encounter canceled"
                )
                return

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
                "\n::First encounter failed::\n"
                f"detection_id = {encounter_result.detection_id}\n"
                f"reason = {encounter_result.failure_reason}"
            )
            self.blackboard.current_stage = (
                ObjectProcessStage.FAILED
            )
            return

        self.get_logger().info(
            "\n::First encounter completed::\n"
            f"detection_id = {encounter_result.detection_id}\n"
            f"image_path = {encounter_result.image_path}\n"
            f"object_name = {encounter_result.label.object_name}"
        )

        self.consume_motivation(
            5,
            "First encounter completed ( -5 )",
        )

        self.blackboard.current_stage = (
            ObjectProcessStage.ENCOUNTER_COMPLETED
        )

    def cancel_first_encounter(self) -> None:

        if not self.first_encounter_goal_active:
            return

        if self.first_encounter_goal_handle is None:
            return

        if self.first_encounter_cancel_requested:
            return

        self.first_encounter_cancel_requested = True

        self.get_logger().info(
            "First Encounter cancel requested"
        )

        cancel_future = (
            self.first_encounter_goal_handle.cancel_goal_async()
        )
        cancel_future.add_done_callback(
            self.first_encounter_cancel_callback
        )

    def first_encounter_cancel_callback(
            self,
            future,
    ) -> None:

        try:
            response = future.result()

        except Exception as error:
            self.get_logger().error(
                f"\nFailed to cancel First encounter : {error}"
            )
            self.first_encounter_cancel_requested = False
            return

        if not response.goals_canceling:
            self.get_logger().warning(
                "\nFirst encounter cancel was rejected"
            )
            self.first_encounter_cancel_requested = False
            return

        self.get_logger().info(
            "\nFirst encounter cancel was accepted"
        )

    def start_curiosity_evaluation(self) -> None:
        if self.curiosity_request_active:
            return

        encounter_result = self.blackboard.encounter_result

        if encounter_result is None:
            self.get_logger().warning(
                "Cannot evaluate curiosity : encounter_result is missing"
            )
            self.blackboard.current_stage = (
                ObjectProcessStage.FAILED
            )
            return

        if not self.curiosity_client.service_is_ready():
            self.get_logger().warning(
                "Evaluate curiosity services is not ready"
            )
            return

        request = EvaluateCuriosity.Request()
        request.encounter = encounter_result
        self.curiosity_request_active = True

        self.blackboard.current_stage = (
            ObjectProcessStage.EVALUATING_CURIOSITY
        )

        self.get_logger().info(
            "\n::Curiosity evaluation requested::\n"
            f"detection_id = {encounter_result.detection_id}"
        )

        future = self.curiosity_client.call_async(request)
        future.add_done_callback(
            self.curiosity_response_callback
        )

    def curiosity_response_callback(self, future) -> None:
        self.curiosity_request_active = False
        try:
            response = future.result()
        except Exception as error:
            self.get_logger().error(
                f"Curiosity service call failed : {error}"
            )
            self.blackboard.current_stage = (
                ObjectProcessStage.FAILED
            )
            return

        if not response.success:
            self.get_logger().warning(
                "\n::Curiosity evaluation failed::\n"
                f"message = {response.message}"
            )
            self.blackboard.current_stage = (
                ObjectProcessStage.FAILED
            )
            return

        self.blackboard.curiosity_decision = (
            response.decision
        )
        self.blackboard.current_stage = (
            ObjectProcessStage.CURIOSITY_EVALUATED
        )
        self.get_logger().info(
            "Curiosity evaluation completed::\n"
            f"action = {response.decision.action}\n"
            f"curiosity_score = {response.decision.curiosity_score : .2f}\n"
            f"similarity_score = {response.decision.similarity_score : .2f}\n"
            f"reason = {response.decision.reason}"
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
            return

        if decision.action == "IGNORE":
            self.consume_motivation(
                2,
                "Object ignored",
            )

            self.blackboard.current_stage = (
                ObjectProcessStage.IGNORED
            )

            return

        self.get_logger().warning(
            f"Unknown curiosity action : {decision.action}"
        )
        self.blackboard.current_stage = (
            ObjectProcessStage.FAILED
        )

    def start_observation(self) -> None:
        if self.observation_goal_active:
            return

        encounter_result = self.blackboard.encounter_result
        curiosity_decision = self.blackboard.curiosity_decision

        if encounter_result is None:
            self.get_logger().warning(
                "Cannot start observation : encounter_result is missing"
            )
            self.blackboard.current_stage = (
                ObjectProcessStage.FAILED
            )
            return

        if curiosity_decision is None:
            self.get_logger().warning(
                "Cannot start observation : curiosity_decision is missing"
            )
            self.blackboard.current_stage = (
                ObjectProcessStage.FAILED
            )
            return

        if not self.observation_action_client.server_is_ready():
            self.get_logger().warning(
                "Observe Object action server is not ready"
            )
            return

        goal_msg = ObserveObject.Goal()
        goal_msg.encounter = encounter_result
        goal_msg.decision = curiosity_decision

        self.observation_goal_active = True

        self.get_logger().info(
            "\n::Observation goal requested::\n"
            f"detection_id = {encounter_result.detection_id}\n"
            f"object_name = {encounter_result.label.object_name}"
        )

        send_goal_future = (
            self.observation_action_client.send_goal_async(
                goal_msg,
                feedback_callback=(
                    self.observation_feedback_callback
                ),
            )
        )
        send_goal_future.add_done_callback(
            self.observation_goal_response_callback
        )

    def observation_goal_response_callback(
            self,
            future,
    ) -> None:
        try:
            goal_handle = future.result()
        except Exception as error:
            self.get_logger().error(
                f"Failed to send observation goal : {error}"
            )
            self.observation_goal_active = False
            self.blackboard.current_stage = (
                ObjectProcessStage.FAILED
            )
            return

        if not goal_handle.accepted:
            self.get_logger().warning(
                "Observation goal was rejected"
            )
            self.observation_goal_active = False
            self.blackboard.current_stage = (
                ObjectProcessStage.FAILED
            )
            return

        self.observation_goal_handle = goal_handle

        self.get_logger().info(
            "Observation goal was accepted"
        )

        result_future = goal_handle.get_result_async()

        result_future.add_done_callback(
            self.observation_result_callback
        )

    def observation_feedback_callback(
            self,
            feedback_msg,
    ) -> None:

        feedback = feedback_msg.feedback

        self.current_detail = (
            f"{feedback.stage} : {feedback.message} ({feedback.progress * 100.0:.0f}%)"
        )
        self.get_logger().info(
            "\n::Observation feedback::\n"
            f"stage = {feedback.stage}\n"
            f"progress = {feedback.progress}\n"
            f"message = {feedback.message}"
        )

    def observation_result_callback(
        self,
        future,
    ) -> None:

        self.observation_goal_active = False
        self.observation_goal_handle = None
        self.observation_cancel_requested = False

        try:
            wrapped_result = future.result()

            if wrapped_result.status == GoalStatus.STATUS_CANCELED:

                self.observation_goal_active = False
                self.observation_goal_handle = None
                self.observation_cancel_requested = False

                self.get_logger().info(
                    "\nObservation canceled"
                )

                return

            observation_result = wrapped_result.result.result

        except Exception as error:
            self.get_logger().error(
                f"Failed to receive observation result : {error}"
            )
            self.blackboard.current_stage = (
                ObjectProcessStage.FAILED
            )
            return

        self.blackboard.observation_result = observation_result

        if not observation_result.success:
            self.get_logger().warning(
                "\n::Observation failed::\n"
                f"detection_id = {observation_result.detection_id}\n"
                f"reason = {observation_result.failure_reason}"
            )
            self.blackboard.current_stage = (
                ObjectProcessStage.FAILED
            )
            return

        self.get_logger().info(
            "\n::Observation completed::\n"
            f"detection_id = {observation_result.detection_id}\n"
            f"saved_to_database = {observation_result.saved_to_database}"
        )

        self.consume_motivation(
            10,
            "Detailed observation completed",
        )
        self.blackboard.observation_count += 1

        self.blackboard.current_stage = (
            ObjectProcessStage.OBSERVATION_COMPLETED
        )

    def cancel_observation(self) -> None:

        if not self.observation_goal_active:
            return
        if self.observation_goal_handle is None:
            return
        if self.observation_cancel_requested:
            return

        self.observation_cancel_requested = True

        self.get_logger().info(
            "\nObservation cancel requested"
        )

        cancel_future = (
            self.observation_goal_handle.cancel_goal_async()
        )
        cancel_future.add_done_callback(
            self.observation_cancel_callback
        )

    def observation_cancel_callback(
            self,
            future,
    ) -> None:

        try:
            response = future.result()

        except Exception as error:
            self.get_logger().error(
                f"\nFailed to cancel observation : {error}"
            )
            self.observation_cancel_requested = False
            return

        if not response.goals_canceling:
            self.get_logger().warning(
                "\nObservation cancel was rejected"
            )
            self.observation_cancel_requested = False
            return

        self.get_logger().info(
            "\nObservation cancel was accepted"
        )


    def start_return_home(self) -> None:
        if self.return_home_goal_active:
            return

        if not self.return_home_action_client.server_is_ready():
            self.get_logger().warning(
                "Returning home action server is not ready"
            )
            return

        goal_msg = ReturnHome.Goal()

        if self.blackboard.battery_low:
            goal_msg.reason = "BATTERY_LOW"
        elif self.blackboard.return_requested:
            goal_msg.reason = "EXPLORATION_FINISHED"
        else:
            goal_msg.reason = "MISSION_RETURN"

        self.return_home_goal_active = True
        self.get_logger().info(
            "\n::Return home goal requested::\n"
            f"reason = {goal_msg.reason}"
        )

        send_goal_future = (
            self.return_home_action_client.send_goal_async(
                goal_msg,
                feedback_callback=(
                    self.return_home_feedback_callback
                ),
            )
        )

        send_goal_future.add_done_callback(
            self.return_home_goal_response_callback
        )

    def return_home_goal_response_callback(
            self,
            future,
    ) -> None:
        try:
            goal_handle = future.result()

        except Exception as error:
            self.get_logger().error(
                f"\nFailed to send Return Home goal : {error}"
            )
            self.return_home_goal_active = False
            return

        if not goal_handle.accepted:
            self.get_logger().warning(
                "\nReturn home goal was rejected"
            )
            self.return_home_goal_active = False
            return

        self.return_home_goal_handle = goal_handle
        self.get_logger().info(
            "\nReturn Home goal was accepted"
        )
        result_future = (
            goal_handle.get_result_async()
        )
        result_future.add_done_callback(
            self.return_home_result_callback
        )

    def return_home_feedback_callback(
            self,
            feedback_msg,
    ) -> None:

        feedback = feedback_msg.feedback

        self.current_detail = (
            f"{feedback.stage} : "
            f"{feedback.message} "
            f"({feedback.progress * 100.0:.0f} % )"
        )
        self.get_logger().info(
            "\n::Return home feedback::\n"
            f"stage = {feedback.stage}\n"
            f"progress = {feedback.progress:.2f}\n"
            f"message = {feedback.message}"
        )

    def return_home_result_callback(
            self,
            future,
    ) -> None:
        self.return_home_goal_active = False
        self.return_home_goal_handle = None

        try:
            wrapped_result = future.result()
            result = wrapped_result.result
        except Exception as error:
            self.get_logger().error(
                f"\nFailed to receive return home result : {error}"
            )
            return

        if not result.success:
            self.get_logger().warning(
                "\n::Return home failed::\n"
                f"message = {result.message}"
            )
            self.publish_behavior_event(
                "RETURN_HOME_FAILED",
                result.message,
            )
            return

        self.get_logger().info(
            "\n::Return Home completed::\n"
            f"message = {result.message}"
        )

        self.blackboard.return_requested = False
        self.blackboard.return_completed = True

        self.publish_behavior_event(
            "RETURN_HOME_COMPLETED",
            result.message,
        )

    def return_home_preparation(self) -> None:
        self.get_logger().info(
            "\n::Preparing for return::\n"
        )
        self.blackboard.detection_locked = True
        self.blackboard.exploration_paused = True

        self.blackboard.pending_objects.clear()

        if self.exploration_goal_active:
            self.pause_exploration()

        if self.first_encounter_goal_active:
            self.cancel_first_encounter()

        if self.observation_goal_active:
            self.cancel_observation()

        if(
            self.exploration_goal_active
            or self.first_encounter_goal_active
            or self.observation_goal_active
        ):
            self.get_logger().info(
                "Waiting for active behaviors to stop..."
            )
            return

        self.blackboard.current_object = None
        self.blackboard.current_stage = (
            ObjectProcessStage.NONE
        )

        self.blackboard.encounter_result = None
        self.blackboard.curiosity_decision = None
        self.blackboard.observation_result = None

        self.return_home_prepared = True

        self.get_logger().info(
            "Return preparation completed"
        )


    def start_reflection(self) -> None:
        if self.reflection_goal_active:
            return

        if not self.reflection_action_client.server_is_ready():
            self.get_logger().warning(
                "Reflect action server is not ready"
            )
            return

        goal_msg = Reflect.Goal()
        goal_msg.session_id = "odi_exploration"

        self.reflection_goal_active = True
        self.blackboard.reflection_active = True

        self.get_logger().info(
            "\n::Reflect goal requested::\n"
            f"session_id = {goal_msg.session_id}"
        )

        send_goal_future = (
            self.reflection_action_client.send_goal_async(
                goal_msg,
                feedback_callback = (
                    self.reflection_feedback_callback
                ),
            )
        )

        send_goal_future.add_done_callback(
            self.reflection_goal_response_callback
        )

    def reflection_goal_response_callback(
            self,
            future,
    ) -> None:
        try:
            goal_handle = future.result()
        except Exception as error:
            self.get_logger().error(
                f"Failed to send Reflect goal : {error}"
            )
            self.reflection_goal_active = False
            self.blackboard.reflection_active = False
            return

        if not goal_handle.accepted:
            self.get_logger().warning(
                "Reflect goal was rejected"
            )

            self.reflection_goal_active = False
            self.blackboard.reflection_active = False
            return

        self.reflection_goal_handle = goal_handle

        self.get_logger().info(
            "Reflect goal was accepted"
        )

        result_future = (
            goal_handle.get_result_async()
        )

        result_future.add_done_callback(
            self.reflection_result_callback
        )

    def reflection_feedback_callback(
            self,
            feedback_msg,
    ) -> None:

        feedback = feedback_msg.feedback

        self.current_detail = (
            f"\n{feedback.stage} : {feedback.message}"
            f"({feedback.progress*100.0:.0f}%)"
        )
        self.get_logger().info(
            "\n::Reflect feedback::\n"
            f"stage = {feedback.stage}\n"
            f"progress = {feedback.progress:.2f}\n"
            f"message = {feedback.message}"
        )

    def reflection_result_callback(
            self,
            future,
    ) -> None:

        self.reflection_goal_active = False
        self.reflection_goal_handle = None
        self.blackboard.reflection_active = False

        try:
            wrapped_result = future.result()
            result = wrapped_result.result
        except Exception as error:
            self.get_logger().error(
                f"Failed to receive Reflect result : {error}"
            )
            self.publish_behavior_event(
                "REFLECTION_FAILED",
                str(error),
            )
            return
        if not result.success:
            self.get_logger().warning(
                "\n::Reflection failed::\n"
                f"message = {result.message}"
            )
            self.publish_behavior_event(
                "REFLECTION_FAILED",
                result.message,
            )
            return

        self.get_logger().info(
            "\n::Reflection completed::\n"
            f"diary_id = {result.diary_id}\n"
            f"diary_text = {result.diary_text}\n"
            f"message = {result.message}"
        )

        self.blackboard.reflection_completed = True

        self.publish_behavior_event(
            "REFLECTION_COMPLETED",
            result.message,
        )


    def consume_motivation(
            self,
            amount: int,
            reason: str,
    ) -> None:
        previous_motivation = (self.blackboard.motivation)
        self.blackboard.motivation = max(
            0,
            self.blackboard.motivation - amount
        )
        self.get_logger().info(
            "\n::Motivation consumed::\n"
            f"reason = {reason}\n"
            f"{previous_motivation} -> {self.blackboard.motivation}"
        )

    def exploration_is_timeout(self) -> bool:
        started_at = self.blackboard.exploration_started_at
        if started_at is None:
            return False
        now = self.get_clock().now().nanoseconds / 1e9
        elapsed_time = now - started_at
        return (
            elapsed_time >= self.blackboard.exploration_maximum_time
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

        behavior_changed = (
            behavior != self.current_behavior
        )
        previous_behavior = self.current_behavior

        self.current_behavior = behavior
        self.current_status = status
        self.current_detail = detail

        if behavior_changed:
            self.get_logger().info(
                "\n::Behavior changed::\n"
                f"{previous_behavior.value} -> {behavior.value}"
            )
        self.publish_current_behavior()

    def publish_current_behavior(self) -> None:
        msg = BehaviorState()
        msg.behavior = self.current_behavior.value
        msg.status = self.current_status.value
        msg.detail = self.current_detail
        msg.updated_at = self.get_clock().now().to_msg()

        self.behavior_state_publisher.publish(msg)

    def publish_behavior_event(
            self,
            event: str,
            detail: str,
    ) -> None:

        msg = BehaviorEvent()
        msg.event = event
        msg.detail = detail
        msg.occurred_at = (self.get_clock().now().to_msg())

        self.behavior_event_publisher.publish(msg)

        self.get_logger().info(
            "\n::Behavior event published::\n"
            f"event = {event}\n"
            f"detail = {detail}"
        )

def main(args=None) -> None:
    rclpy.init(args=args)
    node = BehaviorExecutorNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        node.get_logger().info(
            "\nBehavior Executor node is terminated"
        )
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()



