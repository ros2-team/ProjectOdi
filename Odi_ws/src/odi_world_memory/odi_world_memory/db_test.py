import json
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from std_srvs.srv import Trigger
import mysql.connector

class DbTestNode(Node):
    def __init__(self):
        super().__init__('db_test_node')

        self.conn = mysql.connector.connect(
            host = 'localhost',
            user = 'ksj',
            password = '1234',
            database = 'Odi_DB',
        )
        self.cursor = self.conn.cursor(dictionary=True)
        self.get_logger().info('connect success')

        self.subscription = self.create_subscription(
            String, 
            'detected_object',
            self.insert_callback,
            10,
        )

        self.srv = self.create_service(
            Trigger, 
            'get_objects', 
            self.srv_callback
            )
        self.get_logger().info("srv 'get_objects' is ready")


    def insert_callback(self, msg):
        try:
            data = json.loads(msg.data)

            sql = """
                insert into detected_objects
                (object_name, object_primary_color, object_secondary_color,
                object_material, object_shape, object_condition, object_special_features, raw_json)
                values(%s, %s, %s, %s, %s, %s, %s, %s)
                """
            
            values = (
                data['object_name'],
                data['object_primary_color'],
                data['object_secondary_color'],
                data['object_material'],
                data['object_shape'],
                data['object_condition'],

                json.dumps(data['object_special_features'], ensure_ascii=False),
                json.dumps(data['raw_json'], ensure_ascii=False),

            )
            self.cursor.execute(sql, values)
            self.conn.commit()
            self.get_logger().info(f"insert success: {data['object_name']}")

        except Exception as e:
            self.get_logger().error(f"insert failed: {e}")


    def srv_callback(self, request, response):
        try:
            self.cursor.execute("select * from detected_objects")
            rows = self.cursor.fetchall()

            for row in rows:
                if row['object_special_features']:
                    row['object_special_features'] = json.loads(row['object_special_features'])

                if row['raw_json']:
                    row['raw_json'] = json.loads(row['raw_json'])

            response.success = True

            response.message = json.dumps(rows, ensure_ascii=False, default=str)
            self.get_logger().info(f"조회 {len(rows)}건 응답")

        except Exception as e:
            response.success = False
            response.message = str(e)
            self.get_logger().error(f"조회 실패: {e}")
        return response

    def destroy_node(self):
        self.cursor.close()
        self.conn.close()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = DbTestNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()