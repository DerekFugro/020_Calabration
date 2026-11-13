"""dshow_names.py - DirectShow video input names, in DirectShow's own order.

OpenCV's cv2.CAP_DSHOW index N is the N-th device of the video input category, so the
camera is picked by its *name* (e.g. "Video (01-1 Pro Capture Dual SDI 4K+)") and the
index found here, never by a hard-coded number (ports differ between vans).
Read only: lists devices, opens nothing.  Windows only (comtypes); elsewhere [].
"""

from __future__ import annotations

import sys
from ctypes import POINTER, byref, c_ulong, c_void_p


def video_inputs() -> list[str]:
    """Friendly names of the video inputs, index order = cv2.CAP_DSHOW index order."""
    if sys.platform != "win32":
        return []
    try:
        return _list()
    except Exception:  # noqa: BLE001 - no DirectShow / COM trouble: nothing to pick from
        return []


def _list() -> list[str]:
    import comtypes
    from comtypes import COMMETHOD, GUID, HRESULT, IUnknown
    from comtypes.automation import VARIANT
    from comtypes.persist import IPropertyBag

    class IPersist(IUnknown):
        _iid_ = GUID("{0000010c-0000-0000-C000-000000000046}")
        _methods_ = [COMMETHOD([], HRESULT, "GetClassID", (["out"], POINTER(GUID), "pClassID"))]

    class IPersistStream(IPersist):
        _iid_ = GUID("{00000109-0000-0000-C000-000000000046}")
        _methods_ = [COMMETHOD([], HRESULT, "IsDirty"),
                     COMMETHOD([], HRESULT, "Load", (["in"], c_void_p, "pStm")),
                     COMMETHOD([], HRESULT, "Save", (["in"], c_void_p, "pStm"), (["in"], c_ulong, "fClearDirty")),
                     COMMETHOD([], HRESULT, "GetSizeMax", (["out"], POINTER(c_void_p), "pcbSize"))]

    class IMoniker(IPersistStream):
        _iid_ = GUID("{0000000f-0000-0000-C000-000000000046}")
        _methods_ = [COMMETHOD([], HRESULT, "BindToObject", (["in"], c_void_p, "pbc"), (["in"], c_void_p, "pmkToLeft"),
                               (["in"], POINTER(GUID), "riidResult"), (["out"], POINTER(c_void_p), "ppvResult")),
                     COMMETHOD([], HRESULT, "BindToStorage", (["in"], c_void_p, "pbc"), (["in"], c_void_p, "pmkToLeft"),
                               (["in"], POINTER(GUID), "riid"), (["out"], POINTER(POINTER(IUnknown)), "ppvObj"))]

    class IEnumMoniker(IUnknown):
        _iid_ = GUID("{00000102-0000-0000-C000-000000000046}")
        _methods_ = [COMMETHOD([], HRESULT, "Next", (["in"], c_ulong, "celt"),
                               (["out"], POINTER(POINTER(IMoniker)), "rgelt"), (["out"], POINTER(c_ulong), "pceltFetched")),
                     COMMETHOD([], HRESULT, "Skip", (["in"], c_ulong, "celt")),
                     COMMETHOD([], HRESULT, "Reset"),
                     COMMETHOD([], HRESULT, "Clone", (["out"], POINTER(c_void_p), "ppenum"))]

    class ICreateDevEnum(IUnknown):
        _iid_ = GUID("{29840822-5B84-11D0-BD3B-00A0C911CE86}")
        _methods_ = [COMMETHOD([], HRESULT, "CreateClassEnumerator", (["in"], POINTER(GUID), "clsidDeviceClass"),
                               (["out"], POINTER(POINTER(IEnumMoniker)), "ppEnumMoniker"), (["in"], c_ulong, "dwFlags"))]

    CLSID_SystemDeviceEnum = GUID("{62BE5D10-60EB-11d0-BD3B-00A0C911CE86}")
    CLSID_VideoInputDeviceCategory = GUID("{860BB310-5D01-11d0-BD3B-00A0C911CE86}")
    comtypes.CoInitialize()
    dev_enum = comtypes.CoCreateInstance(CLSID_SystemDeviceEnum, ICreateDevEnum)
    enum = dev_enum.CreateClassEnumerator(byref(CLSID_VideoInputDeviceCategory), 0)
    if not enum:                                   # S_FALSE: no video inputs at all
        return []
    names = []
    while True:
        moniker, fetched = enum.Next(1)
        if not fetched:
            break
        bag = moniker.BindToStorage(None, None, byref(IPropertyBag._iid_)).QueryInterface(IPropertyBag)
        v = VARIANT()
        try:
            names.append(str(bag.Read("FriendlyName", v, None)))
        except Exception:  # noqa: BLE001
            names.append("")
    return names


if __name__ == "__main__":
    for i, n in enumerate(video_inputs()):
        print(i, n)
