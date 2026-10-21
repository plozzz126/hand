import base64
import os
import tempfile
import time
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF
from PySide6.QtGui import QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from gesture_lab.camera import FramePacket
from gesture_lab.config import DEFAULT_CONFIG
from gesture_lab.gestures import Observation
from gesture_lab.portal import PortalState
from gesture_lab.ui import MainWindow

GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAkKAAAALAAAAAABAAEAAAICRAEAOw==")


class InterfaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.application = QApplication.instance() or QApplication([])
        cls.application.setQuitOnLastWindowClosed(False)

    def setUp(self):
        with patch("gesture_lab.ui.load_config", return_value=deepcopy(DEFAULT_CONFIG)):
            self.window = MainWindow(demo=True)
        self.window.show()

    def tearDown(self):
        self.window.saver.stop()
        self.window.close()
        self.window.deleteLater()
        self.application.processEvents()

    def test_all_actions_play_without_camera(self):
        self.window.overlay_checkbox.setChecked(True)
        for gesture in self.window.config["bindings"]:
            self.window.trigger(gesture, manual=True)
            self.application.processEvents()
            self.assertTrue(self.window.scene.isVisible())
            self.assertIn("Проверка:", self.window.history.text())
            self.assertFalse(self.window.scene.grab().isNull())
        self.assertIsNone(self.window.worker)

    def test_camera_uses_full_width_with_gifs_temporarily_disabled(self):
        self.application.processEvents()
        self.assertFalse(self.window.scene.isWindow())
        self.assertIs(self.window.scene.window(), self.window)
        self.assertFalse(self.window.settings_dock.isVisible())
        self.assertTrue(self.window.skeleton.isChecked())
        self.assertFalse(self.window.overlay_checkbox.isChecked())
        self.assertFalse(self.window.scene.isVisible())
        self.assertGreater(self.window.video.width(), self.window.centralWidget().width() * 0.85)

    def test_effects_overlay_the_camera_and_yield_to_two_hand_glass(self):
        self.window.overlay_checkbox.setChecked(True)
        self.window.trigger("Victory", manual=True)
        self.assertTrue(self.window.video.overlay.isVisible())
        self.window.video.portal_active = True
        self.window.video.update_overlay()
        self.assertFalse(self.window.video.overlay.isVisible())
        self.window.video.portal_active = False
        self.window.video.update_overlay()
        self.assertTrue(self.window.video.overlay.isVisible())
        self.window.trigger("Closed_Fist", manual=True)
        self.assertFalse(self.window.video.overlay.isVisible())

    def test_camera_controls_are_grouped_in_collapsible_settings(self):
        self.application.processEvents()
        for control in (self.window.camera_index, self.window.mirror,
                        self.window.skeleton, self.window.camera_tuning,
                        self.window.gpu_acceleration, self.window.overlay_checkbox):
            self.assertTrue(self.window.settings_dock.isAncestorOf(control))
            self.assertFalse(control.isVisible())
        self.window.settings_button.click()
        self.application.processEvents()
        self.assertTrue(self.window.settings_dock.isVisible())
        self.assertTrue(self.window.settings_button.isChecked())
        self.assertTrue(self.window.mirror.isVisible())
        self.window.settings_dock.close()
        self.application.processEvents()
        self.assertFalse(self.window.settings_button.isChecked())

    def test_live_badge_and_metrics_reflect_processed_camera_frame(self):
        from unittest.mock import Mock

        image = QImage(1280, 720, QImage.Format.Format_RGB888)
        image.fill(0)
        worker = Mock()
        worker.isInterruptionRequested.return_value = False
        worker.take_packet.return_value = FramePacket(image, Observation(), 29.9, time.monotonic())
        self.window.worker = worker
        try:
            self.window.poll_camera()
            self.application.processEvents()
            self.assertEqual(self.window.connection_badge.text(), "●  В ЭФИРЕ")
            self.assertEqual(self.window.fps_label.text(), "1280 × 720 · 30 FPS")
            self.assertIn("CPU", self.window.fps_label.toolTip())
            self.assertTrue(self.window.video.hud.isVisible())
            self.assertTrue(self.window.video.image_rect().contains(QRectF(self.window.video.hud.geometry())))
        finally:
            self.window.worker = None

    def test_minimizing_pauses_processing_and_restoring_resumes_it(self):
        from unittest.mock import Mock

        worker = Mock()
        self.window.worker = worker
        try:
            self.window.showMinimized()
            self.application.processEvents()
            self.assertTrue(worker.paused)
            self.window.showNormal()
            self.application.processEvents()
            self.assertFalse(worker.paused)
        finally:
            self.window.worker = None

    def test_gpu_preference_is_saved_and_passed_to_camera_worker(self):
        self.window.gpu_acceleration.setChecked(False)
        self.assertFalse(self.window.config["gpu_acceleration"])
        with patch("gesture_lab.ui.CameraWorker") as worker:
            self.window.toggle_camera()
            try:
                self.assertFalse(worker.call_args.kwargs["use_gpu"])
                self.assertFalse(self.window.gpu_acceleration.isEnabled())
                worker.return_value.start.assert_called_once()
            finally:
                self.window.camera_finished()
        self.assertTrue(self.window.gpu_acceleration.isEnabled())

    def test_portal_blocks_single_hand_actions(self):
        from unittest.mock import Mock

        image = QImage(640, 480, QImage.Format.Format_RGB888)
        image.fill(0)
        portal = PortalState(((0.2, 0.2), (0.8, 0.2), (0.8, 0.7), (0.2, 0.7)), 1, 1)
        packet = FramePacket(image, Observation("Open_Palm", 0.99, 2), 30, time.monotonic(), portal)
        worker = Mock()
        worker.isInterruptionRequested.return_value = False
        worker.take_packet.return_value = packet
        self.window.worker = worker
        try:
            with patch.object(self.window, "trigger") as trigger:
                self.window.poll_camera()
                trigger.assert_not_called()
                self.assertTrue(self.window.video.portal_active)
                self.assertEqual(self.window.gesture_label.text(), "Интерактивное стекло")
        finally:
            self.window.worker = None

    def test_changing_effect_updates_selected_binding(self):
        self.window.select_gesture(1)
        self.window.effect_combo.setCurrentIndex(self.window.effect_combo.findData("hearts"))
        self.assertEqual(self.window.config["bindings"]["Victory"], {"type": "effect", "value": "hearts"})
        self.assertEqual(self.window.config["bindings"]["Open_Palm"]["value"], "portal")

    def test_gif_import_is_copied_played_and_survives_source_removal(self):
        self.window.overlay_checkbox.setChecked(True)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "original.gif"
            source.write_bytes(GIF)
            with (
                patch("gesture_lab.ui.ROOT", root),
                patch("gesture_lab.config.ROOT", root),
                patch("gesture_lab.ui.GIF_DIR", root / "assets" / "gifs"),
                patch("gesture_lab.ui.QFileDialog.getOpenFileName", return_value=(str(source), "GIF")),
            ):
                self.window.choose_gif()
                binding = self.window.config["bindings"]["Open_Palm"]
                self.assertEqual(binding["type"], "gif")
                source.unlink()
                self.window.trigger("Open_Palm", manual=True)
                QTest.qWait(150)
                self.assertIsNotNone(self.window.scene.movie)
                self.assertTrue(self.window.scene.movie.isValid())
                self.assertTrue(self.window.scene.isVisible())
                self.window.scene.close()
                self.assertFalse(self.window.scene.isVisible())
                self.window.trigger("Open_Palm", manual=True)
                self.assertTrue(self.window.scene.isVisible())
                self.window.scene.stop_movie()
                self.window.overlay_checkbox.setChecked(False)
                self.window.trigger("Open_Palm", manual=True)
                self.assertIsNone(self.window.scene.movie)
                self.assertFalse(self.window.scene_container.isVisible())
                self.assertEqual(self.window.config["bindings"]["Open_Palm"], binding)

    def test_missing_gif_reports_error_without_crashing(self):
        self.window.overlay_checkbox.setChecked(True)
        self.window.config["bindings"]["Victory"] = {"type": "gif", "value": "/missing/gesture-lab.gif"}
        self.window.trigger("Victory", manual=True)
        self.assertIn("GIF не найдена", self.window.history.text())

    def test_cancelled_gif_dialog_preserves_binding(self):
        previous = deepcopy(self.window.config["bindings"])
        with patch("gesture_lab.ui.QFileDialog.getOpenFileName", return_value=("", "")):
            self.window.effect_combo.setCurrentIndex(self.window.effect_combo.findData("gif"))
        self.assertEqual(self.window.config["bindings"], previous)
        self.assertEqual(self.window.effect_combo.currentData(), "portal")


if __name__ == "__main__":
    unittest.main()
