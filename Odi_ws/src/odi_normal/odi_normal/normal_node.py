"""Exclusive normal-mode controller. No direct /cmd_vel and no diary pipeline."""
import json
import math
import time
import uuid
from typing import TypedDict, cast

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from std_msgs.msg import String
from nav_msgs.msg import Odometry
from sensor_msgs.msg import BatteryState
from rclpy.qos import qos_profile_sensor_data
from odi_interfaces.msg import MissionState, DetectedObject
from odi_interfaces.action import Explore
from odi_normal.attention import Attention, tracking_angles


class NormalParameters(TypedDict):
    image_width: int
    image_height: int
    target_classes: list[str]
    confidence: float
    minimum_area_ratio: float
    cooldown_sec: float
    rest_sec: float
    move_timeout_sec: float
    track_timeout_sec: float
    pan_sign: float
    tilt_sign: float
    pan_min: float
    pan_max: float
    tilt_min: float
    tilt_max: float
    pan_home: float
    tilt_home: float
    nod_degrees: float


class NormalModeNode(Node):
    def __init__(self):
        super().__init__('normal_node')
        defaults = NormalParameters(image_width=640, image_height=480,
                        target_classes=['bottle', 'backpack', 'cup'],
                        confidence=0.6, minimum_area_ratio=0.02, cooldown_sec=60.0,
                        rest_sec=3.0, move_timeout_sec=30.0, track_timeout_sec=6.0,
                        pan_sign=-1.0, tilt_sign=1.0,
                        pan_min=40.0, pan_max=140.0, tilt_min=0.0, tilt_max=100.0,
                        pan_home=84.0, tilt_home=75.0, nod_degrees=6.0)
        for key, value in defaults.items():
            self.declare_parameter(key, value)
        values = {k:self.get_parameter(k).value for k in defaults}
        for key, default in defaults.items():
            value = values[key]
            if type(value) is not type(default):
                raise ValueError(f'Invalid type for parameter {key}')
            if isinstance(value, list) and not all(isinstance(item, str) for item in value):
                raise ValueError(f'Parameter {key} must contain strings')
        # Values have been checked against the typed defaults above.
        self.p = cast(NormalParameters, values)
        for lower, home, upper in (
                (self.p['pan_min'], self.p['pan_home'], self.p['pan_max']),
                (self.p['tilt_min'], self.p['tilt_home'], self.p['tilt_max'])):
            if not 0 <= lower <= home <= upper <= 180:
                raise ValueError('Invalid head limits')
        if self.p['image_width'] <= 0 or self.p['image_height'] <= 0:
            raise ValueError('Image dimensions must be positive')
        self.nav = ActionClient(self, Explore, '/explore')
        self.head_pub = self.create_publisher(String, '/head/command', 10)
        self.events = self.create_publisher(String, '/normal/event', 10)
        self.status_pub = self.create_publisher(String, '/normal/status', 10)
        self.create_subscription(MissionState, '/mission/state', self.on_mission, 10)
        self.create_subscription(DetectedObject, '/yolo/detection', self.on_detection, 10)
        self.create_subscription(String, '/head/state', self.on_head, 10)
        self.create_subscription(Odometry, '/odom', self.on_odom, qos_profile_sensor_data)
        self.create_subscription(BatteryState, '/battery_state', self.on_battery, qos_profile_sensor_data)
        self.session = ''
        self.stage = 'OFF'
        self.mission_seen = 0.0
        self.head = {}
        self.head_seen = 0.0
        self.motion = None
        self.stationary_since = None
        self.send_future = self.result_future = self.goal = None
        self.cancel_future = None
        self.cancel_at = 0.0
        self.head_id = ''
        self.head_touched = False
        self.stop_requested = False
        self.fault_detail = ''
        self.target = None
        self.target_seen = 0.0
        self.last_status = 0.0
        self.create_timer(0.1, self.tick)

    def on_mission(self, msg):
        self.mission_seen = time.monotonic()
        if msg.state == 'NORMAL' and self.stage == 'OFF' and msg.session_id != self.session:
            self.session = msg.session_id
            self.attention = Attention(self.p['image_width'], self.p['image_height'],
                self.p['target_classes'], self.p['confidence'], self.p['minimum_area_ratio'],
                self.p['cooldown_sec'])
            self.stop_requested = False
            self.fault_detail = ''
            self.head_touched = False
            self.target = None
            self.set_stage('WAIT_HEAD', 10.0)
        elif self.stage != 'OFF' and (msg.state != 'NORMAL' or msg.session_id != self.session):
            self.stop_requested = True

    def on_head(self, msg):
        try:
            data = json.loads(msg.data)
            if not isinstance(data, dict):
                return
            self.head = data
            self.head_seen = time.monotonic()
        except (ValueError, TypeError):
            pass

    def on_odom(self, msg):
        t = msg.twist.twist
        now = time.monotonic()
        moving = not (math.isfinite(t.linear.x) and math.isfinite(t.linear.y)
                      and math.isfinite(t.angular.z) and
                      math.hypot(t.linear.x, t.linear.y) < .02 and abs(t.angular.z) < .05)
        if moving or self.motion is None or now-self.motion > .5:
            self.stationary_since = None
        elif self.stationary_since is None:
            self.stationary_since = now
        self.motion = now

    def on_battery(self, msg):
        if self.stage != 'OFF' and ((math.isfinite(msg.percentage) and 0 <= msg.percentage <= .15)
                                   or msg.power_supply_status == BatteryState.POWER_SUPPLY_STATUS_CHARGING):
            self.fault('Battery low or charging; stopping normal mode')

    def stationary(self):
        now = time.monotonic()
        return (self.motion is not None and now-self.motion < .5 and
                self.stationary_since is not None and now-self.stationary_since >= .5)

    def on_detection(self, msg):
        if self.stage in ('OFF', 'WAIT_HEAD', 'STOPPING'):
            return
        now = time.monotonic()
        if not msg.detection_id.startswith(self.session + ':'):
            return
        self.attention.observe(msg, now)
        # Cooldown suppresses new discoveries, but must not freeze the active target.
        if (self.target is not None and msg.detection_id == self.target.detection_id
                and msg.class_name == self.target.class_name
                and math.isfinite(msg.confidence) and msg.confidence >= self.p['confidence']
                and 0 <= msg.center_x < self.p['image_width']
                and 0 <= msg.center_y < self.p['image_height']
                and msg.width > 0 and msg.height > 0):
            self.target = msg
            self.target_seen = now

    def head_ready(self):
        return (time.monotonic()-self.head_seen < 1.0 and
                self.head.get('session_id') == self.session and
                self.head.get('ready') is True)

    def startup_problem(self):
        if not self.head_seen or time.monotonic()-self.head_seen >= 1.0:
            return '머리 제어 응답이 없어요. SBC의 head_bridge 실행과 ROS 연결을 확인해 주세요.'
        if self.head.get('enabled') is False:
            return '머리 제어가 비활성화되어 있어요. head_bridge의 enabled 설정을 확인해 주세요.'
        if self.head.get('connected') is False:
            return '머리 제어 보드에 연결하지 못했어요. USB 포트와 접근 권한을 확인해 주세요.'
        if self.head.get('session_id') != self.session:
            return '머리 제어기의 모드 정보가 일치하지 않아요. MissionState 수신을 확인해 주세요.'
        if self.head.get('ready') is not True:
            return '머리 제어 보드가 준비되지 않았어요. 펌웨어와 보드 상태를 확인해 주세요.'
        if not self.stationary():
            return '로봇의 정지 상태를 확인하지 못했어요. odom 수신과 실제 움직임을 확인해 주세요.'
        return ''

    def set_stage(self, stage: str, duration: float = 0.0):
        self.stage = stage
        self.deadline = time.monotonic()+duration
        self.get_logger().info('Normal mode: ' + stage)

    def event(self, name, detail=''):
        msg = String()
        msg.data = json.dumps(dict(session_id=self.session, event=name, detail=detail))
        self.events.publish(msg)

    def fault(self, detail):
        if not self.stop_requested:
            self.fault_detail = '[NORMAL_FAULT] ' + detail
            self.get_logger().error('Normal mode fault: ' + detail)
            self.event('FAULT', self.fault_detail)
        self.stop_requested = True

    def head_command(self, pan, tilt, beep=0):
        self.head_id = uuid.uuid4().hex
        msg = String()
        msg.data = json.dumps(dict(id=self.head_id, session_id=self.session,
                                   pan=pan, tilt=tilt, beep=beep))
        self.head_pub.publish(msg)
        self.head_sent = time.monotonic()
        self.head_touched = True
        return self.head_id

    def home(self):
        self.head_command(self.p['pan_home'], self.p['tilt_home'])

    def head_done(self):
        return self.head_ready() and self.head.get('done') == self.head_id

    def scan(self, side, beep=0):
        # Fixed +/-25 degree sweep, bounded by the calibrated servo limits.
        offset = {'LEFT': -25.0, 'RIGHT': 25.0, 'CENTER': 0.0}[side]
        pan = max(self.p['pan_min'], min(self.p['pan_max'], self.p['pan_home'] + offset))
        self.head_command(pan, self.p['tilt_home'], beep)
        self.set_stage('SCAN_' + side, 5)

    def discover(self, target, now):
        # A short surprised chirp precedes a bounded, stationary tracking phase.
        self.target, self.target_seen = target, now
        self.attention.handled_target(target, now)
        self.head_command(float(self.head['pan']), float(self.head['tilt']), 4)
        self.set_stage('DISCOVERED', 5)

    def say_goodbye(self):
        self.target = None
        self.head_command(self.p['pan_home'], self.p['tilt_home'], 6)
        self.set_stage('GOODBYE', 5)

    def start_roaming(self):
        if not self.nav.server_is_ready():
            self.fault('Exploration action server is unavailable')
            return
        request = Explore.Goal()
        request.session_id, request.mode = self.session, 'SHORT_ROAM'
        self.send_future = self.nav.send_goal_async(request)
        self.set_stage('MOVING', self.p['move_timeout_sec'])

    def nav_pending(self):
        return self.send_future is not None or self.goal is not None

    def poll_navigation(self):
        if self.send_future is not None and self.send_future.done():
            future, self.send_future = self.send_future, None
            handle = future.result()
            if handle is not None and handle.accepted:
                self.goal = handle
                self.result_future = handle.get_result_async()
            else:
                self.fault('Short movement goal rejected')
        if self.result_future is not None and self.result_future.done():
            result = self.result_future.result()
            self.result_future = self.goal = self.cancel_future = None
            if not self.stop_requested and self.stage == 'MOVING' and result.status != 4:
                self.fault('Short movement failed')

    def cancel_navigation(self):
        # Retain send_future: a late accepted goal must still be canceled.
        if self.goal is not None and time.monotonic()-self.cancel_at > 1.0:
            if self.cancel_future is None or self.cancel_future.done():
                self.cancel_future = self.goal.cancel_goal_async()
                self.cancel_at = time.monotonic()

    def stop_tick(self):
        self.cancel_navigation()
        if self.nav_pending():
            return
        # Missing hardware before any command is a failed startup, not a fake home ACK.
        if not self.head_touched:
            self.event('STOPPED', self.fault_detail or 'Normal mode stopped before startup')
            self.set_stage('OFF')
            return
        if not self.stationary():
            return
        if self.stage != 'STOPPING':
            self.set_stage('STOPPING')
            self.home()
        elif self.head_done():
            self.event('STOPPED', self.fault_detail or 'Normal mode stopped; camera centered')
            self.set_stage('OFF')
        elif self.head_ready() and time.monotonic()-self.head_sent > 5:
            self.home()

    def tick(self):
        if self.stage == 'OFF':
            return
        now = time.monotonic()
        try:
            self.poll_navigation()
            if now-self.mission_seen > 3:
                self.fault('Mission Manager heartbeat lost')
            if now-self.last_status > .5:
                msg = String()
                msg.data = json.dumps(dict(session_id=self.session, stage=self.stage,
                                          detail=self.fault_detail or (self.startup_problem() if self.stage == 'WAIT_HEAD' else '')))
                self.status_pub.publish(msg)
                self.last_status = now
            if self.stop_requested:
                self.stop_tick()
                return
            if self.stage == 'WAIT_HEAD':
                if self.head_ready() and self.stationary():
                    self.home()
                    self.set_stage('HOMING', 5)
                elif now > self.deadline:
                    self.fault(self.startup_problem() or '일반모드 준비 시간이 초과되었어요.')
                return
            if not self.head_ready():
                self.fault('Head bridge disconnected or firmware disabled')
                return
            if self.stage not in ('MOVING', 'BRAKING') and not self.stationary():
                self.fault('Unexpected base movement during head expression')
                return
            if self.stage in ('HOMING', 'RETURN_HEAD'):
                if self.head_done():
                    self.target = None
                    self.set_stage('REST', self.p['rest_sec'])
                elif now > self.deadline:
                    self.fault('Camera centering acknowledgement timed out')
            elif self.stage == 'REST':
                target = self.attention.candidate(now)
                if target:
                    self.discover(target, now)
                elif now > self.deadline:
                    if not self.nav.server_is_ready():
                        self.fault('Exploration action server is unavailable')
                        return
                    # One phrase announces departure, while still stationary.
                    self.head_command(self.p['pan_home'], self.p['tilt_home'], 1)
                    self.set_stage('DEPARTING', 5)
            elif self.stage == 'DEPARTING':
                if self.head_done():
                    self.start_roaming()
                elif now > self.deadline:
                    self.fault('Departure acknowledgement timed out')
            elif self.stage == 'MOVING':
                if self.attention.candidate(now) or now > self.deadline or not self.nav_pending():
                    self.set_stage('BRAKING', 10)
                    self.cancel_navigation()
            elif self.stage == 'BRAKING':
                self.cancel_navigation()
                if not self.nav_pending() and self.stationary():
                    # Never turn the camera until navigation has terminated.
                    self.scan('LEFT', 2)
                elif now > self.deadline:
                    self.fault('Waiting for navigation termination and base stop')
            elif self.stage.startswith('SCAN_'):
                if self.head_done():
                    # Admit only stable detections collected after the head settles.
                    self.attention.samples.clear()
                    self.attention.latest = None
                    self.set_stage('LOOK_' + self.stage[5:], 1.5)
                elif now > self.deadline:
                    self.fault('Camera scan acknowledgement timed out')
            elif self.stage.startswith('LOOK_'):
                target = self.attention.candidate(now)
                if target:
                    self.discover(target, now)
                elif now > self.deadline:
                    side = self.stage[5:]
                    if side == 'LEFT':
                        self.scan('RIGHT')
                    elif side == 'RIGHT':
                        self.scan('CENTER')
                    else:
                        self.set_stage('REST', self.p['rest_sec'])
            elif self.stage == 'DISCOVERED':
                if self.head_done():
                    if self.target is None or now-self.target_seen > 1.2:
                        self.say_goodbye()
                    else:
                        # Play the thoughtful hum once, not on every tracking step.
                        self.head_command(float(self.head['pan']), float(self.head['tilt']), 5)
                        self.set_stage('TRACKING', self.p['track_timeout_sec'])
                elif now > self.deadline:
                    self.fault('Discovery acknowledgement timed out')
            elif self.stage == 'TRACKING':
                if self.target is None or now-self.target_seen > 1.2 or now > self.deadline:
                    self.say_goodbye()
                    return
                if not self.head_done():
                    if now-self.head_sent > 5:
                        self.fault('Tracking acknowledgement timed out')
                    return
                pan, tilt, centered = tracking_angles(self.target,
                    self.p['image_width'], self.p['image_height'],
                    float(self.head['pan']), float(self.head['tilt']),
                    self.p['pan_sign'], self.p['tilt_sign'],
                    (self.p['pan_min'], self.p['pan_max']),
                    (self.p['tilt_min'], self.p['tilt_max']))
                # No repeated commands in the dead band or at a mechanical limit.
                if not centered and (round(pan), round(tilt)) != (
                        round(float(self.head['pan'])), round(float(self.head['tilt']))):
                    self.head_command(pan, tilt)
            elif self.stage == 'GOODBYE':
                # Wait for centering AND the farewell phrase; then roam without REST.
                if self.head_done() and now-self.head_sent >= .65:
                    self.start_roaming()
                elif now > self.deadline:
                    self.fault('Goodbye centering acknowledgement timed out')
        except Exception as error:
            self.fault(str(error))


def main(args=None):
    rclpy.init(args=args)
    node = NormalModeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        # The normal exit path is STOP -> terminal action result -> stationary -> HOME.
        # On process shutdown, request cancellation; Uno's heartbeat watchdog centers.
        try:
            node.cancel_navigation()
        except Exception:
            pass  # Short-roam lease expiry also cancels Nav2 after controller loss.
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


