"""macOS: Apple's built-in Vision framework for hands and text (offline, fast on Apple silicon) and AVFoundation for the
camera permission."""
import os
import subprocess
import time

NAME = "Mac"


def open_path(p):
    subprocess.run(["open", str(p)])


def _permission(want, send):
    """Ask macOS for the camera ourselves: OpenCV cannot show the prompt from a background thread."""
    try:
        import AVFoundation as AV
    except Exception:
        return True
    st = AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeVideo)
    if st == 3:
        return True
    if st in (1, 2):
        send({"type": "hand", "status": "denied"})
        return False
    send({"type": "hand", "status": "no_camera"})
    AV.AVCaptureDevice.requestAccessForMediaType_completionHandler_(AV.AVMediaTypeVideo, lambda granted: None)
    for _ in range(240):                            # up to 2 minutes for the user to answer
        time.sleep(0.5)
        st = AV.AVCaptureDevice.authorizationStatusForMediaType_(AV.AVMediaTypeVideo)
        if st != 0 or not want():
            break
    if st != 3:
        send({"type": "hand", "status": "denied" if st in (1, 2) else "no_camera"})
    return st == 3


def open_camera(want=lambda: True, send=lambda m: None):
    if not _permission(want, send):
        return None
    os.environ["OPENCV_AVFOUNDATION_SKIP_AUTH"] = "1"
    import cv2
    from .generic import open_camera as _open
    return _open(want, send, cv2.CAP_AVFOUNDATION)


JOINTS = {"wrist": "Wrist", "thumb_tip": "ThumbTip", "thumb_ip": "ThumbIP", "thumb_mp": "ThumbMP",
          "index_tip": "IndexTip", "index_pip": "IndexPIP", "index_mcp": "IndexMCP",
          "middle_tip": "MiddleTip", "middle_pip": "MiddlePIP", "middle_mcp": "MiddleMCP",
          "ring_tip": "RingTip", "ring_pip": "RingPIP", "ring_mcp": "RingMCP",
          "little_tip": "LittleTip", "little_pip": "LittlePIP", "little_mcp": "LittleMCP"}


class VisionHands:
    def __init__(self):
        import Vision
        from Foundation import NSData
        self.V, self.NSData = Vision, NSData
        self.names = {k: getattr(Vision, "VNHumanHandPoseObservationJointName" + v) for k, v in JOINTS.items()}
        self.req = Vision.VNDetectHumanHandPoseRequest.alloc().init()
        self.req.setMaximumHandCount_(2)

    def detect(self, frame):
        import cv2
        ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
        data = self.NSData.dataWithBytes_length_(jpg.tobytes(), len(jpg))
        self.V.VNImageRequestHandler.alloc().initWithData_options_(data, None).performRequests_error_([self.req], None)
        out = []
        for obs in (self.req.results() or [])[:2]:
            pts = {}
            for key, jn in self.names.items():
                p, _err = obs.recognizedPointForJointName_error_(jn, None)
                if p is not None and p.confidence() > 0.3:
                    # Vision: origin bottom-left of the camera image. HUD: mirrored, origin top-left.
                    pts[key] = (1.0 - p.x(), 1.0 - p.y())
            out.append(pts)
        return out


def hand_detector():
    try:
        return VisionHands()
    except ImportError:
        from .generic import hand_detector as mp
        return mp()


def ocr(path):
    """Text boxes on an image: [{"t", "x", "y", "w", "h"}], coordinates 0..1 with y measured from the top."""
    try:
        import Vision
        from Foundation import NSURL
    except ImportError:
        from .generic import ocr as rapid
        return rapid(path)
    url = NSURL.fileURLWithPath_(str(path))
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, None)
    req = Vision.VNRecognizeTextRequest.alloc().init()
    req.setRecognitionLevel_(Vision.VNRequestTextRecognitionLevelAccurate)
    req.setRecognitionLanguages_(["zh-Hans", "en-US"])
    req.setUsesLanguageCorrection_(False)
    res = handler.performRequests_error_([req], None)
    if isinstance(res, tuple) and not res[0]:
        raise RuntimeError(f"text recognition failed: {res[1]}")
    boxes = []
    for obs in req.results() or []:
        cand = obs.topCandidates_(1)
        if not cand:
            continue
        bb = obs.boundingBox()
        x, y, w, h = bb.origin.x, bb.origin.y, bb.size.width, bb.size.height
        boxes.append({"t": str(cand[0].string()).strip(), "x": x, "y": 1 - (y + h), "w": w, "h": h})
    return boxes
