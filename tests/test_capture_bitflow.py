"""Phase 9: the GOX on the BitFlow card (src/capture/bitflow.py), with a fake BFModule.
The real camera is checked by hand on ARAN99 (docs/capture/bench_results.md)."""
import types

import numpy as np
import pytest

from src.capture import bitflow

W, H = 64, 48


class FakeCamera:
    """GenICam nodes + a log of what was set, and whether TLParamsLocked allowed it."""
    def __init__(self, trigger="On", fmt="BayerRG8", answers=True):
        self.nodes = {"TriggerSelector": "AcquisitionStart", "PixelFormat": fmt, "Width": W, "Height": H,
                      "TLParamsLocked": 1}
        self.trigger = {"AcquisitionStart": "Off", "FrameStart": trigger}
        self.log, self.answers, self.closed = [], answers, False

    def get(self, name):
        return self.trigger[self.nodes["TriggerSelector"]] if name == "TriggerMode" else self.nodes[name]

    def set(self, name, value):
        if name in ("TriggerMode", "TriggerSelector") and self.nodes["TLParamsLocked"] != 0:
            raise RuntimeError(f"{name} is locked")
        self.log.append((name, value))
        if name == "TriggerMode":
            self.trigger[self.nodes["TriggerSelector"]] = value
        else:
            self.nodes[name] = value


