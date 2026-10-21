import shutil
import time
from copy import deepcopy
from pathlib import Path

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QImage,
    QKeySequence,
    QMovie,
    QPainter,
    QPainterPath,
    QPen,
    QPolygonF,
    QRadialGradient,
    QShortcut,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from gesture_lab.camera import CameraWorker
from gesture_lab.config import (
    DEFAULT_CONFIG,
    DEFAULT_IMAGE,
    EFFECTS,
    GESTURES,
    GIF_DIR,
    ROOT,
    load_config,
    resolve_asset,
    save_config,
)
from gesture_lab.effects import EffectCanvas
from gesture_lab.gestures import GestureGate
from gesture_lab.model import file_sha256
from gesture_lab.portal import portal_description, portal_stretch

STYLE = """
QWidget { background: #101112; color: #eceee9; font-family: 'Adwaita Sans', 'Segoe UI', 'DejaVu Sans'; font-size: 12px; }
QMainWindow { background: #101112; }
QFrame#panel { background: #17191a; border: 1px solid #2a2d2e; border-radius: 18px; }
QLabel { background: transparent; }
QLabel#muted { color: #929790; }
QLabel#title { font-size: 20px; font-weight: 600; letter-spacing: -0.5px; }
QLabel#section { color: #a5aaa1; font-size: 10px; font-weight: 600; letter-spacing: 1.6px; }
QLabel#badge { color: #a6ad9d; background: #232722; border: 1px solid #353d30; border-radius: 10px; padding: 4px 10px; font-size: 10px; }
QLabel#metrics { color: #a8afa7; font-family: 'Adwaita Mono', 'DejaVu Sans Mono'; font-size: 11px; }
QLabel#shortcut { color: #6f766e; font-size: 11px; }
QPushButton { background: #1c1f20; border: 1px solid #343839; border-radius: 10px; padding: 10px 16px; }
QPushButton:hover { background: #282c2d; border-color: #626a5c; }
QPushButton:pressed, QPushButton:checked { background: #30372b; border-color: #81936d; }
QPushButton:focus { border-color: #c9e6ab; }
QPushButton:disabled { color: #5f655e; background: #1a1d1c; border-color: #282d27; }
QPushButton#primary { background: #d3edb8; color: #192115; font-weight: 600; border: 1px solid #d3edb8; }
QPushButton#primary:hover { background: #e1f6cc; border-color: #e1f6cc; }
QPushButton#primary:disabled { background: #68785a; border-color: #68785a; color: #343f2b; }
QPushButton#ghost { background: transparent; border-color: transparent; color: #a5ada2; }
QPushButton#ghost:hover { background: #232725; color: #eceee9; }
QComboBox, QSpinBox { background: #101312; border: 1px solid #343a34; border-radius: 8px; padding: 8px; selection-background-color: #39472e; }
QComboBox QAbstractItemView { background: #1c211b; selection-background-color: #39472e; }
QListWidget { background: #111412; border: none; border-radius: 10px; padding: 5px; outline: none; }
QListWidget::item { padding: 9px; border-radius: 7px; }
QListWidget::item:selected { background: #30392a; color: #d3edb8; }
QListWidget::item:hover { background: #242a22; }
QSlider::groove:horizontal { height: 3px; background: #333a30; border-radius: 1px; }
QSlider::handle:horizontal { background: #d3edb8; width: 12px; margin: -5px 0; border-radius: 6px; }
QProgressBar { background: #32392e; border: none; border-radius: 1px; max-height: 3px; }
QProgressBar::chunk { background: #d3edb8; border-radius: 1px; }
QScrollArea { border: none; background: transparent; }
QScrollBar:vertical { background: transparent; width: 6px; }
QScrollBar::handle:vertical { background: #414a3c; border-radius: 3px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QCheckBox { background: transparent; spacing: 10px; padding: 4px 0; }
QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #55604c; border-radius: 5px; background: #141912; }
QCheckBox::indicator:checked { background: #d3edb8; border: 3px solid #4d5d3e; }
QCheckBox::indicator:disabled { background: #252b21; border-color: #383f32; }
QDockWidget { color: #c1c8b9; font-size: 12px; }
QDockWidget::title { background: #171b16; padding: 14px; }
QToolTip { background: #252d20; color: #e7edde; border: 1px solid #4b5840; padding: 8px; }
"""


def label(text, kind=None):
    widget = QLabel(text)
    if kind:
        widget.setObjectName(kind)
    return widget


def panel():
    widget = QFrame()
    widget.setObjectName("panel")
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(18, 18, 18, 18)
    layout.setSpacing(12)
    return widget, layout


class VideoCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.image = QImage()
        self.gif_frame = QImage()
        self.photo_frame = QImage()
        self.photo_timer = QTimer(self)
        self.photo_timer.setSingleShot(True)
        self.photo_timer.timeout.connect(self.clear_photo)
        self.demo = False
        self.portal_active = False
        self.overlay_enabled = True
        self.overlay = EffectCanvas(self, transparent=True)
        self.overlay.setMinimumSize(1, 1)
        self.overlay.setStyleSheet("background: transparent;")
        self.overlay.hide()
        self.setMinimumSize(330, 250)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def image_rect(self):
        if self.image.isNull():
            return QRectF(self.rect())
        fitted = self.image.size().scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio)
        return QRectF((self.width() - fitted.width()) / 2,
                      (self.height() - fitted.height()) / 2, fitted.width(), fitted.height())

    def update_overlay(self):
        target = self.image_rect()
        self.overlay.setGeometry(target.toRect())
        self.overlay.setVisible(self.overlay_enabled and not self.portal_active
                                and self.overlay.effect not in ("idle", "clear"))
        if hasattr(self, "hud"):
            self.hud.setGeometry(int(target.left()) + 20, int(target.bottom()) - 78,
                                 max(1, min(720, int(target.width()) - 40)), 58)
            self.hud.setVisible(not self.image.isNull())
            self.hud.raise_()
        self.update()

    def play_effect(self, effect):
        self.gif_frame = QImage()
        self.clear_photo()
        self.overlay.play(effect)
        self.update_overlay()

    def show_photo(self, image, duration_ms=2600):
        self.photo_frame = image
        if duration_ms is None:
            self.photo_timer.stop()
        else:
            self.photo_timer.start(duration_ms)
        self.update()

    def clear_photo(self):
        self.photo_timer.stop()
        self.photo_frame = QImage()
        self.update()

    def set_gif_frame(self, frame):
        self.gif_frame = frame
        self.update()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_overlay()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        outline = QPainterPath()
        outline.addRoundedRect(QRectF(self.rect()), 12, 12)
        painter.setClipPath(outline)
        painter.fillRect(self.rect(), QColor("#080a09"))
        target = self.image_rect()
        if not self.image.isNull():
            painter.drawImage(target, self.image)
            if not self.gif_frame.isNull() and self.overlay_enabled and not self.portal_active:
                fitted = self.gif_frame.size().scaled(
                    QSize(int(target.width() * 0.4), int(target.height() * 0.4)),
                    Qt.AspectRatioMode.KeepAspectRatio,
                )
                painter.drawImage(QRectF(target.right() - fitted.width() - 14,
                                        target.top() + 14, fitted.width(), fitted.height()), self.gif_frame)
        else:
            center_x, center_y = self.width() / 2, self.height() / 2 - 45
            painter.save()
            painter.translate(center_x, center_y)
            scale = min(1.0, self.height() / 380)
            painter.scale(scale, scale)
            glow = QRadialGradient(QPointF(0, -10), 240)
            glow.setColorAt(0, QColor(139, 120, 197, 26))
            glow.setColorAt(1, QColor(139, 120, 197, 0))
            painter.fillRect(QRectF(-240, -250, 480, 480), glow)
            for offset, color in ((-18, "#292638"), (0, "#5b506f"), (18, "#b8a4da")):
                points = QPolygonF([QPointF(-76 + offset, -63), QPointF(62 + offset, -87),
                                    QPointF(76 + offset, 48), QPointF(-62 + offset, 72)])
                painter.setBrush(QColor(151, 125, 196, 5))
                painter.setPen(QPen(QColor(color), 1.2))
                painter.drawPolygon(points)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#d3edb8"))
            painter.drawEllipse(QPointF(-58, -63), 3, 3)
            painter.drawEllipse(QPointF(94, 48), 3, 3)
            painter.restore()
            painter.setPen(QColor("#e3e7df"))
            painter.setFont(QFont("Adwaita Sans", min(23, max(12, self.width() // 26)), QFont.Weight.Medium))
            title_top = center_y + 94 * scale
            painter.drawText(QRectF(0, title_top, self.width(), 44), Qt.AlignmentFlag.AlignCenter,
                             "Пространство в твоих руках")
            painter.setPen(QColor("#818a7c"))
            painter.setFont(QFont("Adwaita Sans", 10))
            text = "Деморежим · эффекты доступны в настройках" if self.demo else "Включи камеру. Всё остальное — движением рук."
            painter.drawText(QRectF(0, title_top + 44, self.width(), 30), Qt.AlignmentFlag.AlignCenter, text)
        if not self.photo_frame.isNull():
            fitted = self.photo_frame.size().scaled(
                QSize(int(target.width() * 0.4), int(target.height() * 0.4)),
                Qt.AspectRatioMode.KeepAspectRatio,
            )
            photo_rect = QRectF(target.right() - fitted.width() - 20,
                                target.bottom() - fitted.height() - 20,
                                fitted.width(), fitted.height())
            painter.setPen(QPen(QColor("#d3edb8"), 2))
            painter.setBrush(QColor(10, 12, 10, 235))
            painter.drawRoundedRect(photo_rect.adjusted(-6, -6, 6, 6), 12, 12)
            painter.drawImage(photo_rect, self.photo_frame)


class ScenePanel(QWidget):
    frame_ready = Signal(QImage)
    visual_changed = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.movie = None
        self.native_size = QSize()
        layout = QVBoxLayout(self)
        header = QHBoxLayout()
        self.title = label("ЭФФЕКТЫ / GIF", "section")
        header.addWidget(self.title)
        header.addStretch()
        layout.addLayout(header)
        self.stack = QStackedWidget()
        self.effect = EffectCanvas()
        self.gif = QLabel()
        self.gif.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gif.setStyleSheet("background: #000000;")
        self.gif.setMinimumSize(1, 1)
        self.gif.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.stack.addWidget(self.effect)
        self.stack.addWidget(self.gif)
        layout.addWidget(self.stack, 1)
        self.caption = label("Одна рука — GIF и эффекты. Две руки — стекло прямо на камере.", "muted")
        self.caption.setWordWrap(True)
        layout.addWidget(self.caption)

    def forward_frame(self, frame_number):
        if self.movie:
            self.frame_ready.emit(self.movie.currentImage())

    def stop_movie(self):
        self.gif.clear()
        if self.movie:
            self.movie.stop()
            self.movie.deleteLater()
            self.movie = None

    def play(self, gesture, binding):
        if binding["type"] == "gif":
            path = resolve_asset(binding["value"])
            movie = QMovie(str(path))
            if not path.is_file() or not movie.isValid():
                movie.deleteLater()
                raise ValueError(f"GIF не найдена или повреждена: {path}")
            self.stop_movie()
            self.movie = movie
            movie.setParent(self)
            self.visual_changed.emit("clear")
            movie.frameChanged.connect(self.forward_frame)
            movie.jumpToFrame(0)
            self.native_size = movie.currentImage().size()
            movie.finished.connect(movie.start)
            movie.error.connect(self.movie_error)
            self.gif.setMovie(movie)
            self.stack.setCurrentWidget(self.gif)
            self.caption.setText(path.name)
            self.show()
            self.fit_movie()
            movie.start()
        else:
            self.stop_movie()
            self.stack.setCurrentWidget(self.effect)
            self.effect.play(binding["value"])
            self.visual_changed.emit(binding["value"])
            self.caption.setText(EFFECTS[binding["value"]])
            self.show()
        self.title.setText(GESTURES[gesture][0].upper())

    def movie_error(self, error):
        self.caption.setText("Не удалось прочитать GIF. Выбери другой файл.")
        if self.movie:
            self.movie.stop()

    def fit_movie(self):
        if self.movie and not self.native_size.isEmpty():
            self.movie.setScaledSize(self.native_size.scaled(
                self.gif.size(), Qt.AspectRatioMode.KeepAspectRatio
            ))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        QTimer.singleShot(0, self.fit_movie)

    def hideEvent(self, event):
        if self.movie:
            self.movie.setPaused(True)
        super().hideEvent(event)

    def showEvent(self, event):
        if self.movie:
            self.movie.setPaused(False)
        super().showEvent(event)


class MainWindow(QMainWindow):
    def __init__(self, demo=False, camera_index=None):
        super().__init__()
        self.setWindowTitle("Gesture Lab · Интерактивное стекло")
        self.resize(1280, 800)
        self.setMinimumSize(1000, 680)
        self.setStyleSheet(STYLE)
        config_error = None
        try:
            self.config = load_config()
        except (OSError, ValueError, TypeError) as error:
            self.config = deepcopy(DEFAULT_CONFIG)
            config_error = str(error)
        if camera_index is not None:
            self.config["camera_index"] = max(0, min(camera_index, 99))
        self.worker = None
        self.closing = False
        self.camera_error = False
        self.photo_tracks_gesture = False
        self.photo_release_since = None
        self.demo = demo
        self.gate = GestureGate()
        self.scene = ScenePanel(self)
        self.saver = QTimer(self)
        self.saver.setSingleShot(True)
        self.saver.setInterval(300)
        self.saver.timeout.connect(self.persist)
        self.build_ui()
        self.scene.visual_changed.connect(self.video.play_effect)
        self.scene.frame_ready.connect(self.video.set_gif_frame)
        self.select_gesture(0)
        self.poller = QTimer(self)
        self.poller.setInterval(30)
        self.poller.timeout.connect(self.poll_camera)
        self.poller.start()
        for index, gesture in enumerate(list(GESTURES)[:10]):
            QShortcut(QKeySequence(str((index + 1) % 10)), self,
                      activated=lambda selected=gesture: self.trigger(selected, manual=True))
        QShortcut(QKeySequence("M"), self,
                  activated=lambda: self.trigger("Middle_Finger", manual=True))
        QShortcut(QKeySequence("Ctrl+Space"), self, activated=self.toggle_camera)
        QShortcut(QKeySequence("F11"), self, activated=self.toggle_fullscreen)
        QShortcut(QKeySequence("Escape"), self,
                  activated=lambda: self.showNormal() if self.isFullScreen() else None)
        if config_error:
            self.log(f"Ошибка config.json: {config_error}. Загружены стандартные настройки.")
        else:
            self.log("Касание двух указательных и двух больших пальцев — включить / выключить стекло.")

    def build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(28, 22, 28, 16)
        root.setSpacing(20)
        header = QHBoxLayout()
        header.setSpacing(14)
        mark = label("◇")
        mark.setAlignment(Qt.AlignmentFlag.AlignCenter)
        mark.setFixedSize(42, 42)
        mark.setStyleSheet("background: #d3edb8; color: #26321d; border-radius: 12px; font-size: 32px;")
        header.addWidget(mark)
        heading = QVBoxLayout()
        heading.setSpacing(2)
        heading.addWidget(label("Gesture Lab", "title"))
        heading.addWidget(label("Немного магии. Только твои руки.", "muted"))
        header.addLayout(heading)
        header.addStretch()
        fullscreen = QPushButton("На весь экран  ↗")
        fullscreen.setObjectName("ghost")
        fullscreen.setToolTip("Полный экран · F11")
        fullscreen.clicked.connect(self.toggle_fullscreen)
        header.addWidget(fullscreen)
        self.settings_button = QPushButton("Настройки")
        self.settings_button.setToolTip("Камера, отображение рук, GIF и чувствительность")
        self.settings_button.setCheckable(True)
        self.settings_button.clicked.connect(lambda visible: self.settings_dock.setVisible(visible))
        header.addWidget(self.settings_button)
        root.addLayout(header)
        body = QHBoxLayout()
        body.setSpacing(16)
        left = QVBoxLayout()
        camera_panel, camera_layout = panel()
        camera_layout.setContentsMargins(12, 12, 12, 14)
        camera_layout.setSpacing(14)
        camera_top = QHBoxLayout()
        camera_top.setContentsMargins(8, 2, 8, 0)
        camera_top.setSpacing(14)
        camera_top.addWidget(label("ИНТЕРАКТИВНОЕ СТЕКЛО", "section"))
        self.connection_badge = label("●  НЕАКТИВНА", "badge")
        camera_top.addWidget(self.connection_badge)
        camera_top.addStretch()
        self.fps_label = label("— FPS", "metrics")
        camera_top.addWidget(self.fps_label)
        camera_layout.addLayout(camera_top)
        self.video = VideoCanvas()
        self.video.demo = self.demo
        camera_layout.addWidget(self.video, 1)
        self.status_label = label("Деморежим · камера выключена" if self.demo else "Камера выключена", "muted")
        self.status_label.setWordWrap(True)
        controls = QHBoxLayout()
        controls.setContentsMargins(8, 0, 8, 0)
        controls.setSpacing(18)
        self.camera_button = QPushButton("Включить камеру")
        self.camera_button.setObjectName("primary")
        self.camera_button.setMinimumWidth(190)
        self.camera_button.setFixedHeight(42)
        self.camera_button.setToolTip("Включить / остановить камеру · Ctrl+Space")
        self.camera_button.clicked.connect(self.toggle_camera)
        controls.addWidget(self.camera_button)
        controls.addWidget(self.status_label, 1)
        controls.addWidget(label("Ctrl + Space", "shortcut"))
        camera_layout.addLayout(controls)
        self.camera_index = QSpinBox()
        self.camera_index.setRange(0, 99)
        self.camera_index.setValue(self.config["camera_index"])
        self.camera_index.valueChanged.connect(self.settings_changed)
        self.mirror = QCheckBox("Зеркало")
        self.mirror.setChecked(self.config["mirror"])
        self.mirror.toggled.connect(self.settings_changed)
        self.skeleton = QCheckBox("Суставы и скелет рук")
        self.skeleton.setChecked(True)
        self.skeleton.toggled.connect(self.display_changed)
        self.overlay_checkbox = QCheckBox("GIF и обычные эффекты")
        self.overlay_checkbox.setToolTip("Временно включить GIF и обычные анимации. Искажения двумя руками работают всегда.")
        self.overlay_checkbox.toggled.connect(self.display_changed)
        self.camera_tuning = QCheckBox("Профиль камеры: движение")
        self.camera_tuning.setChecked(self.config["camera_tuned"])
        self.camera_tuning.setToolTip("Настроенная экспозиция для жестов. Выключи для автоматической экспозиции; меняется при остановленной камере.")
        self.camera_tuning.toggled.connect(self.settings_changed)
        self.gpu_acceleration = QCheckBox("Ускорение распознавания на GPU")
        self.gpu_acceleration.setChecked(self.config["gpu_acceleration"])
        self.gpu_acceleration.setToolTip("Разгружает процессор. Если GPU недоступен, используется CPU. Меняется при остановленной камере.")
        self.gpu_acceleration.toggled.connect(self.settings_changed)
        left.addWidget(camera_panel, 1)
        detection, detection_layout = panel()
        detection.setParent(self.video)
        detection.setObjectName("cameraHud")
        detection.setStyleSheet("QFrame#cameraHud { background: rgba(14, 18, 13, 215); border: 1px solid rgba(199, 220, 180, 35); border-radius: 12px; }")
        detection_layout.setContentsMargins(14, 10, 14, 10)
        detection_layout.setSpacing(7)
        self.video.hud = detection
        stats = QGridLayout()
        self.gesture_label = label("Жду жест…")
        self.gesture_label.setStyleSheet("font-size: 12px; font-weight: 600;")
        self.score_label = label("Уверенность: —", "muted")
        stats.addWidget(self.gesture_label, 0, 0)
        stats.addWidget(self.score_label, 0, 1, Qt.AlignmentFlag.AlignRight)
        detection_layout.addLayout(stats)
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.progress.setValue(0)
        detection_layout.addWidget(self.progress)
        body.addLayout(left, 1)
        self.scene_container, scene_layout = panel()
        scene_layout.setContentsMargins(4, 4, 4, 4)
        scene_layout.addWidget(self.scene)
        body.addWidget(self.scene_container, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(355)
        sidebar = QWidget()
        side_layout = QVBoxLayout(sidebar)
        side_layout.setContentsMargins(12, 12, 8, 12)
        side_layout.setSpacing(12)
        capture_panel, capture_layout = panel()
        capture_layout.addWidget(label("КАМЕРА И ОТОБРАЖЕНИЕ", "section"))
        capture_form = QFormLayout()
        capture_form.addRow("Источник", self.camera_index)
        capture_layout.addLayout(capture_form)
        for control in (self.mirror, self.skeleton, self.camera_tuning, self.gpu_acceleration, self.overlay_checkbox):
            capture_layout.addWidget(control)
        side_layout.addWidget(capture_panel)
        binding_panel, binding_layout = panel()
        binding_layout.addWidget(label("ЖЕСТЫ И ДЕЙСТВИЯ", "section"))
        self.gesture_list = QListWidget()
        self.gesture_list.setMinimumHeight(255)
        self.gesture_list.setMaximumHeight(300)
        for index, (gesture, details) in enumerate(GESTURES.items()):
            shortcut = "M" if gesture == "Middle_Finger" else str((index + 1) % 10)
            self.gesture_list.addItem(f"{shortcut}    {details[0]}")
        self.gesture_list.currentRowChanged.connect(self.select_gesture)
        binding_layout.addWidget(self.gesture_list)
        self.hint_label = label("", "muted")
        self.hint_label.setWordWrap(True)
        binding_layout.addWidget(self.hint_label)
        self.effect_combo = QComboBox()
        for key, name in EFFECTS.items():
            self.effect_combo.addItem(name, key)
        self.effect_combo.addItem("Своя GIF", "gif")
        self.effect_combo.addItem("Фото поверх камеры", "image")
        self.effect_combo.currentIndexChanged.connect(self.change_effect)
        binding_layout.addWidget(self.effect_combo)
        self.binding_label = label("", "muted")
        self.binding_label.setWordWrap(True)
        binding_layout.addWidget(self.binding_label)
        actions = QHBoxLayout()
        self.gif_button = QPushButton("Выбрать GIF…")
        self.gif_button.clicked.connect(self.choose_gif)
        actions.addWidget(self.gif_button)
        test_button = QPushButton("Проверить жест")
        test_button.clicked.connect(lambda: self.trigger(self.selected_gesture(), manual=True))
        actions.addWidget(test_button)
        binding_layout.addLayout(actions)
        side_layout.addWidget(binding_panel)
        settings_panel, settings_layout = panel()
        settings_layout.addWidget(label("ЧУВСТВИТЕЛЬНОСТЬ", "section"))
        self.sliders = {}
        form = QFormLayout()
        form.setSpacing(12)
        for key, title, minimum, maximum, step in (
            ("confidence", "Уверенность", 10, 100, 1),
            ("hold_ms", "Удержание", 0, 2000, 50),
            ("cooldown_ms", "Пауза", 0, 10000, 100),
        ):
            row = QWidget()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 0, 0, 0)
            value_label = label("", "muted")
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(minimum, maximum)
            slider.setSingleStep(step)
            slider.setValue(round(self.config[key] * 100) if key == "confidence" else self.config[key])
            slider.valueChanged.connect(self.settings_changed)
            row_layout.addWidget(value_label)
            row_layout.addWidget(slider)
            self.sliders[key] = (slider, value_label)
            form.addRow(title, row)
        settings_layout.addLayout(form)
        side_layout.addWidget(settings_panel)
        side_layout.addStretch()
        scroll.setWidget(sidebar)
        self.settings_dock = QDockWidget("Настройки", self)
        self.settings_dock.setAllowedAreas(Qt.DockWidgetArea.RightDockWidgetArea)
        self.settings_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)
        self.settings_dock.setWidget(scroll)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.settings_dock)
        self.settings_dock.visibilityChanged.connect(self.settings_button.setChecked)
        self.settings_dock.hide()
        root.addLayout(body, 1)
        self.history = label("", "muted")
        self.history.setWordWrap(True)
        self.history.setTextFormat(Qt.TextFormat.PlainText)
        self.history.setMinimumHeight(26)
        self.history.setStyleSheet("color: #858d7e; font-size: 11px;")
        footer = QHBoxLayout()
        footer.setSpacing(16)
        footer.addWidget(self.history, 1)
        footer.addWidget(label("ЛОКАЛЬНО · БЕЗ ЗАПИСИ", "section"))
        root.addLayout(footer)
        self.refresh_slider_labels()
        self.display_changed()

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def display_changed(self, checked=None):
        enabled = self.overlay_checkbox.isChecked()
        self.scene_container.setVisible(enabled)
        self.video.overlay_enabled = enabled
        if not enabled:
            self.scene.stop_movie()
            self.video.play_effect("clear")
        self.video.update_overlay()
        if self.worker:
            self.worker.show_landmarks = self.skeleton.isChecked()

    def selected_gesture(self):
        return list(GESTURES)[max(0, self.gesture_list.currentRow())]

    def select_gesture(self, row):
        if not hasattr(self, "effect_combo") or row < 0:
            return
        if self.gesture_list.currentRow() != row:
            self.gesture_list.setCurrentRow(row)
            return
        gesture = self.selected_gesture()
        self.hint_label.setText(GESTURES[gesture][1])
        binding = self.config["bindings"][gesture]
        value = binding["type"] if binding["type"] in ("gif", "image") else binding["value"]
        self.effect_combo.blockSignals(True)
        self.effect_combo.setCurrentIndex(self.effect_combo.findData(value))
        self.effect_combo.blockSignals(False)
        if binding["type"] in ("gif", "image"):
            self.binding_label.setText(Path(binding["value"]).name)
        else:
            self.binding_label.setText("Встроенная анимация · можно заменить на GIF или фото")

    def change_effect(self, index):
        effect = self.effect_combo.itemData(index)
        if effect == "gif":
            self.choose_gif()
            self.select_gesture(self.gesture_list.currentRow())
            return
        if effect == "image":
            self.config["bindings"][self.selected_gesture()] = {
                "type": "image", "value": DEFAULT_IMAGE,
            }
            self.select_gesture(self.gesture_list.currentRow())
            self.saver.start()
            return
        self.config["bindings"][self.selected_gesture()] = {"type": "effect", "value": effect}
        self.select_gesture(self.gesture_list.currentRow())
        self.saver.start()

    def choose_gif(self):
        filename, _ = QFileDialog.getOpenFileName(self, "Привязать GIF к жесту", str(ROOT), "GIF (*.gif)")
        if not filename:
            return
        movie = QMovie(filename)
        valid = movie.isValid()
        movie.deleteLater()
        if not valid:
            self.log("Этот файл не читается как GIF. Выбери другой.")
            return
        try:
            source = Path(filename)
            digest = file_sha256(source)[:16]
            GIF_DIR.mkdir(parents=True, exist_ok=True)
            target = GIF_DIR / f"{digest}.gif"
            if source.resolve() != target.resolve():
                shutil.copy2(source, target)
            self.config["bindings"][self.selected_gesture()] = {
                "type": "gif", "value": target.relative_to(ROOT).as_posix(),
            }
            self.select_gesture(self.gesture_list.currentRow())
            self.saver.start()
            self.log(f"GIF «{source.name}» привязана к жесту «{GESTURES[self.selected_gesture()][0]}».")
        except OSError as error:
            self.log(f"Не удалось сохранить GIF: {error}")

    def refresh_slider_labels(self):
        for key, (slider, value_label) in self.sliders.items():
            value_label.setText(f"{slider.value()}%" if key == "confidence" else f"{slider.value()} мс")

    def settings_changed(self, value=None):
        if not hasattr(self, "sliders") or len(self.sliders) != 3:
            return
        self.config["camera_index"] = self.camera_index.value()
        self.config["mirror"] = self.mirror.isChecked()
        self.config["camera_tuned"] = self.camera_tuning.isChecked()
        self.config["gpu_acceleration"] = self.gpu_acceleration.isChecked()
        for key, (slider, _) in self.sliders.items():
            self.config[key] = slider.value() / 100 if key == "confidence" else slider.value()
        self.refresh_slider_labels()
        self.gate.reset()
        self.saver.start()

    def persist(self):
        try:
            save_config(self.config)
        except (OSError, ValueError, TypeError) as error:
            self.log(f"Не удалось сохранить настройки: {error}")

    def toggle_camera(self):
        if self.closing:
            return
        if self.worker:
            self.worker.requestInterruption()
            self.camera_button.setEnabled(False)
            self.connection_badge.setText("●  ОСТАНОВКА")
            self.status_label.setText("Останавливаю камеру…")
            return
        self.demo = False
        self.video.demo = False
        self.camera_error = False
        self.gate.reset()
        self.worker = CameraWorker(self.camera_index.value(), self.mirror.isChecked(), self,
                                   show_landmarks=self.skeleton.isChecked(), tuned=self.camera_tuning.isChecked(),
                                   use_gpu=self.gpu_acceleration.isChecked())
        self.worker.paused = self.isMinimized()
        self.worker.status.connect(self.status_label.setText)
        self.worker.failed.connect(self.camera_failed)
        self.worker.finished.connect(self.camera_finished)
        self.camera_index.setEnabled(False)
        self.mirror.setEnabled(False)
        self.camera_tuning.setEnabled(False)
        self.gpu_acceleration.setEnabled(False)
        self.camera_button.setText("Остановить")
        self.connection_badge.setText("●  ПОДКЛЮЧЕНИЕ")
        self.worker.start()

    def camera_failed(self, message):
        self.camera_error = True
        self.connection_badge.setText("●  НЕТ СИГНАЛА")
        self.status_label.setText(message)
        self.log(f"Ошибка камеры: {message}")

    def camera_finished(self):
        worker, self.worker = self.worker, None
        worker.deleteLater()
        self.camera_button.setEnabled(True)
        self.camera_button.setText("Включить камеру")
        self.camera_index.setEnabled(True)
        self.mirror.setEnabled(True)
        self.camera_tuning.setEnabled(True)
        self.gpu_acceleration.setEnabled(True)
        self.video.image = QImage()
        self.video.clear_photo()
        self.photo_tracks_gesture = False
        self.photo_release_since = None
        self.video.portal_active = False
        self.video.update_overlay()
        self.fps_label.setText("— FPS")
        self.connection_badge.setText("●  НЕТ СИГНАЛА" if self.camera_error else "●  НЕАКТИВНА")
        self.gesture_label.setText("Жду жест…")
        self.score_label.setText("Уверенность: —")
        self.progress.setValue(0)
        self.gate.reset()
        if not self.camera_error:
            self.status_label.setText("Камера выключена")
        if self.closing:
            QTimer.singleShot(0, self.close)

    def poll_camera(self):
        if not self.worker or self.worker.isInterruptionRequested():
            return
        packet = self.worker.take_packet()
        if packet is None:
            return
        if time.monotonic() - packet.timestamp > 0.4:
            self.gate.reset()
            self.progress.setValue(0)
            self.video.clear_photo()
            self.photo_tracks_gesture = False
            self.photo_release_since = None
            self.video.portal_active = False
            self.video.update_overlay()
            return
        self.video.image = packet.image
        self.connection_badge.setText("●  В ЭФИРЕ")
        self.video.portal_active = packet.portal is not None
        self.video.update_overlay()
        self.fps_label.setText(f"{packet.image.width()} × {packet.image.height()} · {packet.fps:.0f} FPS")
        self.fps_label.setToolTip(f"Распознавание: {packet.backend}. FPS измерен по готовым обработанным кадрам.")
        observation = packet.observation
        self.update_photo_release(observation, packet.timestamp)
        if packet.contact_changed:
            self.log("Фигура включена — разведи руки и растягивай её."
                     if packet.portal_enabled else "Фигура выключена — повтори касание для включения.")
        if packet.portal is not None:
            self.gesture_label.setText("Интерактивное стекло")
            self.score_label.setText(portal_description(packet.portal))
            self.gate.reset()
            self.progress.setValue(round(portal_stretch(packet.portal) * 100))
            return
        image_action = (
            observation.gesture in self.config["bindings"]
            and self.config["bindings"][observation.gesture]["type"] == "image"
        )
        if packet.contact_progress > 0 or (not self.overlay_checkbox.isChecked() and not image_action):
            if packet.contact_progress >= 1:
                self.gesture_label.setText("Фигура включена" if packet.portal_enabled else "Фигура выключена")
                self.score_label.setText("Касание принято · разведи руки")
            elif packet.contact_progress > 0:
                self.gesture_label.setText("Удержи касание…")
                self.score_label.setText("Для выключения" if packet.portal_enabled else "Для включения")
            elif packet.portal_enabled:
                self.gesture_label.setText("Фигура включена")
                self.score_label.setText("Разведи руки · следующее касание выключит")
            else:
                self.gesture_label.setText("Соедини пальцы двух рук" if observation.hands == 2 else "Покажи обе руки")
                self.score_label.setText("Два указательных + два больших")
            self.progress.setValue(round(packet.contact_progress * 100))
            self.gate.reset()
            return
        self.gesture_label.setText(GESTURES.get(observation.gesture, ("Жест не определён" if observation.hands else "Рука не найдена",))[0])
        self.score_label.setText(f"Уверенность: {observation.confidence:.0%}" if observation.gesture else "Уверенность: —")
        self.gate.hold_ms = self.config["hold_ms"]
        self.gate.cooldown_ms = self.config["cooldown_ms"]
        self.gate.confidence = self.config["confidence"]
        triggered = self.gate.update(observation, packet.timestamp)
        self.progress.setValue(self.gate.progress)
        if triggered:
            self.trigger(triggered)

    def update_photo_release(self, observation, timestamp):
        if not self.photo_tracks_gesture:
            return
        if self.video.photo_frame.isNull():
            self.photo_tracks_gesture = False
            self.photo_release_since = None
            return
        gesture = observation.gesture
        image_action = (
            gesture in self.config["bindings"]
            and self.config["bindings"][gesture]["type"] == "image"
        )
        if image_action:
            self.photo_release_since = None
        elif self.photo_release_since is None:
            self.photo_release_since = timestamp
        elif timestamp - self.photo_release_since >= 0.12:
            self.video.clear_photo()
            self.photo_tracks_gesture = False
            self.photo_release_since = None

    def trigger(self, gesture, manual=False):
        binding = self.config["bindings"][gesture]
        if not self.overlay_checkbox.isChecked() and binding["type"] != "image":
            if manual:
                self.log("GIF и обычные эффекты отключены. Включить их можно в настройках.")
            return
        try:
            if binding["type"] == "image":
                path = resolve_asset(binding["value"])
                image = QImage(str(path))
                if image.isNull():
                    raise ValueError(f"Фото не найдено или повреждено: {path}")
                self.scene.stop_movie()
                self.scene.effect.play("clear")
                self.video.play_effect("clear")
                self.video.show_photo(image, duration_ms=2600 if manual else None)
                self.photo_tracks_gesture = not manual
                self.photo_release_since = None
                description = f"Фото · {path.name}"
            else:
                self.scene.play(gesture, binding)
                description = "GIF" if binding["type"] == "gif" else EFFECTS[binding["value"]]
            self.log(f"{'Проверка' if manual else 'Жест'}: {GESTURES[gesture][0]} → {description}")
        except (OSError, ValueError) as error:
            self.log(str(error))

    def log(self, message):
        self.history.setText(f"{time.strftime('%H:%M:%S')}   {message}")

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and getattr(self, "worker", None):
            self.worker.paused = self.isMinimized()

    def closeEvent(self, event):
        if self.worker:
            self.closing = True
            self.worker.requestInterruption()
            self.camera_button.setEnabled(False)
            self.status_label.setText("Завершаю обработку камеры…")
            event.ignore()
            return
        if self.saver.isActive():
            self.saver.stop()
            self.persist()
        self.scene.stop_movie()
        self.scene.close()
        event.accept()
