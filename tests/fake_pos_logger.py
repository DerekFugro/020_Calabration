"""A fake POS logger for tests: speaks the POS app's Surveyor protocol (JSON lines on
stdin/stdout, E:\\DP\\POSProcessor\\docs\\Comunication4OtherApps.md) without a POS.

  --protocol N      hello's protocol (2)
  --no-logging      never sends `logging` (start never finishes)
  --start-error T   sends error {"cmd":"start"} instead of logging
  --light L         the light it reports (green)
  --time-scale F    a mark of S seconds lasts S*F seconds (0.01)
  --ignore-quit     never exits on quit / closed stdin (to test the last-resort kill)
"""
import argparse
import json
import os
import re
import sys
import threading
import time

lock = threading.Lock()


def say(d):
    d.setdefault("time", time.strftime("%Y-%m-%dT%H:%M:%S"))
    with lock:
        sys.stdout.write(json.dumps(d) + "\n")
        sys.stdout.flush()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--surveyor", action="store_true")
    p.add_argument("--out", default=".")
    p.add_argument("--protocol", type=int, default=2)
    p.add_argument("--no-logging", action="store_true")
    p.add_argument("--start-error", default="")
    p.add_argument("--light", default="green")
    p.add_argument("--time-scale", type=float, default=0.01)
    p.add_argument("--ignore-quit", action="store_true")
    a = p.parse_args()

    session = os.path.join(a.out, "SurveyorPOS_20261115_120000")
    green = a.light == "green"
    status = {"logging": True, "light": a.light, "message": "POS ready" if green else "Few satellites",
              "detail": "", "ok_to_collect": green, "session_folder": session, "warnings": []}
    active, n = {}, [0]

    def summary(m, complete):
        return {"mark": m["mark"], "label": m["label"], "file": m["file"], "seconds": m["seconds"],
                "rows": 15000 if complete else 300, "complete": complete,
                "green_whole_time": green, "worst_light": a.light, "worst_message": status["message"],
                "max_rms_n_m": 0.35, "max_rms_e_m": 0.35, "max_rms_d_m": 0.44,
                "roll_spread_deg": 0.01, "pitch_spread_deg": 0.01, "heading_spread_deg": 0.016,
                "time_type": "UTC", "first_time1_s": 73090.32, "last_time1_s": 73390.3}

    def finish(m):
        with lock:
            if active.pop(m["mark"], None) is None:
                return
        say({"type": "mark_done", **summary(m, True)})

    say({"type": "hello", "protocol": a.protocol, "pid": os.getpid(), "out": a.out, "heartbeat_s": 60})
    if a.start_error:
        say({"type": "error", "cmd": "start", "error": a.start_error})
    elif not a.no_logging:
        os.makedirs(session, exist_ok=True)
        say({"type": "logging", **status})

    def closing():
        with lock:
            cut = [summary(m, False) for m in active.values()]
            active.clear()
        return cut

    for line in sys.stdin:
        try:
            c = json.loads(line)
        except ValueError:
            say({"type": "error", "error": "not JSON", "line": line.strip()}); continue
        rid = c.get("id")
        rep = {"type": "reply", "cmd": c.get("cmd"), "ok": True}
        if rid is not None:
            rep["id"] = rid
        if c.get("cmd") == "status":
            say({**rep, **status})
        elif c.get("cmd") == "mark":
            folder = c.get("folder")
            if folder and not os.path.isdir(folder):
                say({**rep, "ok": False, "error": f"Folder does not exist: {folder}", **status}); continue
            n[0] += 1
            label = str(c.get("label", ""))
            name = f"{n[0]:02d}_{re.sub(r'[^A-Za-z0-9_.-]', '_', label)}.csv"
            path = os.path.join(folder or os.path.join(session, "marks"), name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write("time1_s,time_type,lat_deg,lon_deg,height_m,roll_deg,pitch_deg,heading_deg,"
                         "speed_mps,align_status,rms_n_m,rms_e_m,rms_d_m,light,message\n")
            secs = float(c.get("seconds", 300))
            m = {"mark": n[0], "label": label, "file": path, "seconds": secs}
            with lock:
                active[n[0]] = m
            say({**rep, **m, **status})
            threading.Timer(secs * a.time_scale, finish, args=(m,)).start()
        elif c.get("cmd") == "quit":
            if a.ignore_quit:
                continue
            say({**rep, "closed_marks": closing(), "session_folder": session, "files": []})
            say({"type": "bye"})
            return
        else:
            say({"type": "error", "error": f"unknown command {c.get('cmd')}", "cmd": c.get("cmd")})
    if a.ignore_quit:
        while True:
            time.sleep(1)
    say({"type": "stopped", "closed_marks": closing(), "session_folder": session, "files": []})
    say({"type": "bye"})


if __name__ == "__main__":
    main()
