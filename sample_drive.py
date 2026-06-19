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
    'decision': 'none',     # NEW — 'left', 'right', or 'none'
    'chasing_car':    False,    # [PERSON 3 V2.5] True when chasing car detected behind
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
    """
    Real-Time Task implementing:
    - Concurrency (inherits threading.Thread)
    - Task Period (enforced in run loop)
    - Task Priority (logical priority assigned)
    """
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
        except Exception as e:
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
# Task Implementations (This is where you write your tasks)
# ---------------------------------------------------------

def read_single_camera(sock, window_name, data_key):
    #This function reads the latest frame from the camera socket and stores it in the shared data
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
                
                # You may disable this if you don't need to display the frames / This could effect the fps
                frame_resized = cv2.resize(frame, (640, 480))
                cv2.imshow(window_name, frame_resized)
                cv2.waitKey(1)
                
    except Exception as e:
        pass

def read_front_camera_task():
    read_single_camera(front_camera_sock, "Front Camera", 'latest_front_frame')

def read_back_camera_task():
    read_single_camera(back_camera_sock, "Back Camera", 'latest_back_frame')

# =========================================================
# [SHAHIR - Token Detection]
# HSV color ranges calibrated for SpeedTrials2D tokens.
# Green  : H=40-75  (lime green)
# Red    : H=0-15 and H=165-180 (wraps around HSV wheel)
# Yellow : H=16-35  (orange-yellow)
# =========================================================
GREEN_LOWER  = np.array([40,  40, 100])
GREEN_UPPER  = np.array([75, 255, 255])

RED_LOWER1   = np.array([0,  100, 100])
RED_UPPER1   = np.array([15, 255, 255])
RED_LOWER2   = np.array([165, 100, 100])
RED_UPPER2   = np.array([180, 255, 255])

YELLOW_LOWER = np.array([16, 100, 150])
YELLOW_UPPER = np.array([35, 255, 255])


