import socket
import threading
import struct
import cv2
import numpy as np
import time
import keyboard
import select
import ctypes

# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------
CAMERA_HOST = '127.0.0.1'
FRONT_CAMERA_PORT = 8080
BACK_CAMERA_PORT = 8082
CONTROL_HOST = '127.0.0.1'
CONTROL_PORT = 8081

# Shared Resources with Mutex Lock for Concurrency
shared_data = {
    'latest_front_frame': None,
    'latest_back_frame': None,
    'steering_input': 0.0,
    'acceleration_input': 0.0,
    'decision': 'none',
    'low_brightness': False,
    'police_active':  False,
    'chasing_car':    False,
    # [PERSON 2 V2.5] Police car event state
    'police_mode':         False,
    'police_mode_expiry':  0.0,
    # [PERSON 2 V3.0] EV5 Golden Lane event state
    'ev5_active':          False,
    'ev5_expiry':          0.0,
    'ev5_target_x':        None,
    'ev5_zone_hits':       [0, 0, 0],   # cumulative [left, centre, right] green-token hits this event
}
data_lock = threading.Lock()
is_running = True

# ---------------------------------------------------------
# Real-Time Scheduling Framework (Do not change this in your code)
# ---------------------------------------------------------
class TaskPriority:
    HIGH = 1
    MEDIUM = 2
    LOW = 3

class RTTask(threading.Thread):
    def __init__(self, name, period, priority, execute_func):
        super().__init__()
        self.name = name
        self.period = period
        self.priority = priority
        self.execute_func = execute_func
        self.daemon = True

    def run(self):
        print(f"[{self.name}] Started | Period: {self.period}s | Priority: {self.priority}")
        try:
            handle = ctypes.windll.kernel32.GetCurrentThread()
            if self.priority == TaskPriority.HIGH:
                ctypes.windll.kernel32.SetThreadPriority(handle, 2)
            elif self.priority == TaskPriority.MEDIUM:
                ctypes.windll.kernel32.SetThreadPriority(handle, 0)
            elif self.priority == TaskPriority.LOW:
                ctypes.windll.kernel32.SetThreadPriority(handle, -2)
        except Exception:
            pass
        while is_running:
            start_time = time.time()
            self.execute_func()
            exec_time = time.time() - start_time
            sleep_time = self.period - exec_time
            if sleep_time > 0:
                time.sleep(sleep_time)

# ---------------------------------------------------------
# Network Connection Setup (Do not change this in your code)
# ---------------------------------------------------------
front_camera_sock = None
back_camera_sock = None
control_conn = None

def setup_cameras():
    global front_camera_sock, back_camera_sock
    print("Connecting to Cameras...")
    front_connected = False
    back_connected = False
    while is_running and not (front_connected and back_connected):
        if not front_connected:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.0)
                s.connect((CAMERA_HOST, FRONT_CAMERA_PORT))
                front_camera_sock = s
                print("Connected to Front Camera successfully.")
                front_connected = True
            except Exception:
                pass
        if not back_connected:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1.0)
                s.connect((CAMERA_HOST, BACK_CAMERA_PORT))
                back_camera_sock = s
                print("Connected to Back Camera successfully.")
                back_connected = True
            except Exception:
                pass
        if not (front_connected and back_connected):
            time.sleep(1)

def setup_control_server():
    global control_conn
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_sock.bind((CONTROL_HOST, CONTROL_PORT))
    server_sock.listen()
    server_sock.settimeout(1.0)
    print(f"Control server listening on {CONTROL_HOST}:{CONTROL_PORT}")
    while is_running:
        try:
            conn, addr = server_sock.accept()
            print(f"Control client connected from {addr}")
            control_conn = conn
            break
        except socket.timeout:
            continue

