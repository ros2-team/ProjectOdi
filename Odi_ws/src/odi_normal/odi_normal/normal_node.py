"""Exclusive normal-mode controller. No direct /cmd_vel and no diary pipeline."""
import json
import math
import time
import uuid

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


class NormalModeNode(Node):
    def __init__(self):
        super().__init__('normal_node')
        defaults = dict(image_width=320, image_height=240,
                        target_classes=['bottle', 'backpack', 'cup'],
                        confidence=0.6, minimum_area_ratio=0.02, cooldown_sec=60.0,
                        rest_sec=8.0, move_timeout_sec=30.0, track_timeout_sec=6.0,
                        pan_sign=-1.0, tilt_sign=1.0,
                        pan_min=40.0, pan_max=140.0, tilt_min=0.0, tilt_max=100.0,
                        pan_home=84.0, tilt_home=65.0, nod_degrees=6.0)
        for key, value in defaults.items():
            self.declare_parameter(key, value)
        self.p = {k:self.get_parameter(k).value for k in defaults}
        for axis in ('pan', 'tilt'):
            if not 0 <= self.p[axis+'_min'] <= self.p[axis+'_home'] <= self.p[axis+'_max'] <= 180:
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
        if self.target is not None and msg.detection_id == self.target.detection_id:
            # Do not let another object of the same class replace the current target.
            if msg.confidence >= self.p['confidence']:
                self.target = msg
                self.target_seen = now

    def head_ready(self):
        return (time.monotonic()-self.head_seen < 1.0 and
                self.head.get('session_id') == self.session and
                self.head.get('ready') is True)

    def set_stage(self, stage, duration=0):
        self.stage = stage
        self.deadline = time.monotonic()+duration
        self.get_logger().info('Normal mode: ' + stage)

    def event(self, name, detail=''):
        msg = String()
        msg.data = json.dumps(dict(session_id=self.session, event=name, detail=detail))
        self.events.publish(msg)

    def fault(self, detail):
        if not self.stop_requested:
            self.fault_detail = detail
            self.event('FAULT', detail)
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
                                          detail=self.fault_detail))
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
                    self.fault('Head bridge/firmware or stationary odometry not ready')
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
                    self.target, self.target_seen = target, now
                    self.set_stage('TRACKING', self.p['track_timeout_sec'])
                elif now > self.deadline:
                    if not self.nav.server_is_ready():
                        self.fault('Exploration action server is unavailable')
                        return
                    request = Explore.Goal()
                    request.session_id, request.mode = self.session, 'SHORT_ROAM'
                    self.send_future = self.nav.send_goal_async(request)
                    self.set_stage('MOVING', self.p['move_timeout_sec'])
            elif self.stage == 'MOVING':
                target = self.attention.candidate(now)
                if target or now > self.deadline or not self.nav_pending():
                    self.target = target
                    self.target_seen = now
                    self.set_stage('BRAKING', 10)
                    self.cancel_navigation()
            elif self.stage == 'BRAKING':
                self.cancel_navigation()
                if not self.nav_pending() and self.stationary():
                    if self.target and now-self.target_seen < 1:
                        self.set_stage('TRACKING', self.p['track_timeout_sec'])
                    else:
                        self.home()
                        self.set_stage('RETURN_HEAD', 5)
                elif now > self.deadline:
                    self.fault('Waiting for navigation termination and base stop')
            elif self.stage == 'TRACKING':
                if now-self.target_seen > .8 or now > self.deadline:
                    self.attention.handled_target(self.target, now)
                    self.home()
                    self.set_stage('RETURN_HEAD', 5)
                    return
                if not self.head_done():
                    return
                pan, tilt, centered = tracking_angles(self.target,
                    self.p['image_width'], self.p['image_height'],
                    float(self.head['pan']), float(self.head['tilt']),
                    self.p['pan_sign'], self.p['tilt_sign'],
                    (self.p['pan_min'], self.p['pan_max']),
                    (self.p['tilt_min'], self.p['tilt_max']))
                if centered:
                    self.attention.handled_target(self.target, now)
                    self.expression_pan, self.expression_tilt = pan, tilt
                    self.head_command(pan, min(self.p['tilt_max'], tilt+self.p['nod_degrees']), 2)
                    self.set_stage('NOD_DOWN', 5)
                else:
                    self.head_command(pan, tilt)
            elif self.stage == 'NOD_DOWN':
                if self.head_done():
                    self.head_command(self.expression_pan, self.expression_tilt)
                    self.set_stage('NOD_UP', 5)
                elif now > self.deadline:
                    self.fault('Head expression acknowledgement timed out')
            elif self.stage == 'NOD_UP':
                if self.head_done():
                    self.home()
                    self.set_stage('RETURN_HEAD', 5)
                elif now > self.deadline:
                    self.fault('Head expression acknowledgement timed out')
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
