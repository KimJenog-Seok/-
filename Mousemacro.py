import sys
import subprocess
import time
import threading
import platform
import os

# =========================
# 필요한 라이브러리 자동 설치
# =========================
try:
    from pynput import mouse, keyboard
    from pynput.mouse import Controller as MouseController, Button
    
except ImportError:
    print("🚨 'pynput' 라이브러리가 설치되어 있지 않습니다.")
    print("자동으로 설치를 시작합니다. 잠시만 기다려주세요...")
    try:
        # pip을 통해 pynput 설치 시도
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pynput"])
        print("✅ 'pynput' 라이브러리 설치가 완료되었습니다.")
        # 설치 후 프로그램을 재시작하도록 안내
        print("프로그램을 다시 실행해주세요.")
        sys.exit()
    except subprocess.CalledProcessError as e:
        print(f"❌ 라이브러리 설치 실패: {e}")
        print("인터넷 연결을 확인하거나, 수동으로 'pip install pynput' 명령어를 실행해주세요.")
        sys.exit()

# =========================
# Windows: DPI 인식 + 가상 화면 좌표
# =========================
IS_WIN = (platform.system() == "Windows")

if IS_WIN:
    try:
        import ctypes
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

def get_virtual_screen_rect():
    """
    듀얼/멀티 모니터 '확장' 환경에서 전체 데스크톱(가상 화면)의
    좌상단 좌표(x0,y0)와 크기(w,h)를 가져온다.
    Windows는 음수 시작 좌표가 나올 수 있음(보조 모니터가 좌측/상단에 있을 때).
    """
    if IS_WIN:
        import ctypes
        user32 = ctypes.windll.user32
        x0 = user32.GetSystemMetrics(76)   # SM_XVIRTUALSCREEN
        y0 = user32.GetSystemMetrics(77)   # SM_YVIRTUALSCREEN
        w  = user32.GetSystemMetrics(78)   # SM_CXVIRTUALSCREEN
        h  = user32.GetSystemMetrics(79)   # SM_CYVIRTUALSCREEN
        return x0, y0, w, h
    else:
        # 크로스플랫폼 대안(대부분 단일 모니터): tkinter
        try:
            import tkinter as tk
            root = tk.Tk(); root.withdraw()
            w = root.winfo_screenwidth()
            h = root.winfo_screenheight()
            root.destroy()
            return 0, 0, w, h
        except Exception:
            return 0, 0, 1920, 1080

V_X0, V_Y0, V_W, V_H = get_virtual_screen_rect()

# =========================
# 상태
# =========================
# 이벤트 포맷 통일:
#   ("click", delay, x_ratio, y_ratio, btn_name)
#   ("scroll", delay, x_ratio, y_ratio, dx, dy)
recorded = []
is_recording = False
last_time = None

mouse_controller = MouseController()
stop_playback = threading.Event()
playback_thread = None

# 타이밍 튜닝
MIN_DELAY = 0.03       # 너무 빠른 입력 방지
AFTER_MOVE_SLEEP = 0.02
AFTER_SCROLL_SLEEP = 0.03

def to_ratio(x, y):
    """가상 화면 기준 정규화 좌표로 변환"""
    xr = (x - V_X0) / max(1, V_W)
    yr = (y - V_Y0) / max(1, V_H)
    return xr, yr

def to_abs(xr, yr):
    """정규화 좌표를 가상 화면 절대 좌표로 변환"""
    x = int(V_X0 + xr * V_W)
    y = int(V_Y0 + yr * V_H)
    return x, y

# =========================
# 리스너: 클릭 & 스크롤 녹화
# =========================
def on_click(x, y, button, pressed):
    global last_time
    if not is_recording or not pressed:
        return
    now = time.time()
    delay = 0 if last_time is None else (now - last_time)
    last_time = now
    xr, yr = to_ratio(x, y)
    recorded.append(("click", delay, xr, yr, button.name))
    print(f"[REC] click d={delay:.3f}s pos=({x},{y}) ratio=({xr:.4f},{yr:.4f}) btn={button.name}")