# ---------------------------------------------------------
# Task Implementations
# ---------------------------------------------------------
def read_single_camera(sock, window_name, data_key):
    if sock is None:
        return
    try:
        latest_frame_data = None
        sock.settimeout(None)
        length_bytes = sock.recv(4)
        if not length_bytes:
            return
        image_length = int.from_bytes(length_bytes, 'little')
        received_bytes = b''
        while len(received_bytes) < image_length and is_running:
            packet = sock.recv(image_length - len(received_bytes))
            if not packet:
                break
            received_bytes += packet
        if len(received_bytes) == image_length:
            latest_frame_data = received_bytes
        while is_running:
            readable, _, _ = select.select([sock], [], [], 0.0)
            if not readable:
                break
            sock.settimeout(1.0)
            length_bytes = sock.recv(4)
            if not length_bytes:
                return
            image_length = int.from_bytes(length_bytes, 'little')
            received_bytes = b''
            while len(received_bytes) < image_length and is_running:
                packet = sock.recv(image_length - len(received_bytes))
                if not packet:
                    break
                received_bytes += packet
            if len(received_bytes) == image_length:
                latest_frame_data = received_bytes
        if latest_frame_data is not None:
            np_arr = np.frombuffer(latest_frame_data, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if frame is not None:
                with data_lock:
                    shared_data[data_key] = frame
                frame_resized = cv2.resize(frame, (640, 480))
                cv2.imshow(window_name, frame_resized)
                cv2.waitKey(1)
    except Exception:
        pass

def read_front_camera_task():
    read_single_camera(front_camera_sock, "Front Camera", 'latest_front_frame')

def read_back_camera_task():
    read_single_camera(back_camera_sock, "Back Camera", 'latest_back_frame')


# =========================================================
# [PERSON 1 V2.5 - Low Light Detection]
# Checks mean brightness. If mean < 60, scene is dark.
# Sets shared_data['low_brightness'] = True for Person 4 recovery.
# =========================================================
def preprocess_frame(frame):
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    mean_val = float(np.mean(gray))
    is_dark = mean_val < 60
    with data_lock:
        shared_data['low_brightness'] = is_dark
    if is_dark:
        with data_lock:
            already_dark = shared_data.get('_prev_dark', False)
        if not already_dark:
            print(f"[DARK] Low light detected (mean brightness={mean_val:.1f})")
        with data_lock:
            shared_data['_prev_dark'] = True
    else:
        with data_lock:
            shared_data['_prev_dark'] = False
    return frame


# =========================================================
# [PERSON 2 V2.5 - Police Car Detection]
# The police car is a blue/purple vehicle (H=100-135, S>100, V>40).
# Contour-based detection in road area only (top 35% sky excluded)
# avoids false positives from the night sky (same hue as police car).
# =========================================================
POLICE_CAR_LOWER    = np.array([100, 100,  40])
POLICE_CAR_UPPER    = np.array([135, 255, 255])
POLICE_CAR_MIN_AREA = 150
POLICE_EVENT_DURATION = 5.0

def detect_police_car(frame):
    """Returns (True, car_x) if blue/purple police car found, else (False, None)."""
    h, w = frame.shape[:2]
    road = frame[h * 35 // 100 : h * 85 // 100, :]
    hsv  = cv2.cvtColor(road, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, POLICE_CAR_LOWER, POLICE_CAR_UPPER)
    mask = cv2.dilate(mask, None, iterations=2)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return False, None
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < POLICE_CAR_MIN_AREA:
        return False, None
    M = cv2.moments(largest)
    if M['m00'] == 0:
        return False, None
    car_x = int(M['m10'] / M['m00'])
    print(f"[POLICE] Car detected at x={car_x}")
    return True, car_x


# =========================================================
# [PERSON 2 V2.5 - Police Red Token Detection]
# Police event red tokens are 4000+px² — too large for detect_tokens()
# which caps at 3000px². This function has no upper size limit.
# detect_tokens() is NOT modified.
# =========================================================
POLICE_RED_MIN_AREA = 300

def detect_police_red_token(frame):
    """Returns centre-X of largest red blob (no upper size limit), or None."""
    h, w = frame.shape[:2]
    roi = frame[h // 4 : h * 7 // 10, :]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    red_mask = cv2.bitwise_or(
        cv2.inRange(hsv, RED_LOWER1, RED_UPPER1),
        cv2.inRange(hsv, RED_LOWER2, RED_UPPER2)
    )
    red_mask = cv2.dilate(red_mask, None, iterations=2)
    contours, _ = cv2.findContours(red_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    valid = [(cv2.contourArea(c), c) for c in contours if cv2.contourArea(c) > POLICE_RED_MIN_AREA]
    if not valid:
        return None
    largest_c = max(valid, key=lambda t: t[0])[1]
    M = cv2.moments(largest_c)
    if M['m00'] == 0:
        return None
    return int(M['m10'] / M['m00'])


# =========================================================
# [PERSON 3 V2.5 - Chasing Car Detection]
# Uses back camera. Canny edge detect in lower-centre ROI.
# If largest contour > CHASE_AREA_THRESHOLD, a car is close.
# =========================================================
CHASE_AREA_THRESHOLD = 2000

def detect_chasing_car(frame):
    """Returns True if chasing car detected close behind."""
    h, w = frame.shape[:2]
    roi = frame[h // 2:, w * 30 // 100 : w * 70 // 100]
    gray  = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    blur  = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)
    contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return False
    max_area = max(cv2.contourArea(c) for c in contours)
    if max_area > CHASE_AREA_THRESHOLD:
        print(f"[CHASE] Chasing car detected! area={max_area:.0f}")
        return True
    return False

def rear_processing_task():
    """[PERSON 3 V2.5] Runs chasing car detection on back camera."""
    with data_lock:
        back_frame = shared_data['latest_back_frame']
    if back_frame is None:
        return
    chasing = detect_chasing_car(back_frame)
    with data_lock:
        shared_data['chasing_car'] = chasing


# =========================================================
# [SHAHIR V1.0 - Token Detection]
# HSV color ranges calibrated for SpeedTrials2D tokens.
# Green  : H=40-75  | Red: H=0-15 and H=165-180 | Yellow: H=16-35
# =========================================================
GREEN_LOWER  = np.array([40,  40, 100])
GREEN_UPPER  = np.array([75, 255, 255])
RED_LOWER1   = np.array([0,  100, 100])
RED_UPPER1   = np.array([15, 255, 255])
RED_LOWER2   = np.array([165, 100, 100])
RED_UPPER2   = np.array([180, 255, 255])
YELLOW_LOWER = np.array([16, 100, 150])
YELLOW_UPPER = np.array([35, 255, 255])
BLUE_LOWER   = np.array([100,  80, 120])
BLUE_UPPER   = np.array([130, 255, 255])


def detect_tokens(frame):
    """
    [PERSON 1 V1.0 - Token Detection] — DO NOT MODIFY
    Scans front camera for colored tokens using HSV color detection.
    Returns: tokens dict {'green', 'red', 'yellow'} -> centre-x or None, and frame_width.
    """
    h, w = frame.shape[:2]
    roi = frame[h // 4 : h * 7 // 10, :]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    def largest_blob_x(mask):
        mask = cv2.dilate(mask, None, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None
        token_candidates = []
        for c in contours:
            area = cv2.contourArea(c)
            if not (400 < area < 3000):
                continue
            x, y, cw, ch = cv2.boundingRect(c)
            if ch == 0:
                continue
            aspect = cw / ch
            if not (0.4 < aspect < 2.5):
                continue
            fill = area / (cw * ch)
            if fill < 0.45:
                continue
            cx = x + cw // 2
            if cx < w * 0.35 or cx > w * 0.65:
                continue
            token_candidates.append((area, cx))
        if not token_candidates:
            return None
        return max(token_candidates, key=lambda t: t[0])[1]

    green_x  = largest_blob_x(cv2.inRange(hsv, GREEN_LOWER, GREEN_UPPER))
    red_mask = cv2.bitwise_or(
        cv2.inRange(hsv, RED_LOWER1, RED_UPPER1),
        cv2.inRange(hsv, RED_LOWER2, RED_UPPER2)
    )
    red_x    = largest_blob_x(red_mask)
    yellow_x = largest_blob_x(cv2.inRange(hsv, YELLOW_LOWER, YELLOW_UPPER))

    roi_top = h // 4
    debug_frame = frame.copy()
    for color_name, mask, bgr in [
        ('G', cv2.inRange(hsv, GREEN_LOWER, GREEN_UPPER), (0, 255, 0)),
        ('R', red_mask, (0, 0, 255)),
        ('Y', cv2.inRange(hsv, YELLOW_LOWER, YELLOW_UPPER), (0, 255, 255)),
    ]:
        mask = cv2.dilate(mask, None, iterations=2)
        cnts, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for c in cnts:
            area = cv2.contourArea(c)
            if not (400 < area < 3000):
                continue
            x, y, cw, ch = cv2.boundingRect(c)
            if ch == 0:
                continue
            aspect = cw / ch
            fill = area / (cw * ch)
            cx = x + cw // 2
            if 0.4 < aspect < 2.5 and fill > 0.45 and w * 0.35 < cx < w * 0.65:
                cv2.rectangle(debug_frame, (x, y + roi_top), (x + cw, y + ch + roi_top), bgr, 2)
                cv2.putText(debug_frame, f'{color_name}:{area:.0f}',
                            (x, y + roi_top - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, bgr, 1)
    cv2.imshow('Token Debug', cv2.resize(debug_frame, (640, 480)))
    cv2.waitKey(1)
    return {'green': green_x, 'red': red_x, 'yellow': yellow_x}, w


# =========================================================
# [PERSON 2 V1.0 - Token Decision] — DO NOT MODIFY
# Priority: Green (collect) > Red (avoid) > Yellow (dodge)
# =========================================================
def decide_steering(tokens, frame_width):
    """Returns 'left', 'right', or 'none' based on token positions."""
    left_bound  = frame_width // 3
    right_bound = (frame_width * 2) // 3
    green_x  = tokens['green']
    red_x    = tokens['red']
    yellow_x = tokens['yellow']

    if green_x is not None:
        if green_x < left_bound:
            return 'left'
        elif green_x > right_bound:
            return 'right'
        else:
            if red_x is not None:
                if red_x < left_bound:    return 'right'
                elif red_x > right_bound: return 'left'
                else:                     return 'right'
            if yellow_x is not None:
                if yellow_x < left_bound:    return 'right'
                elif yellow_x > right_bound: return 'left'
                else:                        return 'right'
            return 'none'

    if red_x is not None:
        if red_x < left_bound:    return 'right'
        elif red_x > right_bound: return 'left'
        else:                     return 'left'

    if yellow_x is not None:
        if yellow_x < left_bound:    return 'right'
        elif yellow_x > right_bound: return 'left'
        else:                        return 'right'

    return 'none'


# =========================================================
# [PERSON 2 V3.0 - EV5 Golden Lane Detection]
# The Golden Lane event fires a full-screen green flash (~0.4s).
# During the flash everything is green — detect_tokens() (max 3000px²)
# ignores the massive background blob (140,000px²). After the flash,
# only tokens in the golden lane stay green.
#
# IMPORTANT: green is also a normal/recurring token colour during regular
# gameplay (confirmed via frame analysis of a real run), so a single
# isolated green blob can appear in ANY lane by chance — picking "the
# single largest green blob" is not reliable on its own, since two
# unrelated green tokens can be on screen in different lanes at once.
# The golden lane instead reveals itself as repeated/stacked green tokens
# scrolling down the SAME lane over time. detect_golden_lane_zone_hits()
# tallies close, confidently-resolved green detections per lane (left/
# centre/right) each frame; processing_task() accumulates this over the
# whole 5s window and the lane with consistently "many green along it"
# wins, instead of reacting to any single frame's biggest blob.
# detect_tokens() also misses lane-1/3 tokens (edge filter cx<0.35w),
# so this detector uses no edge restriction.
# =========================================================
EV5_FLASH_THRESHOLD = 0.40
EV5_EVENT_DURATION  = 5.0
EV5_TOKEN_MAX_AREA   = 50000
EV5_CLOSE_MIN_AREA   = 1200   # ignore small/far blobs whose lane isn't resolved yet
EV5_CLOSE_Y_FRAC     = 0.55   # must sit in the lower (closer-to-camera) part of the ROI
EV5_LANE_MARGIN      = 2      # a lane must lead the runner-up by this many hits to commit


def detect_ev5_flash(frame):
    """
    [PERSON 2 V3.0 - EV5 Flash Detection]
    Returns True when >40% of the frame is bright green (the golden lane flash).
    Normal gameplay has only 5-20% green; the flash spikes to >90%.
    """
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    green_mask = cv2.inRange(hsv, np.array([35, 80, 80]), np.array([85, 255, 255]))
    total_pixels = frame.shape[0] * frame.shape[1]
    green_pct = green_mask.sum() / 255 / total_pixels
    return green_pct > EV5_FLASH_THRESHOLD


def detect_golden_lane_zone_hits(frame):
    """
    [PERSON 2 V3.0 - Golden Lane Zone Tally]
    Counts close, confidently-resolved green tokens per lane third
    (left / centre / right) in this single frame. Far-away/small blobs
    are skipped because perspective hasn't resolved their true lane yet.
    Returns [left_hits, centre_hits, right_hits] for this frame only —
    the caller accumulates these across the 5s event window.
    """
    h, w = frame.shape[:2]
    roi = frame[h // 4 : h * 7 // 10, :]
    roi_h = roi.shape[0]
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
    green_mask = cv2.inRange(hsv, np.array([35, 80, 80]), np.array([85, 255, 255]))
    green_mask = cv2.dilate(green_mask, None, iterations=2)
    contours, _ = cv2.findContours(green_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    left_bound, right_bound = w // 3, (w * 2) // 3
    hits = [0, 0, 0]
    for c in contours:
        area = cv2.contourArea(c)
        if not (EV5_CLOSE_MIN_AREA < area < EV5_TOKEN_MAX_AREA):
            continue
        M = cv2.moments(c)
        if M['m00'] == 0:
            continue
        cx = M['m10'] / M['m00']
        cy = M['m01'] / M['m00']
        if cy < roi_h * EV5_CLOSE_Y_FRAC:
            continue
        if cx < left_bound:
            hits[0] += 1
        elif cx > right_bound:
            hits[2] += 1
        else:
            hits[1] += 1
    return hits


def processing_task():
    """
    PERCEIVE + COMPUTE stage.
    Event priority (highest first):
      1. Police car event  [PERSON 2 V2.5] — collect red token, avoid police car
      2. EV5 golden lane   [PERSON 2 V3.0] — steer to golden lane within 5s
      3. Normal steering   [PERSON 2 V2.5] — chase green, avoid red/yellow
    detect_tokens() and low-light handling are NOT modified.
    """
    with data_lock:
        front_frame = shared_data['latest_front_frame']
    if front_frame is None:
        return

    preprocess_frame(front_frame)
    tokens, frame_width = detect_tokens(front_frame)
    now = time.time()

    # ── Police Car Event ───────────────────────────────────────────────────────
    with data_lock:
        pm_active = shared_data['police_mode']
        pm_expiry = shared_data['police_mode_expiry']

    police_visible, police_x = detect_police_car(front_frame)

    if police_visible and not pm_active:
        with data_lock:
            shared_data['police_mode']        = True
            shared_data['police_mode_expiry'] = now + POLICE_EVENT_DURATION
            shared_data['police_active']      = True
        pm_active = True
        print(f"[POLICE] Event started — collect red token within {POLICE_EVENT_DURATION:.0f}s!")

    if pm_active and now > pm_expiry:
        with data_lock:
            shared_data['police_mode']   = False
            shared_data['police_active'] = False
        pm_active = False
        print("[POLICE] Event window closed")

    if pm_active:
        red_x = detect_police_red_token(front_frame)
        left_bound  = frame_width // 3
        right_bound = (frame_width * 2) // 3
        if red_x is not None:
            if red_x < left_bound:    decision = 'left'
            elif red_x > right_bound: decision = 'right'
            else:                     decision = 'none'
            if police_x is not None:
                if decision == 'left'  and police_x < left_bound:  decision = 'right'
                elif decision == 'right' and police_x > right_bound: decision = 'left'
            print(f"[POLICE] red_x={red_x} police_x={police_x} => {decision}")
        else:
            if police_x is not None:
                if police_x < left_bound:    decision = 'right'
                elif police_x > right_bound: decision = 'left'
                else:                        decision = 'left'
            else:
                decision = 'none'
        with data_lock:
            if shared_data['decision'] == 'none':
                shared_data['decision'] = decision
        return

    # ── EV5 Golden Lane Event ──────────────────────────────────────────────────
    with data_lock:
        ev5_active = shared_data['ev5_active']
        ev5_expiry = shared_data['ev5_expiry']

    flash_active = detect_ev5_flash(front_frame)

    if flash_active and not ev5_active:
        with data_lock:
            shared_data['ev5_active']    = True
            shared_data['ev5_expiry']    = now + EV5_EVENT_DURATION
            shared_data['ev5_target_x']  = None
            shared_data['ev5_zone_hits'] = [0, 0, 0]
        ev5_active = True
        print(f"[EV5] Golden Lane flash — steering to golden lane for {EV5_EVENT_DURATION:.0f}s!")

    if ev5_active and now > ev5_expiry:
        with data_lock:
            shared_data['ev5_active']    = False
            shared_data['ev5_target_x']  = None
            shared_data['ev5_zone_hits'] = [0, 0, 0]
        ev5_active = False
        print("[EV5] Golden Lane window expired")

    if ev5_active:
        if flash_active:
            print("[EV5] Flash active — holding course")
            return
        hits = detect_golden_lane_zone_hits(front_frame)
        with data_lock:
            cum = shared_data['ev5_zone_hits']
            cum = [cum[i] + hits[i] for i in range(3)]
            shared_data['ev5_zone_hits'] = cum
        best_i     = max(range(3), key=lambda i: cum[i])
        runner_up  = max(v for i, v in enumerate(cum) if i != best_i)
        if cum[best_i] > 0 and cum[best_i] >= runner_up + EV5_LANE_MARGIN:
            decision = ['left', 'none', 'right'][best_i]
        else:
            decision = 'none'
        print(f"[EV5] zone_hits(L,C,R)={cum} => {decision}")
        with data_lock:
            if shared_data['decision'] == 'none':
                shared_data['decision'] = decision
        return

    # ── Normal token steering ──────────────────────────────────────────────────
    with data_lock:
        shared_data['police_active'] = False

    decision = decide_steering(tokens, frame_width)
    if any(v is not None for v in tokens.values()):
        print(f"[DETECT] green={tokens['green']} red={tokens['red']} yellow={tokens['yellow']} => {decision}")
    with data_lock:
        if shared_data['decision'] == 'none':
            shared_data['decision'] = decision


# =========================================================
# [PERSON 3 V2.5 - Steering Tap State]
# STEER_TAP_DURATION x period = 25 x 0.005s = 0.125s pulse per lane change.
# =========================================================
STEER_TAP_DURATION = 25
steer_tap_counter  = 0
current_steer      = 0.0
_dark_signal_sent  = False


def send_controls_task():
    """
    ACTUATE stage.
    [PERSON 4 V2.5] Low-light: reverse (accel=-1.0) until bright again.
    [PERSON 3 V2.5] Chasing car: hold max acceleration to escape.
    [PERSON 3 V2.5] Tap state machine: brief steering pulses for lane changes.
    """
    global control_conn, steer_tap_counter, current_steer, _dark_signal_sent
    if control_conn is None:
        return

    with data_lock:
        is_dark = shared_data['low_brightness']
    if is_dark:
        if not _dark_signal_sent:
            print("[DARK] Recovery signal sent (accel=-1.0)")
            _dark_signal_sent = True
        try:
            control_conn.sendall(struct.pack('ff', 0.0, -1.0))
        except Exception as e:
            print(f"Control send error: {e}")
            control_conn = None
        return
    else:
        _dark_signal_sent = False

    with data_lock:
        is_chasing = shared_data['chasing_car']
    acceleration_input = 1.0
    if is_chasing:
        print("[CHASE] Chasing car close --- holding max acceleration!")

    if steer_tap_counter > 0:
        steer_tap_counter -= 1
    else:
        with data_lock:
            decision = shared_data['decision']
            shared_data['decision'] = 'none'
        if decision == 'left':
            current_steer     = -1.0
            steer_tap_counter = STEER_TAP_DURATION
        elif decision == 'right':
            current_steer     = 1.0
            steer_tap_counter = STEER_TAP_DURATION
        else:
            current_steer = 0.0

    try:
        control_conn.sendall(struct.pack('ff', current_steer, acceleration_input))
    except Exception as e:
        print(f"Control send error: {e}")
        control_conn = None


# ---------------------------------------------------------
# Main (Scheduler Initialization)
# ---------------------------------------------------------
if __name__ == '__main__':
    print("Initializing RTSE Sample Drive...")
    threading.Thread(target=setup_control_server, daemon=True).start()
    threading.Thread(target=setup_cameras, daemon=True).start()
    print("\n--- Starting Real-Time Tasks ---\n")

    t_front_camera = RTTask("ReadFrontCamera", period=0.005, priority=TaskPriority.HIGH,   execute_func=read_front_camera_task)
    t_back_camera  = RTTask("ReadBackCamera",  period=0.005, priority=TaskPriority.HIGH,   execute_func=read_back_camera_task)
    t_processing   = RTTask("Processing",      period=0.005, priority=TaskPriority.MEDIUM, execute_func=processing_task)
    t_rear_proc    = RTTask("RearProcessing",  period=0.005, priority=TaskPriority.MEDIUM, execute_func=rear_processing_task)
    t_controls     = RTTask("SendControls",    period=0.005, priority=TaskPriority.HIGH,   execute_func=send_controls_task)

    t_front_camera.start()
    t_back_camera.start()
    t_processing.start()
    t_rear_proc.start()
    t_controls.start()

    try:
        while is_running:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nKeyboard Interrupt detected. Stopping system...")
        is_running = False

    t_front_camera.join()
    t_back_camera.join()
    t_processing.join()
    t_rear_proc.join()
    t_controls.join()

    if front_camera_sock: front_camera_sock.close()
    if back_camera_sock:  back_camera_sock.close()
    if control_conn:      control_conn.close()
    cv2.destroyAllWindows()
    print("System terminated cleanly.")