def fake_module(cam: FakeCamera, frames=True):
    class Node:
        def __init__(self, n): self.n = n
        @property
        def EntrySymbolic(self): return cam.get(self.n)
        @EntrySymbolic.setter
        def EntrySymbolic(self, v): cam.set(self.n, v)
        @property
        def IntValue(self): return cam.get(self.n)
        @IntValue.setter
        def IntValue(self, v): cam.set(self.n, v)
        def Execute(self): cam.log.append(("cmd", self.n))

    class Device:
        def Open(self, ciraq):
            if not cam.answers:
                raise RuntimeError("GenICam Runtime exception")
        def getNode(self, n): return n
        def Close(self): cam.closed = True

    class Ciraq:
        def Open(self, board): cam.log.append(("open board", board))
        def BufferSetup(self, n):
            pattern = np.tile(np.array([[200, 120], [120, 40]], np.uint8), (H // 2, W // 2))  # R G / G B
            return [pattern.copy() for _ in range(n)]
        def AqSetup(self, o): pass
        def AqControl(self, c, o): cam.log.append(("aq", c))
        def WaitForFrame(self, ms):
            if not frames:
                raise TimeoutError
            return types.SimpleNamespace(BufferNumber=0)
        def AqCleanup(self): pass
        def BufferCleanup(self): pass
        def Close(self): cam.log.append(("close board",))

    buf = types.SimpleNamespace(clsCircularAcquisition=Ciraq, SetupOptions=types.SimpleNamespace(setupDefault=0),
                                AcqCommands=types.SimpleNamespace(Start="start", Stop="stop"),
                                AcqControlOptions=types.SimpleNamespace(Wait=0))
    gtl = types.SimpleNamespace(BFGTLDevice=Device, EnumerationNode=Node, IntegerNode=Node, CommandNode=Node)
    return types.SimpleNamespace(BufferAcquisition=buf, BFGTLUtils=gtl)


@pytest.fixture
def card(monkeypatch, tmp_path):
    monkeypatch.setattr(bitflow, "restore_file", lambda board: tmp_path / f"board{board}_trigger.json")
    monkeypatch.setattr(bitflow, "video_service_running", lambda: False)
    monkeypatch.setattr(bitflow, "boards_on_pc", lambda: 1)
    monkeypatch.setattr(bitflow, "load_genicam_settings", lambda: None)

    def use(cam, frames=True):
        monkeypatch.setattr(bitflow, "import_bfmodule", lambda: fake_module(cam, frames))
    return use


def test_free_run_while_open_and_trigger_put_back_on_close(card):
    cam = FakeCamera(trigger="On"); card(cam)
    src = bitflow.BitFlowSource(0, "Right")
    r = src.open(1920, 1080)
    assert r.ok and (r.width, r.height) == (W, H)                    # the camera's own size
    assert cam.trigger["FrameStart"] == "Off"                         # free run while Capture has it
    assert cam.nodes["TriggerSelector"] == "AcquisitionStart"         # selector left as found
    assert cam.nodes["TLParamsLocked"] == 1                           # relocked
    src.close()
    assert cam.trigger["FrameStart"] == "On"                          # trigger put back for ARAN
    assert cam.nodes["TriggerSelector"] == "AcquisitionStart" and cam.nodes["TLParamsLocked"] == 1
    assert cam.closed and ("close board",) in cam.log
    assert not any(n in ("ExposureTime", "AcquisitionFrameRate") for n, *_ in cam.log)  # nothing else changed


def test_refuses_while_aran_video_service_runs(card, monkeypatch):
    cam = FakeCamera(); card(cam)
    monkeypatch.setattr(bitflow, "video_service_running", lambda: True)
    r = bitflow.BitFlowSource(0, "Right").open()
    assert not r.ok and "FR Video Service" in r.message and not cam.log      # board never touched


def test_board_not_on_pc_is_never_opened(card):
    cam = FakeCamera(); card(cam)
    r = bitflow.BitFlowSource(1, "Right").open()
    assert not r.ok and "board 1 is not on this PC" in r.message and not cam.log


def test_camera_not_answering_closes_the_board(card):
    cam = FakeCamera(answers=False); card(cam)
    r = bitflow.BitFlowSource(0, "Right").open()
    assert not r.ok and "did not answer" in r.message and ("close board",) in cam.log
    assert cam.trigger["FrameStart"] == "On"                          # nothing changed


def test_no_frames_closes_and_puts_trigger_back(card):
    cam = FakeCamera(trigger="On"); card(cam, frames=False)
    r = bitflow.BitFlowSource(0, "Right").open()
    assert not r.ok and "no pictures" in r.message
    assert cam.trigger["FrameStart"] == "On" and ("close board",) in cam.log


def test_bayer_rg_comes_out_with_red_and_blue_right():
    """Camera 'BayerRG' (R at top-left) -> OpenCV BayerBG: a red-ish scene stays red."""
    raw = np.tile(np.array([[200, 120], [120, 40]], np.uint8), (H // 2, W // 2))
    bgr = bitflow.to_bgr(raw, W, H, "BayerRG8")
    b, g, r = (float(bgr[8:-8, 8:-8, i].mean()) for i in range(3))
    assert bgr.shape == (H, W, 3) and r > g > b and abs(r - 200) < 5 and abs(b - 40) < 5


def test_12_bit_is_scaled_to_8():
    raw = np.full((H, W), 4095, "<u2")
    out = bitflow.to_bgr(raw, W, H, "BayerRG12")
    assert out.dtype == np.uint8 and out.max() == 255


def test_ports_and_board_numbers():
    assert bitflow.is_bitflow_port("0-GOX-16205C-CXP") and not bitflow.is_bitflow_port("Video (00-0 Pro Capture)")
    assert bitflow.board_number("0-GOX-16205C-CXP") == 0 and bitflow.board_number("2-GOX-X-CXP") == 2


def test_crash_while_open_next_open_still_puts_the_trigger_back(card, tmp_path):
    """Capture killed while the camera is in free run: the next Capture restores the original."""
    cam = FakeCamera(trigger="On"); card(cam)
    first = bitflow.BitFlowSource(0, "Right")
    assert first.open().ok and cam.trigger["FrameStart"] == "Off"
    assert (tmp_path / "board0_trigger.json").exists()               # written before the change
    # ...Capture dies here: no close().  The camera is left in free run.
    second = bitflow.BitFlowSource(0, "Right")
    assert second.open().ok
    assert ("TriggerMode", "On") in second._restore                    # from the file, not the "Off" it saw
    second.close()
    assert cam.trigger["FrameStart"] == "On"
    assert not (tmp_path / "board0_trigger.json").exists()           # cleared after the restore


def test_restore_file_cleared_after_normal_close(card, tmp_path):
    cam = FakeCamera(trigger="Off"); card(cam)
    s = bitflow.BitFlowSource(0, "Right"); assert s.open().ok; s.close()
    assert cam.trigger["FrameStart"] == "Off" and not (tmp_path / "board0_trigger.json").exists()
