import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path

from gesture_lab.config import ROOT

logger = logging.getLogger(__name__)
PROFILE_PATH = ROOT / "camera_profile.json"


def matches_device(profile, camera_index):
    device = Path(f"/dev/video{camera_index}")
    identity = Path("/dev/v4l/by-id") / profile["device_id"]
    return identity.exists() and identity.resolve() == device.resolve()


def apply_camera_profile(camera_index, tuned=True, status=None):
    if not sys.platform.startswith("linux") or not PROFILE_PATH.is_file():
        return False
    executable = shutil.which("v4l2-ctl")
    if executable is None:
        return False
    try:
        with PROFILE_PATH.open(encoding="utf-8") as handle:
            profile = json.load(handle)
        if not matches_device(profile, camera_index):
            return False
        controls = dict(profile["controls"] if tuned else profile["auto_controls"])
        exposure_mode = controls.pop("auto_exposure")
        base = [executable, "-d", f"/dev/video{camera_index}"]
        subprocess.run([*base, f"--set-ctrl=auto_exposure={exposure_mode}"],
                       check=True, capture_output=True, text=True, timeout=3)
        if controls:
            values = ",".join(f"{key}={value}" for key, value in controls.items())
            subprocess.run([*base, "--set-ctrl=" + values],
                           check=True, capture_output=True, text=True, timeout=3)
        if status:
            status("Применена настройка камеры для движения" if tuned else "Включена автоэкспозиция камеры")
        return True
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        logger.warning("Не удалось применить профиль камеры: %s", error)
        if status:
            status("Профиль камеры не применён: " + str(error))
        return False
