import sys
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
