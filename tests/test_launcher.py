import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import run


class RuntimeTests(unittest.TestCase):
    def test_supported_linux_python_is_accepted(self):
        with (
            patch("run.sys.platform", "linux"),
            patch("run.sys.version_info", (3, 12, 0)),
            patch("run.platform.machine", return_value="x86_64"),
            patch("run.struct.calcsize", return_value=8),
        ):
            run.check_runtime()

    def test_old_python_is_rejected_before_installing_anything(self):
        with patch("run.sys.version_info", (3, 9, 0)), self.assertRaisesRegex(RuntimeError, "Python 3.12"):
            run.check_runtime()

    def test_intel_mac_requires_python_supported_by_legacy_mediapipe(self):
        with (
            patch("run.sys.platform", "darwin"),
            patch("run.sys.version_info", (3, 14, 0)),
            patch("run.platform.machine", return_value="x86_64"),
            self.assertRaisesRegex(RuntimeError, "Intel Mac"),
        ):
            run.check_runtime()

    def test_unsupported_linux_arm_has_an_actionable_error(self):
        with (
            patch("run.sys.platform", "linux"),
            patch("run.platform.machine", return_value="aarch64"),
            self.assertRaisesRegex(RuntimeError, "Linux ARM"),
        ):
            run.check_runtime()

    def test_environment_paths_cover_windows_and_unix(self):
        root = Path("environment")
        with patch("run.sys.platform", "win32"):
            self.assertEqual(run.environment_python(root), root / "Scripts" / "python.exe")
        with patch("run.sys.platform", "darwin"):
            self.assertEqual(run.environment_python(root), root / "bin" / "python")


class EnvironmentTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.requirements = self.root / "requirements.txt"
        self.requirements.write_text("mediapipe==0.10.35\n", encoding="utf-8")
        self.executable = run.environment_python(self.root / ".venv")

    def tearDown(self):
        self.directory.cleanup()

    def create_environment(self, directory):
        self.executable.parent.mkdir(parents=True)
        self.executable.touch()

    def test_first_launch_creates_environment_and_installs_locally(self):
        with (
            patch("run.venv.EnvBuilder") as builder,
            patch("run.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as command,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            builder.return_value.create.side_effect = self.create_environment
            self.assertEqual(run.prepare_environment(self.root), self.executable)
        builder.assert_called_once_with(with_pip=True)
        arguments = command.call_args.args[0]
        self.assertEqual(arguments[:4], [str(self.executable), "-m", "pip", "install"])
        self.assertEqual(arguments[-1], str(self.requirements))
        self.assertTrue((self.root / ".venv" / ".gesture-lab-requirements").is_file())

    def test_repeat_launch_needs_no_pip_or_internet(self):
        self.create_environment(self.root / ".venv")
        with (
            patch("run.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as command,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            run.prepare_environment(self.root)
            command.reset_mock()
            run.prepare_environment(self.root)
        command.assert_called_once()
        self.assertEqual(command.call_args.args[0][1], "-c")

    def test_changed_requirements_are_reinstalled(self):
        self.create_environment(self.root / ".venv")
        with (
            patch("run.subprocess.run", return_value=subprocess.CompletedProcess([], 0)) as command,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            run.prepare_environment(self.root)
            self.requirements.write_text("mediapipe==0.10.21\n", encoding="utf-8")
            command.reset_mock()
            run.prepare_environment(self.root)
        self.assertIn("pip", command.call_args.args[0])

    def test_failed_install_does_not_mark_environment_as_ready(self):
        self.create_environment(self.root / ".venv")
        with (
            patch("run.subprocess.run", side_effect=subprocess.CalledProcessError(1, "pip")),
            contextlib.redirect_stdout(io.StringIO()),
            self.assertRaises(subprocess.CalledProcessError),
        ):
            run.prepare_environment(self.root)
        self.assertFalse((self.root / ".venv" / ".gesture-lab-requirements").exists())

    def test_app_arguments_and_exit_code_are_preserved(self):
        with (
            patch("run.check_runtime"),
            patch("run.prepare_environment", return_value=self.executable),
            patch("run.subprocess.run", return_value=subprocess.CompletedProcess([], 7)) as command,
        ):
            self.assertEqual(run.main(["--demo", "--camera", "1"]), 7)
        self.assertEqual(command.call_args.args[0], [
            str(self.executable), str(run.ROOT / "main.py"), "--demo", "--camera", "1",
        ])

    def test_setup_only_does_not_open_a_window(self):
        with (
            patch("run.check_runtime"),
            patch("run.prepare_environment", return_value=self.executable),
            patch("run.subprocess.run") as command,
        ):
            self.assertEqual(run.main(["--setup-only"]), 0)
        command.assert_not_called()


if __name__ == "__main__":
    unittest.main()
