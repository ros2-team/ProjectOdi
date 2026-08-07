import rclpy
from rclpy.node import Node

# core 패키지 가져옴 
from curiosity_engine.core import ObjectCandidate, MemoryInfo, CuriosityCalculator, CuriosityPolicy


class CuriosityEngineNode(Node):
    def __init__(self):
        super().__init__('curiosity_engine_node')

        # 더미 메모리 DB (초기 상태)
        self.dummy_memory_db = {}

        # 로직 클래스 인스턴스화
        self.calculator = CuriosityCalculator()  # 점수 계산기
        self.policy = CuriosityPolicy()          # 행동 결정기

        # 2초 주기로 타이머 콜백 실행
        self.timer = self.create_timer(2.0, self.timer_callback)
        self.get_logger().info("Curiosity Engine Node Started")

    def timer_callback(self):
        # 비전 AI 노드에서 수신되었다고 가정하는 더미 입력 데이터
        dummy_objects = [
            # 예시: ID 1번 물체 (상태가 DIRTY로 새로 감지된 bottle)
            ObjectCandidate(
                track_id=1, confidence=0.55, object_name="bottle",
                primary_color="blue", secondary_color="white", material="plastic",
                shape="cylinder", condition="DIRTY"
            )
        ]

        for candidate in dummy_objects:
            # DB에 ID가 전혀 없으면 최초 발견된 물체(is_new=True)로 DB 인스턴스 생성
            if candidate.track_id not in self.dummy_memory_db:
                self.dummy_memory_db[candidate.track_id] = MemoryInfo(is_new=True)

            memory = self.dummy_memory_db[candidate.track_id]

            # 1. 과거 DB(memory)와 현재 실시간 데이터(candidate) 비교 점수 계산
            calc_result = self.calculator.calculate_score(candidate, memory)
            
            # 2. 산출된 점수로 행동 결정
            decision = self.policy.decide_action(calc_result["score"])

            # 3. 콘솔 로그 출력
            self.print_log(candidate, memory, calc_result, decision)

            # 4. IGNORE가 아닌 유의미한 관찰 행동을 수행한 경우 DB 최신화
            if decision != "IGNORE":
                memory.visit_count += 1    # 방문 횟수 증가 -> 다음번 Visit Score 감소
                memory.is_new = False      # 최초 발견 확인 완료 처리 -> 다음번 Novelty 점수 제거(0점)
                
                # [중요] 변한 속성을 확인 완료했으므로 DB 상태를 현재 상태로 동기화 (Change Reset)
                memory.primary_color = candidate.primary_color
                memory.secondary_color = candidate.secondary_color
                memory.material = candidate.material
                memory.shape = candidate.shape
                memory.condition = candidate.condition

    def print_log(self, candidate, memory, result, decision):
        """디버깅을 위한 출력 로그 포맷"""
        log_msg = (
            f"\n==============================\n"
            f"Object : {candidate.object_name} (ID: {candidate.track_id})\n"
            f"Visit Count : {memory.visit_count} | Is New : {memory.is_new}\n"
            f"Confidence : {candidate.confidence}\n"
            f"------------------------------\n"
            f"Novelty Score    : {result['novelty']}\n"
            f"Visit Score      : {result['visit']}\n"
            f"Change Score     : {result['change']}\n"
            f"Uncertainty Score: {result['uncertainty']}\n"
            f"------------------------------\n"
            f"Total Curiosity Score : {result['score']}\n"
            f"Decision : {decision}\n"
            f"=============================="
        )
        self.get_logger().info(log_msg)


def main(args=None):
    rclpy.init(args=args)
    node = CuriosityEngineNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()

