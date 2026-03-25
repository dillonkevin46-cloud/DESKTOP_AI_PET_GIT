from PyQt6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QTextEdit, QLineEdit,
    QDialog, QFormLayout, QDialogButtonBox, QSpinBox, QCheckBox
)
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QPixmap

from config import load_settings, save_settings
# Note: we need to import AIBrainWorker for ChatWidget.
# We will do an inline import or import at top level if no cycle.
from workers import AIBrainWorker, PetState

class SettingsDialog(QDialog):
    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("AI Pet Settings")
        self.config = config

        self.layout = QFormLayout(self)

        self.ollama_url_input = QLineEdit(self.config.get("ollama_url", ""))
        self.chat_model_input = QLineEdit(self.config.get("chat_model", ""))
        self.vision_model_input = QLineEdit(self.config.get("vision_model", ""))
        self.pet_name_input = QLineEdit(self.config.get("pet_name", ""))
        self.user_name_input = QLineEdit(self.config.get("user_name", ""))

        self.pet_size_input = QSpinBox()
        self.pet_size_input.setRange(32, 256)
        self.pet_size_input.setValue(self.config.get("pet_size", 64))

        self.lock_to_taskbar_input = QCheckBox()
        self.lock_to_taskbar_input.setChecked(self.config.get("lock_to_taskbar", True))

        self.layout.addRow("Ollama API URL:", self.ollama_url_input)
        self.layout.addRow("Chat Model:", self.chat_model_input)
        self.layout.addRow("Vision Model:", self.vision_model_input)
        self.layout.addRow("Pet Name:", self.pet_name_input)
        self.layout.addRow("User Name:", self.user_name_input)
        self.layout.addRow("Pet Size (Pixels):", self.pet_size_input)
        self.layout.addRow("Lock to Taskbar:", self.lock_to_taskbar_input)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.save_and_accept)
        self.button_box.rejected.connect(self.reject)

        self.layout.addWidget(self.button_box)

    def save_and_accept(self):
        self.config["ollama_url"] = self.ollama_url_input.text().strip()
        self.config["chat_model"] = self.chat_model_input.text().strip()
        self.config["vision_model"] = self.vision_model_input.text().strip()
        self.config["pet_name"] = self.pet_name_input.text().strip()
        self.config["user_name"] = self.user_name_input.text().strip()
        self.config["pet_size"] = self.pet_size_input.value()
        self.config["lock_to_taskbar"] = self.lock_to_taskbar_input.isChecked()

        save_settings(self.config)
        self.accept()


class DesktopProp(QWidget):
    """A frameless, draggable desktop prop (e.g., a food bowl)."""
    def __init__(self, image_path: str):
        super().__init__()

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.drag_position = QPoint()

        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        pixmap = QPixmap(image_path)
        if pixmap.isNull():
            print(f"Warning: Could not load prop image from {image_path}")
            pixmap = QPixmap(64, 64)
            pixmap.fill(Qt.GlobalColor.magenta)
        else:
            pixmap = pixmap.scaled(64, 64, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

        self.image_label.setPixmap(pixmap)
        self.layout.addWidget(self.image_label)
        self.resize(pixmap.size())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()


class ChatWidget(QWidget):
    """Semi-transparent tool window for chatting with the pet."""
    def __init__(self, pet_state: PetState, config: dict, parent=None):
        super().__init__(parent)
        self.pet_state = pet_state
        self.config = config
        self.worker = None

        self.setWindowTitle("Chat with Pet")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self.layout = QVBoxLayout(self)

        self.history_display = QTextEdit()
        self.history_display.setReadOnly(True)
        self.history_display.setStyleSheet("background-color: rgba(0, 0, 0, 150); color: white; border-radius: 5px; padding: 5px;")

        self.input_field = QLineEdit()
        self.input_field.setStyleSheet("background-color: rgba(255, 255, 255, 200); color: black; border-radius: 5px; padding: 5px;")
        self.input_field.setPlaceholderText("Type a message...")
        self.input_field.returnPressed.connect(self._send_message)

        self.layout.addWidget(self.history_display)
        self.layout.addWidget(self.input_field)

        self.resize(300, 400)

    def _send_message(self):
        msg = self.input_field.text().strip()
        if not msg:
            return

        self.input_field.clear()
        user_name = self.config.get("user_name", "You")
        self.history_display.append(f"<b>{user_name}:</b> {msg}")
        self.input_field.setEnabled(False) # Disable input while processing

        # Reset boredom to reward user interaction
        self.pet_state.boredom = 0
        if self.parent():
            self.parent().autonomy_triggered = False

        # Spawn AIBrainWorker
        self.worker = AIBrainWorker(msg, self.pet_state, self.config)
        self.worker.response_ready.connect(self._on_response)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.finished.connect(self._cleanup_worker)
        self.worker.start()

    def _on_response(self, response: str):
        pet_name = self.config.get("pet_name", "Pet")
        self.history_display.append(f"<b>{pet_name}:</b> {response}")

    def _on_error(self, error_msg: str):
        self.history_display.append(f"<i><span style='color:red;'>System:</span> {error_msg}</i>")

    def _cleanup_worker(self):
        self.input_field.setEnabled(True)
        self.input_field.setFocus()
        if self.worker:
            self.worker.deleteLater()
            self.worker = None
