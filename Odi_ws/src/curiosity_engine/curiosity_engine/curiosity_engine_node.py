#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
import mysql.connector
from mysql.connector import Error

# ============================================================
# ROS2 Interface
# ============================================================
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
        # 1. MySQL DB 연결
        # ========================================================
        self.conn = None
        self.cursor = None

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
                self.get_logger().info('MySQL DB 연결 성공!!!!!!!!!!!!!!!!!!!!!')

        except Error as e:
            self.get_logger().error(f'MySQL connection failed: {e}')
            self.conn = None
            self.cursor = None

        # ========================================================
        # 2. DB 테이블 확인
        # ========================================================
        if self.cursor is not None:
            try:
                self.cursor.execute("SHOW TABLES")
                tables = self.cursor.fetchall()
                for table in tables:
                    self.get_logger().info(f'[DB TABLE] {table}')
            except Error as e:
                self.get_logger().error(f'Table query failed: {e}')

        # ========================================================
        # 3. Curiosity 계산 모듈
        # ========================================================
        self.calculator = CuriosityCalculator()
        self.policy = CuriosityPolicy()

        # ========================================================
        # 4. Perception 데이터 구독
        # ========================================================
        self.sub_perception = self.create_subscription(
            SemanticLabel,
            '/perception/scene_data',
            self.perception_callback,
            10
        )

        self.get_logger().info('==========================================')
        self.get_logger().info('Curiosity Engine Node initialized')
        self.get_logger().info('Waiting for perception data...')
        self.get_logger().info('==========================================')

    # ============================================================
    # Perception Callback
    # ============================================================
    def perception_callback(self, msg: SemanticLabel):
        self.get_logger().info('------------------------------------------')
        self.get_logger().info('[PERCEPTION] SemanticLabel received')

        # 인지 데이터 출력
        self.get_logger().info(f'Object Name     : {msg.object_name}')
        self.get_logger().info(f'Primary Color   : {msg.object_primary_color}')
        self.get_logger().info(f'Secondary Color : {msg.object_secondary_color}')
        self.get_logger().info(f'Material        : {msg.object_material}')
        self.get_logger().info(f'Shape           : {msg.object_shape}')
        self.get_logger().info(f'Condition       : {msg.object_condition}')

        # 계산용 ObjectCandidate 생성
        candidate = ObjectCandidate(
            object_name=msg.object_name,
            primary_color=msg.object_primary_color,
            secondary_color=msg.object_secondary_color,
            material=msg.object_material,
            shape=msg.object_shape,
            condition=msg.object_condition
        )

        # World Memory DB 조회 (유사도 기반 비교)
        memory = self.get_memory_from_db(candidate)

        if memory is None:
            self.get_logger().error('[MEMORY] Failed to retrieve memory from DB')
            return

        # 과거 정보 + 현재 정보로 호기심 계산
        calc_result = self.calculator.calculate_score(candidate, memory)

        # 행동 결정
        decision = self.policy.decide_action(calc_result['score'])

        # 결과 로그 출력
        self.get_logger().info('==========================================')
        self.get_logger().info('[CURIOSITY RESULT]')
        self.get_logger().info(f'Object       : {candidate.object_name}')
        self.get_logger().info(f'Visit Count  : {memory.visit_count}')

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
    # World Memory DB 조회
    # ============================================================
    def get_memory_from_db(self, candidate: ObjectCandidate):
        if self.cursor is None:
            self.get_logger().error('[DB] Cursor is not available')
            return None

        # 1. DB 후보 전체 조회
        find_sql = "SELECT * FROM detected_objects"

        try:
            self.cursor.execute(find_sql)
            rows = self.cursor.fetchall()

            # DB가 비어있는 경우
            if not rows:
                self.get_logger().info('[MEMORY] DB is empty. New object.')
                return MemoryInfo(visit_count=0, is_new=True)

            # 2. 후보 하나씩 비교하여 최고 유사도 탐색
            best_similarity = 0.0
            best_row = None

            for row in rows:
                # DB에 저장된 객체를 비교용 ObjectCandidate로 변환
                db_candidate = ObjectCandidate(
                    object_name=row['object_name'],
                    primary_color=row['object_primary_color'],
                    secondary_color=row['object_secondary_color'],
                    material=row['object_material'],
                    shape=row['object_shape'],
                    condition=row['object_condition']
                )

                similarity = self.calculator.calculate_similarity(candidate, db_candidate)

                self.get_logger().info(
                    f'[MEMORY] {row["object_name"]} similarity={similarity:.2f}'
                )

                if similarity > best_similarity:
                    best_similarity = similarity
                    best_row = row

            # 3. 임계값(Threshold) 판정
            similarity_threshold = 0.80

            if best_row is not None and best_similarity >= similarity_threshold:
                self.get_logger().info('[MEMORY] Existing object found')
                self.get_logger().info(f'[MEMORY] best_similarity={best_similarity:.2f}')
                self.get_logger().info(f'[MEMORY] matched_object={best_row["object_name"]}')

                # 방문 횟수 계산 (동일 속성 완전 일치 row 수 조회)
                count_sql = """
                    SELECT COUNT(*) AS visit_count
                    FROM detected_objects
                    WHERE object_name = %s
                      AND object_primary_color = %s
                      AND object_secondary_color = %s
                      AND object_material = %s
                      AND object_shape = %s
                """
                count_values = (
                    best_row['object_name'],
                    best_row['object_primary_color'],
                    best_row['object_secondary_color'],
                    best_row['object_material'],
                    best_row['object_shape']
                )

                self.cursor.execute(count_sql, count_values)
                count_row = self.cursor.fetchone()

                visit_count = count_row['visit_count'] if count_row is not None else 1

                self.get_logger().info(f'[MEMORY] visit_count={visit_count}')

                memory = MemoryInfo(visit_count=visit_count, is_new=False)
                memory.object_name = best_row['object_name']
                memory.primary_color = best_row['object_primary_color']
                memory.secondary_color = best_row['object_secondary_color']
                memory.material = best_row['object_material']
                memory.shape = best_row['object_shape']
                memory.condition = best_row['object_condition']
                memory.similarity = best_similarity

                return memory

            # Threshold 미만인 경우
            self.get_logger().info('[MEMORY] New object found')
            self.get_logger().info(f'[MEMORY] best_similarity={best_similarity:.2f}')

            return MemoryInfo(visit_count=0, is_new=True)

        except Error as e:
            self.get_logger().error(f'[DB] Memory query failed: {e}')
            return None

    # ============================================================
    # Node 종료
    # ============================================================
    def destroy_node(self):
        if self.cursor is not None:
            try:
                self.cursor.close()
            except Exception as e:
                self.get_logger().error(f'[DB] Cursor close failed: {e}')

        if self.conn is not None:
            try:
                if self.conn.is_connected():
                    self.conn.close()
                    self.get_logger().info('[DB] MySQL connection closed')
            except Exception as e:
                self.get_logger().error(f'[DB] Connection close failed: {e}')

        super().destroy_node()


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


if __name__ == '__main__':
    main()