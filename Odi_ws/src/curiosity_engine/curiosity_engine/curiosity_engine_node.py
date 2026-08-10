#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
import mysql.connector
from mysql.connector import Error

from odi_interfaces.msg import SemanticLabel

# ============================================================
# Curiosity Engine 내부 모듈
# ============================================================
from curiosity_engine.core import (
    ObjectCandidate,
    MemoryInfo,
    CuriosityCalculator,
    CuriosityPolicy
)

class CuriosityEngineNode(Node):

    def __init__(self):
        super().__init__('curiosity_engine_node')

        # ========================================================
        # 1. 임시 Memory DB
        # ========================================================
        # 현재는 실제 DB / world_memory_node가 아직 없기 때문에
        # 테스트를 위해 Curiosity Engine 내부에서 임시 DB를 사용한다.
 
        # ========================================================
        # MySQL DB 연결
        # ========================================================
        try:
            self.conn = mysql.connector.connect(
                host='192.168.0.20',
                port=3306,
                user='yyj',
                password='1234',
                database='Odi_DB'
            )

            self.cursor = self.conn.cursor(dictionary=True)

            if self.conn.is_connected():
                self.get_logger().info('==========================================')
                self.get_logger().info('MySQL DB connected successfully')
                self.get_logger().info('Database: Odi_DB')
                self.get_logger().info('==========================================')

        except Error as e:
            self.get_logger().error(
                f'MySQL connection failed: {e}'
            )

            self.conn = None
            self.cursor = None

        if self.cursor is not None:

            try:
                self.cursor.execute("SHOW TABLES")

                tables = self.cursor.fetchall()

                for table in tables:
                    self.get_logger().info(
                        f'[DB TABLE] {table}'
                    )

            except Error as e:
                self.get_logger().error(
                    f'Table query failed: {e}'
                )

        # 점수 계산 담당
        self.calculator = CuriosityCalculator()
        # 점수 → 행동 결정 담당
        self.policy = CuriosityPolicy()

        self.sub_perception = self.create_subscription(
            SemanticLabel,
            '/perception/scene_data',
            self.perception_callback,
            10
        )

        # from odi_interfaces.msg import CuriosityDecision
        #
        # self.pub_decision = self.create_publisher(
        #     CuriosityDecision,
        #     '/curiosity/decision',
        #     10
        # )

        self.get_logger().info('==========================================')
        self.get_logger().info('Curiosity Engine Node initialized')
        self.get_logger().info('Waiting for perception data...' )
        self.get_logger().info('==========================================')

    # ============================================================
    # Perception Callback
    # ============================================================
    def perception_callback(self, msg: SemanticLabel):
        self.get_logger().info('------------------------------------------')
        self.get_logger().info('[PERCEPTION] SemanticLabel received')

        # ========================================================
        # Step 1. 인지 데이터 확인
        # ========================================================
        self.get_logger().info(f'Object Name     : {msg.object_name}')
        self.get_logger().info(f'Primary Color   : {msg.object_primary_color}')
        self.get_logger().info(f'Secondary Color : {msg.object_secondary_color}' )
        self.get_logger().info(f'Material        : {msg.object_material}')
        self.get_logger().info(f'Shape           : {msg.object_shape}')
        self.get_logger().info(f'Condition       : {msg.object_condition}')

        # ========================================================
        # Step 2. ObjectCandidate 생성
        # ========================================================
        #
        # 🔴 수정된 부분
        #
        # 기존에는:
        #
        # track_id
        # confidence
        #
        # 를 사용했지만 SemanticLabel.msg에 존재하지 않는다.
        #
        # 따라서 현재는 실제 존재하는 데이터만 사용한다.
        #

        candidate = ObjectCandidate(
            object_name=msg.object_name,
            primary_color=msg.object_primary_color,
            secondary_color=msg.object_secondary_color,
            material=msg.object_material,
            shape=msg.object_shape,
            condition=msg.object_condition)
        # ========================================================
        # Step 3. 임시 Memory DB 조회
        # ========================================================
        #
        # 🔴 수정된 부분
        #
        # 예전:
        #
        # memory_db[track_id]
        #
        # 현재:
        #
        # object 특징을 조합한 임시 Key 사용
        #
        # 실제 World Memory Node가 완성되면
        # 이 부분은 World Memory에 조회 요청하는 구조로 변경한다.
        #

        memory_key = self.make_memory_key(candidate)

        # --------------------------------------------------------
        # 처음 본 객체
        # --------------------------------------------------------

        if memory_key not in self.memory_db:

            self.memory_db[memory_key] = MemoryInfo(
                visit_count=0,
                is_new=True
            )

            self.get_logger().info(
                f'[MEMORY] New object detected'
            )

        # --------------------------------------------------------
        # 기존에 본 객체
        # --------------------------------------------------------

        else:

            self.get_logger().info(
                f'[MEMORY] Existing object found'
            )

        memory = self.memory_db[memory_key]

        # ========================================================
        # Step 4. Curiosity Score 계산
        # ========================================================

        calc_result = self.calculator.calculate_score(
            candidate,
            memory
        )

        # ========================================================
        # Step 5. 행동 결정
        # ========================================================
        #
        # 실제 기준값은 policy.py에서 관리한다.
        #

        decision = self.policy.decide_action(calc_result['score'])

        # ========================================================
        # Step 6. Memory 업데이트
        # ========================================================
        #
        # 현재는 테스트용 DB이므로
        # 여기서 방문 횟수와 객체 정보를 업데이트한다.
        #
        # ⚠️ 실제 DB가 연결되면
        # 이 역할은 world_memory_node가 담당한다.
        #

        self.update_memory(memory, candidate)

        # ========================================================
        # Step 7. 결과 로그
        # ========================================================

        self.get_logger().info('==========================================')
        self.get_logger().info('[CURIOSITY RESULT]')
        self.get_logger().info(f'Object       : {candidate.object_name}')
        self.get_logger().info(f'Memory Key   : {memory_key}')
        self.get_logger().info(f'Visit Count  : {memory.visit_count}')

        # calculator.py에서 계산한 값
        if 'novelty' in calc_result:
            self.get_logger().info(f'Novelty      : {calc_result["novelty"]}')

        if 'uncertainty' in calc_result:
            self.get_logger().info(f'Uncertainty  : {calc_result["uncertainty"]}')

        if 'change' in calc_result:
            self.get_logger().info(f'Change       : {calc_result["change"]}')

        self.get_logger().info(f'Curiosity    : {calc_result["score"]}')
        self.get_logger().info(f'Decision     : {decision}')
        self.get_logger().info('==========================================')

    # ============================================================
    # Memory Key 생성
    # ============================================================

    def make_memory_key(
        self,
        candidate: ObjectCandidate
    ) -> str:

        """
        현재 프로토타입에서 사용하는 임시 Memory Key.

        track_id가 없기 때문에 객체의 의미적 특징을
        조합해서 동일한 객체를 임시로 찾는다.

        실제 World Memory가 구현되면
        이 함수는 제거될 예정이다.
        """

        return (
            f'{candidate.object_name}|'
            f'{candidate.primary_color}|'
            f'{candidate.secondary_color}|'
            f'{candidate.material}|'
            f'{candidate.shape}'
        )

    # ============================================================
    # Memory 업데이트
    # ============================================================

    def update_memory(
        self,
        memory: MemoryInfo,
        candidate: ObjectCandidate
    ):

        """
        현재는 테스트용 Memory 업데이트.

        실제 DB가 연결되면 world_memory_node가
        담당하게 된다.
        """

        # --------------------------------------------------------
        # 방문 횟수 증가
        # --------------------------------------------------------

        memory.visit_count += 1

        # --------------------------------------------------------
        # 더 이상 신규 객체가 아님
        # --------------------------------------------------------

        memory.is_new = False

        # --------------------------------------------------------
        # 현재 객체 특징 저장
        # --------------------------------------------------------

        memory.primary_color = candidate.primary_color
        memory.secondary_color = candidate.secondary_color
        memory.material = candidate.material
        memory.shape = candidate.shape
        memory.condition = candidate.condition

        self.get_logger().info(
            f'[MEMORY UPDATE] '
            f'visit_count={memory.visit_count}'
        )

    # ============================================================
    # Curiosity Decision Publisher
    # ============================================================

    # 현재는 테스트 단계라 주석 처리.
    #
    # 나중에 Behavior Executive와 연결할 때 사용한다.
    #
    # def publish_decision(
    #     self,
    #     score: float,
    #     decision: str
    # ):
    #
    #     dec_msg = CuriosityDecision()
    #
    #     dec_msg.score = score
    #     dec_msg.decision = decision
    #
    #     self.pub_decision.publish(dec_msg)


# ================================================================
# Main
# ================================================================


def main(args=None):
    rclpy.init(args=args)
    node = CuriosityEngineNode()

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass

    finally:
        node.destroy_node()

        if rclpy.ok():
            rclpy.shutdown()

# ===============================================================
# Python Entry Point
# ================================================================

if __name__ == '__main__':

    main()