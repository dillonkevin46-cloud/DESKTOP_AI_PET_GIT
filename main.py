import sys
import logging
import faulthandler
import threading

# Enable fatal crash dumping to a file
crash_file = open("crash_dump.log", "w")
faulthandler.enable(file=crash_file)

# Configure standard logging
logging.basicConfig(
    filename='pet_debug.log',
    level=logging.DEBUG,
    format='%(asctime)s - [%(threadName)s] - %(levelname)s - %(message)s'
)

# Catch unhandled Python exceptions
def handle_exception(exc_type, exc_value, exc_traceback):
    if issubclass(exc_type, KeyboardInterrupt):
        sys.__excepthook__(exc_type, exc_value, exc_traceback)
        return
    logging.error("Uncaught exception", exc_info=(exc_type, exc_value, exc_traceback))

sys.excepthook = handle_exception

def handle_thread_exception(args):
    logging.error(f"Uncaught thread exception in {args.thread.name}", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

threading.excepthook = handle_thread_exception

logging.info("=== APPLICATION STARTED ===")

from PyQt6.QtWidgets import QApplication
from ui_components import DesktopProp
from pet_window import PetWindow

def main():
    app = QApplication(sys.argv)

    # Ensure application doesn't close when the main window is hidden
    # (Though we keep ours visible, it's good practice for tray apps)
    app.setQuitOnLastWindowClosed(False)

    sprite_paths = {
        "idle": "idle.gif",
        "sleeping": "sleeping.gif",
        "hungry": "hungry.gif",
        "eating": "eating.gif"
    }

    food_bowl = DesktopProp("bowl.png")

    pet = PetWindow(sprite_paths, food_bowl=food_bowl)
    pet.show()
    food_bowl.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
