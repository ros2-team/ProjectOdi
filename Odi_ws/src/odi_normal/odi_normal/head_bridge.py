"""Run on the Raspberry Pi. Real serial only; no simulated success responses."""
import json
import math
import time
from collections import deque

import serial
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from odi_interfaces.msg import MissionState


class HeadBridge(Node):
    def __init__(self):
        super().__init__('head_bridge')
        self.declare_parameter('enabled', False)
        self.declare_parameter('port', '/dev/odi_head')
        self.enabled = self.get_parameter('enabled').value
        self.port = self.get_parameter('port').value
        self.connection = None
        self.next_connect = 0.
        self.buffer = b''
        self.last_ping = 0.
        self.last_rx = 0.
        self.mission = ''
        self.session = ''
        self.mission_at = 0.
        self.normal_at = 0.
        self.serial_sequence = 0
        self.pending = None
        self.done = ''
        self.recent = deque(maxlen=32)
        self.ready = False
        self.pan = self.tilt = 90
        self.busy = False
        self.publisher = self.create_publisher(String, '/head/state', 10)
        self.create_subscription(String, '/head/command', self.command, 10)
        self.create_subscription(MissionState, '/mission/state', self.on_mission, 10)
        self.create_subscription(String, '/normal/status', self.on_normal, 10)
        self.create_timer(.05, self.tick)

    def on_mission(self, msg):
        if msg.state != self.mission and msg.state not in ('NORMAL', 'NORMAL_STOPPING'):
            if self.connection is not None:
                try:
                    self.write('H')  # Fail-safe neutral on external mode reset.
                except (serial.SerialException, OSError, RuntimeError):
                    pass
        self.mission, self.session = msg.state, msg.session_id
        self.mission_at = time.monotonic()

    def write(self, line):
        if self.connection is None:
            raise RuntimeError('Serial disconnected')
        self.connection.write((line+'\n').encode('ascii'))

    def on_normal(self, msg):
        try:
            if json.loads(msg.data).get('session_id') == self.session:
                self.normal_at = time.monotonic()
        except (ValueError, TypeError, AttributeError):
            pass

    def command(self, msg):
        try:
            request = json.loads(msg.data)
            identifier = request['id']
            if (not isinstance(identifier, str) or not 1 <= len(identifier) <= 64
                    or request.get('session_id') != self.session
                    or self.mission not in ('NORMAL', 'NORMAL_STOPPING')
                    or time.monotonic()-self.mission_at > 3
                    or not self.ready or time.monotonic()-self.last_rx > 1):
                return
            if identifier in self.recent:
                return
            pan, tilt = float(request['pan']), float(request['tilt'])
            beep = int(request.get('beep', 0))
            if not (math.isfinite(pan) and math.isfinite(tilt)
                    and 0 <= pan <= 180 and 0 <= tilt <= 180 and 0 <= beep <= 3):
                return
            # Firmware enforces calibrated limits too; out-of-range requests are rejected.
            self.serial_sequence += 1
            self.pending = (self.serial_sequence, identifier)
            self.done = ''
            self.write(f'M {self.serial_sequence} {round(pan)} {round(tilt)} {beep}')
            self.recent.append(identifier)
        except (ValueError, KeyError, TypeError, serial.SerialException, OSError, RuntimeError) as error:
            self.get_logger().warning('Head command rejected: '+str(error))

    def line(self, text):
        parts = text.split()
        if text == 'BOOT':
            self.ready = False
            self.done = ''
            self.pending = None
        if len(parts) == 5 and parts[0] == 'S':
            self.ready = parts[1] == '1'
            self.pan, self.tilt = int(parts[2]), int(parts[3])
            self.busy = parts[4] == '1'
            self.last_rx = time.monotonic()
        elif len(parts) == 2 and parts[0] == 'D':
            if self.pending and int(parts[1]) == self.pending[0]:
                self.done = self.pending[1]
                self.pending = None
        elif parts and parts[0] == 'E':
            self.get_logger().warning('Uno rejected command: '+text)

    def tick(self):
        now = time.monotonic()
        try:
            if self.enabled and self.connection is None and now >= self.next_connect:
                self.next_connect = now+3
                self.connection = serial.Serial(self.port, 115200, timeout=0, write_timeout=.1)
                self.buffer = b''
                self.ready = False
                self.done = ''
                self.pending = None
                self.recent.clear()
            if self.connection is not None:
                # Do not keep the Uno watchdog alive after the mission source disappears.
                alive = (self.mission not in ('NORMAL', 'NORMAL_STOPPING') or now-self.normal_at < 3)
                if now-self.last_ping >= .4 and now-self.mission_at < 3 and alive:
                    self.write('P')
                    self.last_ping = now
                self.buffer += self.connection.read(min(4096, self.connection.in_waiting))
                if len(self.buffer) > 4096:
                    self.buffer = b''
                while b'\n' in self.buffer:
                    line, self.buffer = self.buffer.split(b'\n', 1)
                    try:
                        self.line(line.decode('ascii').strip())
                    except (UnicodeError, ValueError):
                        pass
        except (serial.SerialException, OSError) as error:
            self.get_logger().warning('Uno unavailable: '+str(error))
            if self.connection:
                self.connection.close()
            self.connection = None
            self.ready = False
            self.done = ''
        msg = String()
        msg.data = json.dumps(dict(ready=self.ready and now-self.last_rx < 1,
                                   session_id=self.session,
                                   pan=self.pan, tilt=self.tilt, busy=self.busy, done=self.done))
        self.publisher.publish(msg)


def main(args=None):
    rclpy.init(args=args)
    node = HeadBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        if node.connection:
            node.connection.close()
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
