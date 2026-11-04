"""Windows and Linux building blocks (also usable on macOS): OpenCV camera, MediaPipe hands, RapidOCR text."""
import os
import subprocess
import sys
import time

NAME = "computer"

# MediaPipe's 21 hand landmarks, in the joint names gesture.py uses
MP_JOINTS = {0: "wrist", 2: "thumb_mp", 3: "thumb_ip", 4: "thumb_tip", 5: "index_mcp", 6: "index_pip", 8: "index_tip",
             9: "middle_mcp", 10: "middle_pip", 12: "middle_tip", 13: "ring_mcp", 14: "ring_pip", 16: "ring_tip",
             17: "little_mcp", 18: "little_pip", 20: "little_tip"}


def open_path(p):
    p = str(p)
    if sys.platform.startswith("win"):
        os.startfile(p)                                  # noqa: S606 (a local file the user asked for)
    elif sys.platform == "darwin":
        subprocess.run(["open", p])
    else:
        subprocess.run(["xdg-open", p])


def open_camera(want=lambda: True, send=lambda m: None, backend=None):
    import cv2
    api = backend if backend is not None else (cv2.CAP_DSHOW if sys.platform.startswith("win") else cv2.CAP_ANY)
    for attempt in range(20):
        if not want():
            return None
        cap = cv2.VideoCapture(0, api)
        if cap.isOpened():
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            ok, frame = cap.read()
            if ok and frame is not None:
                return cap
        cap.release()
        if attempt == 0:
            send({"type": "hand", "status": "no_camera"})
        time.sleep(1.5)
    return None


class MediaPipeHands:
    def __init__(self):
        import mediapipe as mp
        self.mp = mp.solutions.hands.Hands(static_image_mode=False, max_num_hands=2, model_complexity=0,
                                           min_detection_confidence=0.5, min_tracking_confidence=0.4)

    def detect(self, frame):
        import cv2
        res = self.mp.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        out = []
        for lm in (res.multi_hand_landmarks or [])[:2]:
            # MediaPipe: origin top-left of the camera image. HUD: mirrored, origin top-left.
            out.append({name: (1.0 - lm.landmark[i].x, lm.landmark[i].y) for i, name in MP_JOINTS.items()})
        return out


def hand_detector():
    return MediaPipeHands()


_ocr = None


def ocr(path):
    global _ocr
    if _ocr is None:
        from rapidocr_onnxruntime import RapidOCR
        _ocr = RapidOCR()
    import cv2
    img = cv2.imread(str(path))
    if img is None:
        raise RuntimeError(f"cannot read image {path}")
    H, W = img.shape[:2]
    result, _ = _ocr(img)
    boxes = []
    for quad, text, _score in result or []:
        xs, ys = [p[0] for p in quad], [p[1] for p in quad]
        boxes.append({"t": str(text).strip(), "x": min(xs) / W, "y": min(ys) / H,
                      "w": (max(xs) - min(xs)) / W, "h": (max(ys) - min(ys)) / H})
    return boxes
