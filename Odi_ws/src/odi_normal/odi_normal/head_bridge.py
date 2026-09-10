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
    # Face codes must match the enum in firmware/odi_head/odi_head.ino.
    FACE_SLEEP, FACE_NEUTRAL, FACE_DRIVE, FACE_CURIOUS = 0, 1, 2, 3
    FACE_HAPPY, FACE_TIRED, FACE_ERROR, FACE_THINK = 4, 5, 6, 7
    STAGE_FACES = {'WAIT_HEAD': FACE_NEUTRAL, 'HOMING': FACE_NEUTRAL,
                   'RETURN_HEAD': FACE_NEUTRAL, 'REST': FACE_NEUTRAL,
                   'MOVING': FACE_DRIVE,
                   'BRAKING': FACE_CURIOUS, 'TRACKING': FACE_CURIOUS,
                   'NOD_DOWN': FACE_HAPPY, 'NOD_UP': FACE_HAPPY,
                   'STOPPING': FACE_TIRED}
    MISSION_FACES = {'IDLE': FACE_SLEEP, 'EXPLORING': FACE_DRIVE,
                     'PREPARING': FACE_THINK, 'REFLECTING': FACE_THINK,
                     'RESETTING': FACE_THINK, 'COMPLETED': FACE_HAPPY,
                     'RETURNING': FACE_TIRED, 'NORMAL_STOPPING': FACE_TIRED,
                     'ERROR': FACE_ERROR}

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
        self.stage = ''
        self.face = None
        self.face_at = 0.
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
            status = json.loads(msg.data)
            if status.get('session_id') == self.session:
                self.normal_at = time.monotonic()
                self.stage = status.get('stage') or ''
        except (ValueError, TypeError, AttributeError):
            pass

    def face_for(self):
        """Expression for the current driving state; the stage wins in normal mode."""
        if self.mission == 'NORMAL':
            return self.STAGE_FACES.get(self.stage, self.FACE_NEUTRAL)
        return self.MISSION_FACES.get(self.mission, self.FACE_SLEEP)

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
            self.face = None  # A reset Uno lost its CGRAM and its glass.
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
                self.face = None
                self.recent.clear()
            if self.connection is not None:
                # Do not keep the Uno watchdog alive after the mission source disappears.
                alive = (self.mission not in ('NORMAL', 'NORMAL_STOPPING') or now-self.normal_at < 3)
                if now-self.last_ping >= .4 and now-self.mission_at < 3 and alive:
                    self.write('P')
                    self.last_ping = now
                # Faces are not gated on NORMAL: exploration gets one too. They
                # stop with the mission heartbeat so a dead stack sleeps the face.
                if now-self.mission_at < 3:
                    face = self.face_for()
                    if face != self.face or now-self.face_at > 2:
                        self.write(f'F {face}')
                        self.face, self.face_at = face, now
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