def on_scroll(x, y, dx, dy):
    """
    dx: 수평 스크롤, dy: 수직 스크롤(양수=위로, 음수=아래로)
    브라우저/앱마다 배율이 다를 수 있으므로 '있는 그대로' 기록/재생.
    """
    global last_time
    if not is_recording:
        return
    now = time.time()
    delay = 0 if last_time is None else (now - last_time)
    last_time = now
    xr, yr = to_ratio(x, y)
    recorded.append(("scroll", delay, xr, yr, int(dx), int(dy)))
    print(f"[REC] scroll d={delay:.3f}s pos=({x},{y}) ratio=({xr:.4f},{yr:.4f}) dx={dx} dy={dy}")

# =========================
# 녹화 토글
# =========================
def start_recording():
    global is_recording, recorded, last_time, V_X0, V_Y0, V_W, V_H
    recorded = []
    is_recording = True
    last_time = None
    V_X0, V_Y0, V_W, V_H = get_virtual_screen_rect()
    print(f"▶ 녹화 시작 | 가상 화면 {V_W}x{V_H} (origin= {V_X0},{V_Y0}) | Ctrl+X로 종료")

def stop_recording():
    global is_recording
    is_recording = False
    print(f"■ 녹화 종료: {len(recorded)}개 이벤트(click/scroll) 기록됨")

def toggle_record():
    if is_recording:
        stop_recording()
    else:
        start_recording()

# =========================
# 재생
# =========================
def playback_loop():
    print("▶ 재생 시작 (무한 반복). 정지: alt+Z")
    stop_playback.clear()

    if not recorded:
        print("녹화 데이터 없음. Ctrl+X로 먼저 녹화하세요.")
        return

    try:
        while not stop_playback.is_set():
            for ev in recorded:
                if stop_playback.is_set():
                    break

                typ = ev[0]
                if typ == "click":
                    _, delay, xr, yr, btn_name = ev
                    time.sleep(max(MIN_DELAY, delay))
                    x, y = to_abs(xr, yr)
                    mouse_controller.position = (x, y)
                    time.sleep(AFTER_MOVE_SLEEP)
                    btn = Button.left if btn_name == "left" else Button.right if btn_name == "right" else Button.middle
                    mouse_controller.click(btn, 1)

                elif typ == "scroll":
                    _, delay, xr, yr, dx, dy = ev
                    time.sleep(max(MIN_DELAY, delay))
                    x, y = to_abs(xr, yr)
                    mouse_controller.position = (x, y)
                    time.sleep(AFTER_MOVE_SLEEP)
                    # scroll: dx(수평), dy(수직). 양수=위, 음수=아래
                    mouse_controller.scroll(dx, dy)
                    time.sleep(AFTER_SCROLL_SLEEP)

            time.sleep(0.05)  # 루프 간 짧은 휴식
    finally:
        print("■ 재생 종료")

def toggle_playback():
    global playback_thread
    if playback_thread and playback_thread.is_alive():
        stop_playback.set()
        return
    stop_playback.clear()
    playback_thread = threading.Thread(target=playback_loop, daemon=True)
    playback_thread.start()

# =========================
# 안내 & 메인
# =========================
def print_help():
    print("=== 마우스 매크로 v3 (클릭+스크롤, 듀얼모니터/가상화면 대응) ===")
    print("Ctrl+X : 녹화 시작/종료")
    print("Ctrl+z or alt+Z : 재생 시작/정지 (무한 반복)")
    print("Esc    : 프로그램 종료")
    print("=========================================================")

def main():
    print_help()

    m_listener = mouse.Listener(on_click=on_click, on_scroll=on_scroll)
    m_listener.start()

    def safe_quit():
        stop_playback.set()
        m_listener.stop()
        hotkeys.stop()
        os._exit(0) # 프로그램 강제 종료

    hotkeys = keyboard.GlobalHotKeys({
        '<ctrl>+x': toggle_record,
        '<alt>+z': toggle_playback,
        '<ctrl>+z': toggle_playback,  # (권장) Alt+Z 충돌 대비용
        '<esc>':    safe_quit
    })
    hotkeys.start()
    hotkeys.join()

if __name__ == "__main__":
    main()
