import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QWidget


class EffectCanvas(QWidget):
    def __init__(self, parent=None, transparent=False):
        super().__init__(parent)
        self.transparent = transparent
        if transparent:
            self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
            self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.setMinimumSize(300, 240)
        self.effect = "idle"
        self.started = time.monotonic()
        generator = random.Random(17)
        self.particles = [
            (generator.random(), generator.random(), generator.uniform(0.4, 1.5),
             generator.uniform(0, math.tau), generator.randrange(3))
            for _ in range(110)
        ]
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self.update)

    def play(self, effect):
        self.effect = effect
        self.started = time.monotonic()
        self.update()

    def showEvent(self, event):
        self.timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.timer.stop()
        super().hideEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self.transparent:
            painter.fillRect(self.rect(), QColor("#000000"))
        width, height = self.width(), self.height()
        center = QPointF(width / 2, height / 2)
        scale = min(width, height)
        elapsed = time.monotonic() - self.started
        colors = [QColor("#80f5ce"), QColor("#ad94ff"), QColor("#ff92b5")]
        if self.effect in ("idle", "clear"):
            if self.transparent:
                return
            painter.setPen(QColor("#78859d"))
            painter.setFont(QFont("Sans Serif", 14))
            painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter,
                             "Сцена очищена" if self.effect == "clear" else "Покажи жест — здесь появится эффект")
            return
        if self.effect in ("portal", "pulse", "orbit"):
            for index in range(8):
                phase = (elapsed * 0.24 + index / 8) % 1
                radius = scale * (0.08 + phase * 0.38)
                color = QColor(colors[index % 3])
                color.setAlphaF((1 - phase) * 0.75)
                painter.setPen(QPen(color, 2 if self.effect != "pulse" else 4))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                ellipse = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
                if self.effect == "portal":
                    painter.drawArc(ellipse, int((elapsed * 50 + index * 43) * 16), 260 * 16)
                else:
                    painter.drawEllipse(ellipse)
                if self.effect == "orbit":
                    angle = elapsed * (0.5 + index * 0.13) + index
                    painter.setBrush(colors[index % 3])
                    painter.drawEllipse(QPointF(center.x() + math.cos(angle) * radius,
                                                center.y() + math.sin(angle) * radius), 6, 6)
        for horizontal, vertical, speed, phase, color_index in self.particles:
            color = QColor(colors[color_index])
            color.setAlphaF(0.35 + speed * 0.4)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(color)
            if self.effect in ("rain", "confetti", "hearts"):
                position_x = horizontal * width + math.sin(elapsed * speed + phase) * 22
                direction = -1 if self.effect == "hearts" else 1
                position_y = ((vertical + elapsed * speed * 0.15 * direction) % 1) * (height + 40) - 20
                painter.save()
                painter.translate(position_x, position_y)
                if self.effect == "hearts":
                    size = 8 + speed * 6
                    heart = QPainterPath(QPointF(0, size * 0.35))
                    heart.cubicTo(-size, -size * 0.4, -size, size * 0.7, 0, size * 1.2)
                    heart.cubicTo(size, size * 0.7, size, -size * 0.4, 0, size * 0.35)
                    painter.drawPath(heart)
                elif self.effect == "rain":
                    painter.drawRoundedRect(QRectF(0, 0, 2, 12 + speed * 16), 1, 1)
                else:
                    painter.rotate(elapsed * 60 * speed + phase * 80)
                    painter.drawRect(QRectF(-3, -5, 6, 10))
                painter.restore()
            else:
                radius = ((vertical + elapsed * speed * 0.2) % 1) * scale * 0.6
                angle = phase + (elapsed * 0.3 if self.effect != "sparks" else 0)
                point = QPointF(center.x() + math.cos(angle) * radius,
                                center.y() + math.sin(angle) * radius)
                painter.drawEllipse(point, 2 + speed, 2 + speed)
        painter.end()
