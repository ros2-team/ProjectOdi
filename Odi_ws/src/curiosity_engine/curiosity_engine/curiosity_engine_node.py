import rclpy
from rclpy.node import Node

# core 패키지 가져옴 
from curiosity_engine.core import ObjectCandidate, MemoryInfo, CuriosityCalculator, CuriosityPolicy


class CuriosityEngineNode(Node):
    def __init__(self):
        super().__init__('curiosity_engine_node')

        # 더미 메모리 DB
        self.dummy_memory_db = {
            1: MemoryInfo(visit_count=0, change=True),
            2: MemoryInfo(visit_count=0, change=True),    # 방문 횟수 0으로 변경
            3: MemoryInfo(visit_count=0, change=True)     # 방문 횟수 0으로 변경
        }

        # 로직 클래스 인스턴스화
        self.calculator = CuriosityCalculator()  # 점수 계산기
        self.policy = CuriosityPolicy()          # 행동 결정기 

        # 2초마다 실행되는 더미 루프
        self.timer = self.create_timer(2.0, self.timer_callback)
        self.get_logger().info("Curiosity Engine Node Started")

    def timer_callback(self):
        # 더미 데이터 생성
        dummy_objects = [
            ObjectCandidate(track_id=1, class_name="bottle", confidence=0.42),
            ObjectCandidate(track_id=2, class_name="cup", confidence=0.43),
            ObjectCandidate(track_id=3, class_name="chair", confidence=0.98)
        ]

        for candidate in dummy_objects:
            if candidate.track_id not in self.dummy_memory_db:
                self.dummy_memory_db[candidate.track_id] = MemoryInfo(visit_count=0, change=False)

            memory = self.dummy_memory_db[candidate.track_id]
            
            # 1. 점수 계산
            calc_result = self.calculator.calculate_score(candidate, memory)
            # 2. 행동 결정
            decision = self.policy.decide_action(calc_result["score"])
            # 3. 콘솔 로그 출력
            self.print_log(candidate, memory, calc_result, decision)

            #접근해서 조사를 수행했거나 관찰을 진행한 경우
            if decision in ["APPROACH_AND_INSPECT", "OBSERVE_FROM_DISTANCE"]:
                memory.visit_count += 1  # 방문 횟수 증가 -> Novelty 감소
                memory.change = False    # 변화 상태 확인 완료 처리 -> Change 가중치 제거

    def print_log(self, candidate, memory, result, decision):
        log_msg = (
            f"\n==============================\n"
            f"Object : {candidate.class_name} (ID: {candidate.track_id})\n"  # 물체 고유번호 
            f"Visit Count : {memory.visit_count}\n"                          # 물체 방문/관찰한 횟수 
            f"Confidence : {candidate.confidence}\n"                         # yolo 인식 신뢰도
            f"Novelty : {result['novelty']}\n"                               # 참신성 (방문횟수가 적을수록 높으ㅁ)
            f"Uncertainty : {result['uncertainty']}\n"                       # 불확실성 (yolo 인식 신뢰도가 낮을수록 높음 )
            f"Change : {memory.change}\n\n"                                  # 이전 관찰 시점에서 위치 변화 여부 
            f"Curiosity Score : {result['score']}\n"                         # 가중치 계산한 총합 점수
            f"Decision : {decision}\n"                                       # 호기심 점수에 따른 로봇 행동 
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

