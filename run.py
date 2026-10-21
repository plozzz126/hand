import hashlib
import platform
import struct
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def check_runtime():
    if not (3, 10) <= sys.version_info[:2] <= (3, 14) or struct.calcsize("P") != 8:
        raise RuntimeError("Install 64-bit Python 3.12 (supported: Python 3.10-3.14).")
    if sys.platform == "darwin":
        if platform.machine() == "x86_64" and sys.version_info[:2] > (3, 12):
            raise RuntimeError("Intel Mac requires Python 3.10-3.12. Install Python 3.12.")
        version = platform.mac_ver()[0]
        if version and int(version.split(".")[0]) < 14:
            raise RuntimeError("This build requires macOS 14 or newer.")
    elif sys.platform.startswith("linux"):
        if platform.machine().lower() not in ("x86_64", "amd64"):
            raise RuntimeError("This build requires Linux x64; Linux ARM is not supported.")
    elif sys.platform != "win32":
        raise RuntimeError("Supported systems: Windows, Linux x64 and macOS 14+.")


def environment_python(directory):
    return directory / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def prepare_environment(root=ROOT):
    directory = root / ".venv"
    executable = environment_python(directory)
    if not executable.is_file():
        print("Creating .venv...", flush=True)
        venv.EnvBuilder(with_pip=True).create(directory)
    requirements = root / "requirements.txt"
    signature = hashlib.sha256(requirements.read_bytes()).hexdigest()
    marker = directory / ".gesture-lab-requirements"
    current = marker.read_text(encoding="utf-8").strip() if marker.is_file() else None
    ready = False
    if current == signature:
        probe = subprocess.run([
            str(executable), "-c",
            ("from importlib.metadata import version; "
             "[version(name) for name in ('mediapipe', 'opencv-contrib-python', 'PySide6-Essentials')]"),
        ], cwd=root, check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ready = probe.returncode == 0
    if not ready:
        print("Installing dependencies (internet required on first launch)...", flush=True)
        subprocess.run([
            str(executable), "-m", "pip", "install", "--disable-pip-version-check",
            "--only-binary=:all:", "-r", str(requirements),
        ], cwd=root, check=True)
        marker.write_text(signature + "\n", encoding="utf-8")
    return executable


def main(arguments=None):
    arguments = list(sys.argv[1:] if arguments is None else arguments)
    try:
        check_runtime()
        executable = prepare_environment()
        if arguments == ["--setup-only"]:
            return 0
        return subprocess.run([str(executable), str(ROOT / "main.py"), *arguments],
                              cwd=ROOT, check=False).returncode
    except KeyboardInterrupt:
        return 130
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f"Could not start Gesture Lab: {error}", file=sys.stderr)
        print("Check your internet connection and Python version. Recommended: Python 3.12.", file=sys.stderr)
        if sys.platform.startswith("linux"):
            print("Ubuntu/Debian: sudo apt install python3-venv", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
