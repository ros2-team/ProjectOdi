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
        self.normal_stage = ''
        self.last_face = None
        self.face_at = 0.
        self.serial_sequence = 0
        self.pending = None
        self.done = ''
        self.recent = deque(maxlen=32)
        self.sound_recent = deque(maxlen=64)
        self.ready = False
        self.pan = self.tilt = 90
        self.busy = False
        self.publisher = self.create_publisher(String, '/head/state', 10)
        self.create_subscription(String, '/head/command', self.command, 10)
        self.create_subscription(String, '/head/sound', self.sound_command, 10)
        self.create_subscription(MissionState, '/mission/state', self.on_mission, 10)
        self.create_subscription(String, '/normal/status', self.on_normal, 10)
        self.create_timer(.05, self.tick)

    def on_mission(self, msg):
        previous_mission, previous_session = self.mission, self.session
        if msg.session_id != self.session:
            self.normal_stage = ''
            self.normal_at = 0.
        if msg.state != self.mission and msg.state not in ('NORMAL', 'NORMAL_STOPPING'):
            if self.connection is not None:
                try:
                    self.write('H')  # Fail-safe neutral on external mode reset.
                except (serial.SerialException, OSError, RuntimeError):
                    pass
        self.mission, self.session = msg.state, msg.session_id
        self.mission_at = time.monotonic()
        # Only actual transitions: repeated heartbeats/reconnects cannot replay cues.
        if msg.session_id and msg.session_id == previous_session:
            if previous_mission == 'PREPARING' and msg.state == 'EXPLORING':
                self.play_sound(1)
            elif previous_mission == 'RETURNING' and msg.state == 'REFLECTING':
                self.play_sound(7)

    def play_sound(self, sound):
        # B never changes servo goals, pending M/D acknowledgement, or motor lease.
        if (self.connection is None or not self.enabled or not self.ready
                or time.monotonic()-self.last_rx >= 1
                or time.monotonic()-self.mission_at >= 3):
            return
        try:
            self.write(f'B {sound}')
        except (serial.SerialException, OSError, RuntimeError) as error:
            self.get_logger().warning('Sound skipped: ' + str(error))

    def sound_command(self, msg):
        try:
            request = json.loads(msg.data)
            if not isinstance(request, dict):
                return
            identifier, sound = request.get('id'), request.get('sound')
            if (self.mission != 'EXPLORING' or not self.session
                    or request.get('session_id') != self.session
                    or not isinstance(identifier, str) or not 1 <= len(identifier) <= 64
                    or type(sound) is not int or sound not in (4, 5, 6)
                    or identifier in self.sound_recent):
                return
            self.sound_recent.append(identifier)
            self.play_sound(sound)
        except (ValueError, TypeError):
            pass

    def write(self, line):
        if self.connection is None:
            raise RuntimeError('Serial disconnected')
        self.connection.write((line+'\n').encode('ascii'))

    def on_normal(self, msg):
        try:
            status = json.loads(msg.data)
            if status.get('session_id') == self.session:
                self.normal_at = time.monotonic()
                self.normal_stage = status.get('stage', '')
        except (ValueError, TypeError, AttributeError):
            pass

    def display_face(self, now):
        if now-self.mission_at >= 3:
            return 6
        if self.mission == 'NORMAL_STOPPING':
            return 5
        if self.mission == 'NORMAL':
            if now-self.normal_at >= 3:
                return 6
            return {'REST': 1, 'DEPARTING': 2, 'MOVING': 2, 'BRAKING': 3, 'TRACKING': 3,
                    'SCAN_LEFT': 3, 'SCAN_RIGHT': 3, 'SCAN_CENTER': 3,
                    'LOOK_LEFT': 3, 'LOOK_RIGHT': 3, 'LOOK_CENTER': 3,
                    'DISCOVERED': 4, 'DISCOVERY_PAUSE': 4, 'GOODBYE': 4,
                    'NOD_DOWN': 4, 'NOD_UP': 4, 'STOPPING': 5}.get(self.normal_stage, 0)
        if self.mission == 'ERROR':
            return 6
        return {'': 0, 'IDLE': 8, 'PREPARING': 9, 'RESETTING': 9,
                'EXPLORING': 7, 'RETURNING': 5, 'REFLECTING': 9,
                'COMPLETED': 4}.get(self.mission, 0)

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
                    and 0 <= pan <= 180 and 0 <= tilt <= 180 and 0 <= beep <= 6):
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
            self.last_face = None
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
                self.last_face = None
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
                face = self.display_face(now)
                if face != self.last_face or now-self.face_at >= 1:
                    self.write(f'L {face}')
                    self.last_face, self.face_at = face, now
        except (serial.SerialException, OSError) as error:
            self.get_logger().warning('Uno unavailable: '+str(error))
            if self.connection:
                self.connection.close()
            self.connection = None
            self.ready = False
            self.done = ''
        msg = String()
        msg.data = json.dumps(dict(enabled=self.enabled, connected=self.connection is not None,
                                   ready=self.ready and now-self.last_rx < 1,
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



