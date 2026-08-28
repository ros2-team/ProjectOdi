#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
from rclpy.executors import MultiThreadedExecutor
from rclpy.callback_groups import ReentrantCallbackGroup

from odi_interfaces.msg import CuriosityDecision
from odi_interfaces.srv import EvaluateCuriosity, GetSimilarObservations

from curiosity_engine.core import (
    ObjectCandidate,
    MemoryInfo,
    CuriosityCalculator,
    CuriosityPolicy
)
from curiosity_engine.core import weights as W


class CuriosityEngineNode(Node):
    """
    호기심 판단 노드.

    구조:
        [메인] --EvaluateCuriosity--> [이 노드]
                                        |
                                        | GetSimilarObservations
                                        ↓
                                  [World Memory] --> MySQL

    이 노드는 더 이상 DB에 직접 접속하지 않는다.
    DB 접근은 World Memory가 전담하고, 여기서는 서비스로 물어본다.

    World Memory는 object_name이 일치하는 기록만 돌려주므로,
    "선풍기를 봤으면 과거의 선풍기들만" 비교 대상이 된다.
    """

    def __init__(self):
        super().__init__('curiosity_engine_node')

        # 서비스 콜백 안에서 또 다른 서비스를 호출하므로
        # ReentrantCallbackGroup + MultiThreadedExecutor가 필수다.
        # 안 그러면 응답을 기다리다 스스로를 막아 데드락이 난다.
        self.callback_group = ReentrantCallbackGroup()

        self.calculator = CuriosityCalculator()
        self.policy = CuriosityPolicy()

        self.srv_curiosity = self.create_service(
            EvaluateCuriosity,
            '/evaluate_curiosity',
            self.evaluate_curiosity_callback,
            callback_group=self.callback_group,
        )

        self.cli_similar = self.create_client(
            GetSimilarObservations,
            '/world_memory/get_similar_observations',
            callback_group=self.callback_group,
        )

        self.get_logger().info('==========================================')
        self.get_logger().info('Curiosity Engine 준비완!!!!!서비스 요청 기다림 ')
        self.get_logger().info('==========================================')

    # ============================================================
    # Service Callback
    # ============================================================

    def evaluate_curiosity_callback(self, request, response):
        encounter = request.encounter
        label = encounter.label

        self.get_logger().info(
            f'[SERVICE] 평가 요청: detection_id={encounter.detection_id}, '
            f'object={label.object_name}'
        )

        # 조우 자체가 실패했으면 label이 비어 있으므로 평가하지 않는다.
        if not encounter.success:
            response.success = False
            response.message = (
                f'Encounter failed: {encounter.failure_reason}'
            )
            self.get_logger().warn(f'[SERVICE] {response.message}')
            return response

        candidate = ObjectCandidate(
            object_name=label.object_name,
            primary_color=label.object_primary_color,
            secondary_color=label.object_secondary_color,
            material=label.object_material,
            shape=label.object_shape,
            condition=label.object_condition,
            special_features=list(label.object_special_features),
        )

        result = self.evaluate(candidate, encounter)
        if result is None:
            response.success = False
            response.message = 'World Memory query failed'
            self.get_logger().error(f'[SERVICE] {response.message}')
            return response

        memory, calc_result, action = result

        decision = CuriosityDecision()
        decision.detection_id = str(encounter.detection_id)
        decision.curiosity_score = float(calc_result['score'])
        decision.similarity_score = float(memory.similarity)
        decision.action = str(action)
        decision.reason = (
            f'Novelty={calc_result["novelty"]:.2f}'
            f'(x{calc_result["decay"]:.2f}), '
            f'Change={calc_result["change"]:.2f}'
            f'{calc_result["changed_features"]}, '
            f'Similarity={memory.similarity:.2f}, '
            f'Visits={memory.visit_count}'
        )
        decision.novel_features = list(calc_result['novel_features'])
        decision.duplicated_features = list(calc_result['duplicated_features'])
        decision.compared_record_count = int(memory.compared_record_count)
        decision.evaluated_at = self.get_clock().now().to_msg()

        response.success = True
        response.decision = decision
        response.message = '호기심 평가 완료ㅇㅇ'
        return response

    # ============================================================
    # 평가 로직
    # ============================================================

    def evaluate(self, candidate: ObjectCandidate, encounter):
        """반환: (memory, calc_result, action) 또는 실패 시 None"""

        name = (candidate.object_name or '').strip().lower()

        # 탐사 대상이 아닌 구조물/사람은 조회 없이 즉시 종료
        if name in W.IGNORE_CLASSES:
            self.get_logger().info(f'[FILTER] "{name}" is not a target -> IGNORE')
            memory = MemoryInfo(visit_count=0, is_new=True)
            calc_result = {
                'novelty': 0.0, 'change': 0.0,
                'novelty_term': 0.0, 'change_term': 0.0,
                'decay': 1.0, 'score': 0.0,
                'changed_features': [],
                'novel_features': [], 'duplicated_features': [],
            }
            return memory, calc_result, 'IGNORE'

        memory = self.get_memory(encounter, candidate)
        if memory is None:
            return None

        calc_result = self.calculator.calculate_score(candidate, memory)
        action = self.policy.decide_action(calc_result['score'])

        self.log_result(candidate, memory, calc_result, action)
        return memory, calc_result, action

    # ============================================================
    # World Memory 조회
    # ============================================================

    def get_memory(self, encounter, candidate: ObjectCandidate):
        """
        1) World Memory에 같은 이름의 과거 기록을 요청한다
        2) 응답 중 가장 닮은 기록을 찾아 similarity를 구한다
        3) 임계값을 넘으면 '같은 개체'로 보고,
           가장 최근 기록(배열 0번)을 change 비교 기준으로 삼는다

        3번이 중요하다. best match는 '가장 닮은 기록'이라
        차이가 최소가 되도록 선택된 것이므로
        변화 감지의 기준으로 쓰면 안 된다.
        """
        if not self.cli_similar.wait_for_service(timeout_sec=2.0):
            self.get_logger().error(
                '[MEMORY] World Memory 서비스를 찾을 수 없음'
            )
            return None

        req = GetSimilarObservations.Request()
        req.encounter = encounter
        req.max_results = W.MAX_SIMILAR_RESULTS

        future = self.cli_similar.call_async(req)

        # ReentrantCallbackGroup + MultiThreadedExecutor 조합이라
        # 여기서 블로킹해도 다른 콜백이 계속 처리된다.
        if not self.wait_future(future, W.WORLD_MEMORY_TIMEOUT):
            self.get_logger().error('[MEMORY] World Memory 응답 타임아웃')
            return None

        res = future.result()
        if res is None or not res.success:
            message = res.message if res else 'no response'
            # 기록이 0건일 때도 success=False로 올 수 있으므로
            # 실패로 단정하지 않고 '처음 보는 물체'로 처리한다.
            self.get_logger().info(f'[MEMORY] 과거 기록 없음 ({message})')
            return MemoryInfo(visit_count=0, is_new=True, similarity=0.0)

        records = list(res.observations)

        if not records:
            self.get_logger().info('[MEMORY] 처음 보는 물체 (기록 0건)')
            return MemoryInfo(visit_count=0, is_new=True, similarity=0.0)

        # --- best match 탐색 ---
        best_similarity = 0.0
        best_record = None

        for stored in records:
            record = self.stored_to_memory(stored)
            similarity = self.calculator.calculate_similarity(candidate, record)

            self.get_logger().debug(
                f'[MEMORY] {stored.memory_id} sim={similarity:.2f}'
            )

            if similarity > best_similarity:
                best_similarity = similarity
                best_record = record

        compared_record_count = len(records)

        # --- 신규 판정 ---
        if best_record is None or best_similarity < W.IDENTITY_THRESHOLD:
            self.get_logger().info(
                f'[MEMORY] New object (best_similarity={best_similarity:.2f}, '
                f'compared={compared_record_count})'
            )
            return MemoryInfo(
                visit_count=0,
                is_new=True,
                similarity=best_similarity,
                compared_record_count=compared_record_count,
            )

        # --- 기존 개체 ---
        # World Memory 응답은 stored_at DESC 정렬이므로
        # 배열의 0번이 가장 최근 기록이다.
        latest = self.stored_to_memory(records[0])
        latest.is_new = False
        latest.visit_count = compared_record_count
        latest.similarity = best_similarity
        latest.compared_record_count = compared_record_count

        self.get_logger().info(
            f'[MEMORY] Existing object sim={best_similarity:.2f}, '
            f'visit_count={latest.visit_count}, '
            f'latest={latest.memory_id}'
        )
        return latest

    def wait_future(self, future, timeout_sec):
        """future가 완료될 때까지 대기. 타임아웃이면 False."""
        import time
        deadline = time.time() + timeout_sec
        while rclpy.ok() and not future.done():
            if time.time() > deadline:
                return False
            time.sleep(0.02)
        return future.done()

    @staticmethod
    def stored_to_memory(stored) -> MemoryInfo:
        """StoredObservation → MemoryInfo 변환 (필드 매핑을 한 곳에 모은다)"""
        label = stored.observation.detailed_label
        return MemoryInfo(
            visit_count=0,
            is_new=False,
            object_name=label.object_name,
            primary_color=label.object_primary_color,
            secondary_color=label.object_secondary_color,
            material=label.object_material,
            shape=label.object_shape,
            condition=label.object_condition,
            special_features=list(label.object_special_features),
            memory_id=stored.memory_id,
        )

    # ============================================================

    def log_result(self, candidate, memory, calc, action):
        self.get_logger().info('==========================================')
        self.get_logger().info('[CURIOSITY RESULT]')
        self.get_logger().info(f'Object      : {candidate.object_name}')
        self.get_logger().info(f'Similarity  : {memory.similarity:.2f}')
        self.get_logger().info(f'IsNew       : {memory.is_new}')
        self.get_logger().info(f'Visit Count : {memory.visit_count}')
        self.get_logger().info(
            f'Novelty     : {calc["novelty"]:.2f} '
            f'x decay {calc["decay"]:.2f} -> {calc["novelty_term"]:.2f}'
        )
        self.get_logger().info(
            f'Change      : {calc["change"]:.2f} -> {calc["change_term"]:.2f} '
            f'{calc["changed_features"]}'
        )
        self.get_logger().info(f'Curiosity   : {calc["score"]:.2f}')
        self.get_logger().info(f'Decision    : {action}')
        self.get_logger().info('==========================================')


def main(args=None):
    rclpy.init(args=args)

    node = CuriosityEngineNode()
    executor = MultiThreadedExecutor()
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