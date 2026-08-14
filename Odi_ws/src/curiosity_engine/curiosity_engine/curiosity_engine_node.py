#!/usr/bin/env python3

import rclpy
from rclpy.node import Node
import mysql.connector
from mysql.connector import Error

from odi_interfaces.msg import CuriosityDecision
from odi_interfaces.srv import EvaluateCuriosity
from odi_interfaces.msg import SemanticLabel

from curiosity_engine.core import (
    ObjectCandidate,
    MemoryInfo,
    CuriosityCalculator,
    CuriosityPolicy
)
from curiosity_engine.core import weights as W


class CuriosityEngineNode(Node):

    def __init__(self):
        super().__init__('curiosity_engine_node')

        # DB 접속 정보는 파라미터로 뺀다 (자격증명 하드코딩 방지)
        self.declare_parameter('db_host', '192.168.0.20')
        self.declare_parameter('db_port', 3306)
        self.declare_parameter('db_user', 'yyj')
        self.declare_parameter('db_password', '1234')
        self.declare_parameter('db_name', 'Odi_DB')

        self.conn = None
        self.cursor = None
        self.init_db_connection()

        self.calculator = CuriosityCalculator()
        self.policy = CuriosityPolicy()

        self.srv_curiosity = self.create_service(
            EvaluateCuriosity,
            '/curiosity/evaluate',
            self.evaluate_curiosity_callback
        )

        self.sub_perception = self.create_subscription(
            SemanticLabel,
            '/perception/scene_data',
            self.perception_callback,
            10
        )

        self.get_logger().info('==========================================')
        self.get_logger().info('Curiosity Engine 준비완!!!!!서비스 요청 기다림 ')
        self.get_logger().info('==========================================')

    # ============================================================
    # DB 연결
    # ============================================================

    def init_db_connection(self):
        try:
            self.conn = mysql.connector.connect(
                host=self.get_parameter('db_host').value,
                port=self.get_parameter('db_port').value,
                user=self.get_parameter('db_user').value,
                password=self.get_parameter('db_password').value,
                database=self.get_parameter('db_name').value,
                autocommit=True   # ★ 없으면 첫 SELECT 스냅샷에 갇혀
                                  #   다른 노드가 INSERT한 행이 영원히 안 보인다
            )
            self.cursor = self.conn.cursor(dictionary=True)

            if self.conn.is_connected():
                self.get_logger().info('MySQL DB 연결 성공')

        except Error as e:
            self.get_logger().error(f'MySQL connection failed: {e}')
            self.conn = None
            self.cursor = None

    def ensure_connection(self):
        """조회 직전에 커넥션 살아있는지 확인하고 필요하면 재연결."""
        if self.conn is None:
            self.init_db_connection()
            return self.cursor is not None
        try:
            self.conn.ping(reconnect=True, attempts=3, delay=1)
            return True
        except Error as e:
            self.get_logger().error(f'[DB] ping failed: {e}')
            return False

    # ============================================================
    # 공통 평가 로직 (서비스/토픽 양쪽에서 재사용)
    # ============================================================

    def evaluate(self, candidate: ObjectCandidate):
        """반환: (memory, calc_result, action) 또는 실패 시 None"""
        memory = self.get_memory_from_db(candidate)
        if memory is None:
            return None

        calc_result = self.calculator.calculate_score(candidate, memory)
        action = self.policy.decide_action(calc_result['score'])

        self.log_result(candidate, memory, calc_result, action)
        return memory, calc_result, action

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

    # ============================================================
    # Service Callback
    # ============================================================

    def evaluate_curiosity_callback(self, request, response):
        self.get_logger().info('[SERVICE] 새로운 물건 평가 요청 들어옴')

        encounter_data = request.encounter
        label = encounter_data.label

        candidate = ObjectCandidate(
            object_name=label.object_name,
            primary_color=label.object_primary_color,
            secondary_color=label.object_secondary_color,
            material=label.object_material,
            shape=label.object_shape,
            condition=label.object_condition
        )

        result = self.evaluate(candidate)
        if result is None:
            response.success = False
            response.message = 'DB Memory retrieval failed'
            self.get_logger().error('[SERVICE] DB Memory retrieval failed')
            return response

        memory, calc_result, action_decision = result

        decision_msg = CuriosityDecision()
        decision_msg.detection_id = str(getattr(encounter_data, 'detection_id', ''))
        decision_msg.curiosity_score = float(calc_result['score'])
        decision_msg.similarity_score = float(memory.similarity)
        decision_msg.action = str(action_decision)
        decision_msg.reason = (
            f'Novelty={calc_result["novelty"]:.2f}(x{calc_result["decay"]:.2f}), '
            f'Change={calc_result["change"]:.2f}, '
            f'Similarity={memory.similarity:.2f}, '
            f'Visits={memory.visit_count}'
        )
        decision_msg.novel_features = list(calc_result['novel_features'])
        decision_msg.duplicated_features = list(calc_result['duplicated_features'])
        decision_msg.compared_record_count = int(memory.compared_record_count)
        decision_msg.evaluated_at = self.get_clock().now().to_msg()

        response.success = True
        response.decision = decision_msg
        response.message = '호기심 평가 완료ㅇㅇ'
        return response

    # ============================================================
    # 인지 test callback
    # ============================================================

    def perception_callback(self, msg):
        candidate = ObjectCandidate(
            object_name=msg.object_name,
            primary_color=msg.object_primary_color,
            secondary_color=msg.object_secondary_color,
            material=msg.object_material,
            shape=msg.object_shape,
            condition=msg.object_condition
        )

        if self.evaluate(candidate) is None:
            self.get_logger().error('[CURIOSITY] DB Memory retrieval failed')

    # ============================================================
    # DB 기억 조회
    # ============================================================

    def get_memory_from_db(self, candidate: ObjectCandidate):
        """
        1) 전체 기록과 유사도를 비교해 best match를 찾는다
        2) best match가 임계값을 넘으면 '같은 개체'로 판정
        3) 같은 개체의 '가장 최근 기록'을 가져와 change 비교 기준으로 삼는다

        3번이 핵심 변경점.
        best match는 '가장 닮은 행'이라 차이가 최소가 되도록 선택된 것이므로
        변화 감지의 기준으로 쓰면 안 된다.
        """
        if self.cursor is None or not self.ensure_connection():
            self.get_logger().error('[DB] Cursor is not available')
            return None

        try:
            self.cursor.execute('SELECT * FROM detected_objects')
            rows = self.cursor.fetchall()

            if not rows:
                self.get_logger().info('[MEMORY] DB is empty. New object.')
                return MemoryInfo(visit_count=0, is_new=True,
                                  similarity=0.0, compared_record_count=0)

            # --- 1) best match 탐색 ---
            best_similarity = 0.0
            best_row = None

            for row in rows:
                db_record = self.row_to_memory(row)
                similarity = self.calculator.calculate_similarity(candidate, db_record)

                self.get_logger().debug(
                    f'[MEMORY] id={row["id"]} {row["object_name"]} sim={similarity:.2f}'
                )

                if similarity > best_similarity:
                    best_similarity = similarity
                    best_row = row

            compared_record_count = len(rows)

            # --- 2) 신규 판정 ---
            if best_row is None or best_similarity < W.IDENTITY_THRESHOLD:
                self.get_logger().info(
                    f'[MEMORY] New object (best_similarity={best_similarity:.2f})'
                )
                return MemoryInfo(
                    visit_count=0,
                    is_new=True,
                    similarity=best_similarity,
                    compared_record_count=compared_record_count
                )

            # --- 3) 기존 개체: 정체성으로 방문 횟수 + 최신 기록 조회 ---
            self.get_logger().info(
                f'[MEMORY] Existing object id={best_row["id"]} '
                f'sim={best_similarity:.2f}'
            )

            identity = (
                best_row['object_name'],
                best_row['object_material'],
                best_row['object_shape'],
            )

            # <=> 는 MySQL의 NULL-safe equal.
            # NULL <=> NULL 이 TRUE라서 'OR IS NULL' 나열이 필요 없다.
            identity_where = """
                WHERE object_name <=> %s
                  AND object_material <=> %s
                  AND object_shape <=> %s
            """

            self.cursor.execute(
                f'SELECT COUNT(*) AS visit_count FROM detected_objects {identity_where}',
                identity
            )
            count_row = self.cursor.fetchone()
            visit_count = count_row['visit_count'] if count_row else 1

            # 같은 개체의 가장 최근 기록 = change 비교 기준
            self.cursor.execute(
                f'SELECT * FROM detected_objects {identity_where} ORDER BY id DESC LIMIT 1',
                identity
            )
            latest_row = self.cursor.fetchone() or best_row

            memory = self.row_to_memory(latest_row)
            memory.is_new = False
            memory.visit_count = visit_count
            memory.similarity = best_similarity
            memory.compared_record_count = compared_record_count

            self.get_logger().info(
                f'[MEMORY] visit_count={visit_count}, '
                f'latest_record_id={latest_row["id"]}'
            )
            return memory

        except Error as e:
            self.get_logger().error(f'[DB] Memory query failed: {e}')
            return None

    @staticmethod
    def row_to_memory(row) -> MemoryInfo:
        """DB row → MemoryInfo 변환 (컬럼명 매핑을 한 곳에 모은다)"""
        return MemoryInfo(
            visit_count=0,
            is_new=False,
            object_name=row['object_name'],
            primary_color=row['object_primary_color'],
            secondary_color=row['object_secondary_color'],
            material=row['object_material'],
            shape=row['object_shape'],
            condition=row['object_condition'],
            record_id=row.get('id')
        )

    # ============================================================

    def destroy_node(self):
        if self.cursor is not None:
            try:
                self.cursor.close()
            except Exception as e:
                self.get_logger().error(f'[DB] Cursor close failed: {e}')

        if self.conn is not None and self.conn.is_connected():
            try:
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