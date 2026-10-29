"""check_env.py — Verify all project dependencies are importable and print versions."""

import sys


def check(label, fn):
    try:
        version = fn()
        print(f"  OK  {label:<30} {version}")
        return True
    except Exception as exc:
        print(f"FAIL  {label:<30} {exc}")
        return False


def main():
    print(f"\n{'='*55}")
    print("  Calibration — Environment Check")
    print(f"{'='*55}")
    print(f"  Python: {sys.version}\n")

    results = [
        check("PySide6", lambda: __import__("PySide6").__version__),
        check("cv2 (opencv-contrib)", lambda: __import__("cv2").__version__),
        check("numpy", lambda: __import__("numpy").__version__),
        check("fpdf2", lambda: __import__("fpdf").__version__),
        check("pyyaml", lambda: __import__("yaml").__version__),
        check("pytest", lambda: __import__("pytest").__version__),
    ]

    # Verify ArUco submodule is present (requires contrib build)
    try:
        import cv2
        _ = cv2.aruco.DICT_5X5_50
        print(f"  OK  {'cv2.aruco (contrib check)':<30} DICT_5X5_50 accessible")
        results.append(True)
    except AttributeError:
        print(f"FAIL  {'cv2.aruco (contrib check)':<30} ArUco not found — wrong opencv package?")
        results.append(False)

    print(f"\n{'='*55}")
    if all(results):
        print("  All checks PASSED — environment is ready.")
    else:
        print(f"  {results.count(False)} check(s) FAILED — see above.")
    print(f"{'='*55}\n")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
