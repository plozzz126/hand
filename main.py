import argparse
import sys


def main():
    parser = argparse.ArgumentParser(description="Gesture Lab — жесты, GIF и эффекты")
    parser.add_argument("--demo", action="store_true", help="Запустить без камеры и модели")
    parser.add_argument("--camera", type=int, help="Индекс камеры, обычно 0")
    parser.add_argument("--start-camera", action="store_true", help="Включить камеру сразу после запуска")
    args = parser.parse_args()

    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from gesture_lab.ui import MainWindow

    application = QApplication(sys.argv[:1])
    application.setApplicationName("Gesture Lab")
    window = MainWindow(demo=args.demo, camera_index=args.camera)
    window.show()
    if args.start_camera and not args.demo:
        QTimer.singleShot(0, window.toggle_camera)
    return application.exec()


if __name__ == "__main__":
    sys.exit(main())