def detect_tokens(frame):
    """
    [PERSON 1 - Token Detection]
    Scans the front camera frame for colored tokens using HSV color detection.
    Only looks at the bottom 3/4 of the frame (top 1/4 is sky, no tokens there).

    Returns:
        tokens (dict): {'green': x_pos or None, 'red': x_pos or None, 'yellow': x_pos or None}
                        x_pos is the center-x pixel of the largest detected blob.
        frame_width (int): width of the frame in pixels.
    """
    h, w = frame.shape[:2]
    roi = frame[h // 4 : h * 7 // 10, :]  # ignore sky (top 25%) and own car + near ground (bottom 30%)
    hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)

    def largest_blob_x(mask):
        """Find the center-x of the largest token-shaped blob in the mask."""
        mask = cv2.dilate(mask, None, iterations=2)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        token_candidates = []
        for c in contours:
            area = cv2.contourArea(c)
            if not (150 < area < 1000):
                continue                        # wrong size
            x, y, cw, ch = cv2.boundingRect(c)
            if ch == 0:
                continue
            aspect = cw / ch
            if not (0.4 < aspect < 2.5):
                continue                        # too elongated (road stripe)
            fill = area / (cw * ch)
            if fill < 0.45:
                continue                        # hollow/diagonal shape (road stripe)
            cx = x + cw // 2
            if cx < w * 0.25 or cx > w * 0.75:
                continue                        # too close to screen edge
            token_candidates.append((area, cx))

        if not token_candidates:
            return None
        # Return x of the largest passing candidate
        return max(token_candidates, key=lambda t: t[0])[1]

    # Detect each token color
    green_x  = largest_blob_x(cv2.inRange(hsv, GREEN_LOWER, GREEN_UPPER))

    red_mask = cv2.bitwise_or(                              # red wraps around HSV
        cv2.inRange(hsv, RED_LOWER1, RED_UPPER1),
        cv2.inRange(hsv, RED_LOWER2, RED_UPPER2)
    )
    red_x    = largest_blob_x(red_mask)

    yellow_x = largest_blob_x(cv2.inRange(hsv, YELLOW_LOWER, YELLOW_UPPER))

    # Draw detected blobs on the frame for visual debug
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
            if not (150 < area < 1000):
                continue
            x, y, cw, ch = cv2.boundingRect(c)
            if ch == 0: continue
            aspect = cw / ch
            fill = area / (cw * ch)
            cx = x + cw // 2
            if 0.4 < aspect < 2.5 and fill > 0.45 and w * 0.25 < cx < w * 0.75:
                cv2.rectangle(debug_frame, (x, y + roi_top), (x + cw, y + ch + roi_top), bgr, 2)
                cv2.putText(debug_frame, f'{color_name}:{area:.0f}',
                            (x, y + roi_top - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, bgr, 1)
    cv2.imshow('Token Debug', cv2.resize(debug_frame, (640, 480)))
    cv2.waitKey(1)

    return {'green': green_x, 'red': red_x, 'yellow': yellow_x}, w

# =========================================================
# [PERSON 2 - Token Decision]
# Takes token positions and decides steering direction.
# Priority order: Green (collect) > Red (avoid) > Yellow (dodge)
# Frame is divided into 3 zones: left / center / right
# =========================================================
def decide_steering(tokens, frame_width):
    """
    [PERSON 2 - Token Decision]
    Decides which direction to steer based on detected token positions.

    Logic:
        - Green token detected → steer toward it to collect (+10% speed)
        - Red token detected   → steer away from it to avoid (-20% speed)
        - Yellow token detected → dodge it (random chaos effect)
        - No token detected    → go straight

    Returns:
        'left', 'right', or 'none'
    """
    left_bound  = frame_width // 3           # left lane boundary
    right_bound = (frame_width * 2) // 3    # right lane boundary

    green_x  = tokens['green']
    red_x    = tokens['red']
    yellow_x = tokens['yellow']

    # Priority 1: Chase green token (+10% speed)
    if green_x is not None:
        if green_x < left_bound:
            return 'left'
        elif green_x > right_bound:
            return 'right'
        else:
            return 'none'       # already lined up with green

    # Priority 2: Avoid red token (-20% speed)
    if red_x is not None:
        if red_x < left_bound:
            return 'right'      # red on left, go right
        elif red_x > right_bound:
            return 'left'       # red on right, go left
        else:
            return 'left'       # red in center, dodge left

    # Priority 3: Dodge yellow token (unpredictable effect)
    if yellow_x is not None:
        if yellow_x < left_bound:
            return 'right'
        elif yellow_x > right_bound:
            return 'left'
        else:
            return 'right'      # yellow in center, dodge right

    return 'none'               # no token, go straight


def processing_task():
    """
    PERCEIVE + COMPUTE stage.
    Calls detect_tokens() [Person 1] then decide_steering() [Person 2]
    and writes the result into shared_data for send_controls_task to act on.
    """
    with data_lock:
        front_frame = shared_data['latest_front_frame']

    if front_frame is None:
        return

    # [PERSON 1] Detect token positions from front camera
    tokens, frame_width = detect_tokens(front_frame)

    # [PERSON 2] Decide steering direction based on token positions
    decision = decide_steering(tokens, frame_width)

    # Debug: print when tokens are detected
    if any(v is not None for v in tokens.values()):
        print(f"[DETECT] green={tokens['green']} red={tokens['red']} yellow={tokens['yellow']} => {decision}")

    with data_lock:
        # Only write new decision if not already mid-tap
        if shared_data['decision'] == 'none':
            shared_data['decision'] = decision


# =========================================================
# [PERSON 3 V2.5 - Chasing Car Detection (back camera)]
# =========================================================
CHASE_AREA_THRESHOLD = 2000   # px^2 — chasing car is "close" when blob this large

def detect_chasing_car(frame):
    """[PERSON 3 V2.5] Detect a car closing in from behind via the back camera.
    Lower-half centre ROI -> grayscale -> blur -> Canny -> largest contour area."""
    h, w = frame.shape[:2]
    roi = frame[h // 2:, w * 30 // 100: w * 70 // 100]
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
    """[PERSON 3 V2.5] Separate RTTask: read back camera, run chasing detection,
    write the 'chasing_car' flag. Kept separate so it never blocks front processing."""
    with data_lock:
        back_frame = shared_data['latest_back_frame']
    if back_frame is None:
        return
    chasing = detect_chasing_car(back_frame)
    with data_lock:
        shared_data['chasing_car'] = chasing


# ---------------------------------------------------------
# Steering Tap State (Person 3 — Steering Control)
# A "tap" = apply full steering for a fixed number of control cycles, then
# release. send_controls_task runs at period=0.005s, so:
#   STEER_TAP_DURATION (25) x 0.005s = 0.125s of steering per lane change.
# ---------------------------------------------------------
STEER_TAP_DURATION = 25   # cycles per tap (tune for clean single-lane moves)
steer_tap_counter = 0     # cycles remaining in the current tap (0 = idle)
current_steer = 0.0       # steering value held during the current tap


def send_controls_task():
    """Actuate stage (Person 3): turn shared_data['decision'] into brief
    steering pulses (taps) so the car changes lane without over-steering."""
    global control_conn, steer_tap_counter, current_steer
    if control_conn is None:
        return

    with data_lock:
        is_dark = shared_data['low_brightness']
    if is_dark:
        if not _dark_signal_sent:
            print("[DARK] Recovery signal sent (accel=-1.0)")
            _dark_signal_sent = True
        try:
            data = struct.pack('ff', 0.0, -1.0)  # reverse while dark
            control_conn.sendall(data)
        except Exception as e:
            print(f"Control send error: {e}")
            control_conn = None
        return  # skip token-based steering while dark
    else:
        _dark_signal_sent = False  # reset for next dark event

    # [PERSON 3 V2.5] Chasing car escape: floor the accelerator to pull away
    with data_lock:
        is_chasing = shared_data['chasing_car']
    acceleration_input = 1.0  # normal: always forward
    if is_chasing:
        acceleration_input = 1.0  # already max, but logged explicitly
        print("[CHASE] Chasing car close --- holding max acceleration!")

    # --- Tap state machine ---
    if steer_tap_counter > 0:
        # Tap in progress: hold the current steer and count it down.
        steer_tap_counter -= 1
    else:
        # Idle: consume the latest decision and start a fresh tap if needed.
        with data_lock:
            decision = shared_data['decision']
            shared_data['decision'] = 'none'   # one tap per decision
        if decision == 'left':
            current_steer = -1.0
            steer_tap_counter = STEER_TAP_DURATION
        elif decision == 'right':
            current_steer = 1.0
            steer_tap_counter = STEER_TAP_DURATION
        else:
            current_steer = 0.0   # no decision -> drive straight

    steering_input = current_steer

    try:
        data = struct.pack('ff', steering_input, acceleration_input)
        control_conn.sendall(data)
    except Exception as e:
        print(f"Control send error: {e}")
        control_conn = None

# ---------------------------------------------------------
# Main (Scheduler Initialization)
# ---------------------------------------------------------
if __name__ == '__main__':
    print("Initializing RTSE Sample Drive...")
    
    # Initialize network connections
    threading.Thread(target=setup_control_server, daemon=True).start()
    threading.Thread(target=setup_cameras, daemon=True).start()
    
    print("\n--- Starting Real-Time Tasks (awaiting connections dynamically) ---\n")
    
    # This is where you define tasks with explicit Scheduling parameters (Concurrency, Priority, Period)
    # Period refers to the period of execution of the task in seconds
    # Priority refers to the priority of the task, higher priority means higher priority
    # Concurrency refers to the number of instances of the task that can run at the same time
    t_front_camera = RTTask("ReadFrontCamera", period=0.005, priority=TaskPriority.HIGH, execute_func=read_front_camera_task)
    t_back_camera = RTTask("ReadBackCamera", period=0.005, priority=TaskPriority.HIGH, execute_func=read_back_camera_task)
    t_processing = RTTask("Processing", period=0.005, priority=TaskPriority.MEDIUM, execute_func=processing_task)
    t_rear_processing = RTTask("RearProcessing", period=0.005, priority=TaskPriority.MEDIUM, execute_func=rear_processing_task)  # [PERSON 3 V2.5]
    t_controls = RTTask("SendControls", period=0.005, priority=TaskPriority.HIGH, execute_func=send_controls_task)

    # Start tasks to run concurrently
    t_front_camera.start()
    t_back_camera.start()
    t_processing.start()
    t_rear_processing.start()   # [PERSON 3 V2.5]
    t_controls.start()
    
    try:
        # You need this to keep the main thread alive, otherwise the program will exit immediately
        while is_running:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nKeyboard Interrupt detected. Stopping system...")
        is_running = False

    # This is to make sure that the tasks are terminated cleanly
    t_front_camera.join()
    t_back_camera.join()
    t_processing.join()
    t_rear_processing.join()   # [PERSON 3 V2.5]
    t_controls.join()
    
    # This is to close all the connections
    if front_camera_sock:
        front_camera_sock.close()
    if back_camera_sock:
        back_camera_sock.close()
    if control_conn:
        control_conn.close()
    cv2.destroyAllWindows()
    print("System terminated cleanly.")
