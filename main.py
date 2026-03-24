import sys
import time
import asyncio
import aiohttp
import mss
import base64
import random
from dataclasses import dataclass
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QMenu, QSystemTrayIcon, QVBoxLayout,
    QTextEdit, QLineEdit
)
from PyQt6.QtCore import Qt, QTimer, QPoint, QRect, QThread, pyqtSignal, QPropertyAnimation
from PyQt6.QtGui import QPixmap, QAction, QIcon, QGuiApplication

from database import init_db, ChatHistory, MemoryTraits

# Initialize the global sessionmaker
SessionLocal = init_db()

@dataclass
class PetState:
    hunger: int = 0
    energy: int = 100
    boredom: int = 0
    affection: int = 50
    current_activity: str = 'idle'

class StatDecayWorker(QThread):
    """Background thread that manages the biological clock of the pet."""
    state_updated = pyqtSignal(object)

    def __init__(self, state: PetState):
        super().__init__()
        self.state = state
        self.running = True

    def run(self):
        ticks_passed = 0
        while self.running:
            # Sleep in smaller chunks to allow faster thread termination
            time.sleep(0.5)
            ticks_passed += 0.5

            if ticks_passed >= 5:
                # Drain energy, increase hunger and boredom
                self.state.energy = max(0, self.state.energy - 5)
                self.state.hunger = min(100, self.state.hunger + 5)
                self.state.boredom = min(100, self.state.boredom + 5)

                # Emit the updated state back to the main GUI thread
                self.state_updated.emit(self.state)
                ticks_passed = 0

    def stop(self):
        self.running = False
        self.wait()

class AIBrainWorker(QThread):
    """Background thread that handles LLM inferences using local Ollama."""
    response_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, user_message: str, pet_state: PetState, history_limit: int = 5):
        super().__init__()
        self.user_message = user_message
        self.pet_state = pet_state
        self.history_limit = history_limit
        self.url = "http://localhost:11434/api/chat"

    def run(self):
        asyncio.run(self.process_message())

    async def process_message(self):
        messages = self._build_context()

        # Append the new user message
        messages.append({"role": "user", "content": self.user_message})

        # Save user message to DB
        self._save_to_db("user", self.user_message)

        payload = {
            "model": "llama3", # Change to whatever model you use
            "messages": messages,
            "stream": False
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.url, json=payload, timeout=30) as response:
                    if response.status == 200:
                        data = await response.json()
                        llm_reply = data.get("message", {}).get("content", "")
                        self._save_to_db("assistant", llm_reply)
                        self.response_ready.emit(llm_reply)
                    else:
                        error_msg = f"HTTP {response.status}: Failed to reach Ollama."
                        self.error_occurred.emit(error_msg)
        except aiohttp.ClientError as e:
            self.error_occurred.emit(f"Connection error to Ollama: {e}")
        except asyncio.TimeoutError:
            self.error_occurred.emit("Ollama API timed out.")
        except Exception as e:
            self.error_occurred.emit(f"Unexpected Brain error: {e}")

    def _build_context(self):
        # Base system prompt dynamically injected with current stats
        system_content = (
            f"You are a virtual desktop pet. Your current stats are: "
            f"Energy {self.pet_state.energy}/100, Hunger {self.pet_state.hunger}/100, "
            f"Boredom {self.pet_state.boredom}/100, Affection {self.pet_state.affection}/100. "
            f"Act accordingly. Keep responses short and full of personality."
        )

        messages = [{"role": "system", "content": system_content}]

        # Inject memory and history if DB is active
        if SessionLocal:
            with SessionLocal() as db:
                # Fetch 3-5 traits
                traits = db.query(MemoryTraits).limit(5).all()
                if traits:
                    traits_text = "\n".join(f"- [{t.entity_type}]: {t.trait_description}" for t in traits)
                    messages.append({"role": "system", "content": f"Relevant traits:\n{traits_text}"})

                # Fetch last N messages
                history = db.query(ChatHistory).order_by(ChatHistory.timestamp.desc()).limit(self.history_limit).all()
                # Reverse to chronological order
                for entry in reversed(history):
                    messages.append({"role": entry.role, "content": entry.content})

        return messages

    def _save_to_db(self, role: str, content: str):
        if SessionLocal:
            try:
                with SessionLocal() as db:
                    new_chat = ChatHistory(role=role, content=content)
                    db.add(new_chat)
                    db.commit()
            except Exception as e:
                print(f"Failed to save {role} message to DB: {e}")

class VisionWorker(QThread):
    """Background thread that handles screen capture and LLaVA vision inference."""
    response_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.url = "http://localhost:11434/api/generate"
        self.prompt = "Briefly describe what the user is doing on their screen in one short sentence. Act as a cute desktop pet observing them."

    def run(self):
        asyncio.run(self.process_vision())

    async def process_vision(self):
        try:
            with mss.mss() as sct:
                # Capture the primary monitor
                monitor = sct.monitors[1]
                sct_img = sct.grab(monitor)

                # Convert to PNG bytes
                img_bytes = mss.tools.to_png(sct_img.rgb, sct_img.size)

                # Encode to base64
                base64_img = base64.b64encode(img_bytes).decode('utf-8')

            payload = {
                "model": "llava",
                "prompt": self.prompt,
                "images": [base64_img],
                "stream": False
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(self.url, json=payload, timeout=60) as response:
                    if response.status == 200:
                        data = await response.json()
                        llm_reply = data.get("response", "").strip()
                        self.response_ready.emit(llm_reply)
                    else:
                        error_msg = f"HTTP {response.status}: Failed to reach Ollama."
                        self.error_occurred.emit(error_msg)

        except mss.exception.ScreenShotError as e:
            self.error_occurred.emit(f"Failed to capture screen: {e}")
        except aiohttp.ClientError as e:
            self.error_occurred.emit(f"Connection error to Ollama: {e}")
        except asyncio.TimeoutError:
            self.error_occurred.emit("Ollama API timed out.")
        except Exception as e:
            self.error_occurred.emit(f"Unexpected Vision error: {e}")


class ChatWidget(QWidget):
    """Semi-transparent tool window for chatting with the pet."""
    def __init__(self, pet_state: PetState, parent=None):
        super().__init__(parent)
        self.pet_state = pet_state
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
        self.history_display.append(f"<b>You:</b> {msg}")
        self.input_field.setEnabled(False) # Disable input while processing

        # Spawn AIBrainWorker
        self.worker = AIBrainWorker(msg, self.pet_state)
        self.worker.response_ready.connect(self._on_response)
        self.worker.error_occurred.connect(self._on_error)
        self.worker.finished.connect(self.worker.deleteLater)
        self.worker.start()

    def _on_response(self, response: str):
        self.history_display.append(f"<b>Pet:</b> {response}")
        self._cleanup_worker()

    def _on_error(self, error_msg: str):
        self.history_display.append(f"<i><span style='color:red;'>System:</span> {error_msg}</i>")
        self._cleanup_worker()

    def _cleanup_worker(self):
        self.input_field.setEnabled(True)
        self.input_field.setFocus()


class SpriteAnimator:
    """Handles loading and animating a sprite sheet."""
    def __init__(self, sprite_sheet_path: str, frame_width: int, frame_height: int, frame_count: int, update_interval: int = 100):
        self.sprite_sheet_path = sprite_sheet_path
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.frame_count = frame_count
        self.current_frame = 0

        self.frames = []
        self._load_frames()

        self.timer = QTimer()
        self.timer.setInterval(update_interval)

    def _load_frames(self):
        sprite_sheet = QPixmap(self.sprite_sheet_path)
        if sprite_sheet.isNull():
            # If the image failed to load, we can create dummy empty pixmaps or log a warning
            print(f"Warning: Could not load sprite sheet from {self.sprite_sheet_path}")
            # Create a placeholder visible frame if file not found
            placeholder = QPixmap(self.frame_width, self.frame_height)
            placeholder.fill(Qt.GlobalColor.blue)
            self.frames = [placeholder] * self.frame_count
            return

        for i in range(self.frame_count):
            # Assuming a horizontal sprite sheet for simplicity
            rect = QRect(i * self.frame_width, 0, self.frame_width, self.frame_height)
            frame = sprite_sheet.copy(rect)
            self.frames.append(frame)

    def start(self, callback):
        """Starts the animation, calling `callback` with the current frame's pixmap."""
        self._callback = callback
        self.timer.timeout.connect(self._update_frame)
        self.timer.start()

    def stop(self):
        self.timer.stop()

    def _update_frame(self):
        if not self.frames:
            return

        frame = self.frames[self.current_frame]
        if hasattr(self, '_callback'):
            self._callback(frame)

        self.current_frame = (self.current_frame + 1) % self.frame_count

class PetWindow(QWidget):
    """The main transparent, frameless window for the virtual pet."""
    def __init__(self, sprite_path: str):
        super().__init__()

        self.drag_position = QPoint()
        self.total_screen_geometry = QRect()

        self.state = PetState()

        self.chat_widget = ChatWidget(self.state)
        self.vision_worker = None

        self._setup_window()
        self._setup_multi_monitor()
        self._setup_ui()
        self._setup_tray()
        self._setup_animation(sprite_path)
        self._setup_worker()
        self._setup_roaming()

    def _setup_roaming(self):
        self.roam_animation = QPropertyAnimation(self, b"pos")

        self.roam_timer = QTimer(self)
        self.roam_timer.timeout.connect(self.wander)
        # Trigger wander every 15 to 30 seconds
        self.roam_timer.start(random.randint(15000, 30000))

    def wander(self):
        # Calculate random position within total_screen_geometry
        min_x = self.total_screen_geometry.left()
        max_x = self.total_screen_geometry.right() - self.width()

        min_y = self.total_screen_geometry.top()
        max_y = self.total_screen_geometry.bottom() - self.height()

        if max_x > min_x and max_y > min_y:
            target_x = random.randint(min_x, max_x)
            target_y = random.randint(min_y, max_y)
            target_pos = QPoint(target_x, target_y)

            self.roam_animation.setDuration(random.randint(3000, 5000))
            self.roam_animation.setEndValue(target_pos)
            self.roam_animation.start()

            # Reset timer for next wander
            self.roam_timer.setInterval(random.randint(15000, 30000))

    def _setup_worker(self):
        self.worker = StatDecayWorker(self.state)
        self.worker.state_updated.connect(self.update_pet_state)
        self.worker.start()

    def update_pet_state(self, state: PetState):
        # Threshold Logic
        if state.energy < 10 and state.current_activity != 'sleeping':
            state.current_activity = 'sleeping'
            print("State change: Energy is low! Switching to sleep sprite.", flush=True)
        elif state.hunger > 80 and state.current_activity != 'hungry':
            state.current_activity = 'hungry'
            print("State change: Very hungry! Switching to hungry sprite.", flush=True)
        else:
            print(f"Tick - Energy: {state.energy}, Hunger: {state.hunger}, Boredom: {state.boredom}, Activity: {state.current_activity}", flush=True)

    def _setup_window(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.Tool  # Hides from taskbar on some systems
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def _setup_multi_monitor(self):
        screens = QGuiApplication.screens()
        total_rect = QRect()
        for screen in screens:
            total_rect = total_rect.united(screen.geometry())

        self.total_screen_geometry = total_rect
        print(f"Total bounding geometry of all monitors: {self.total_screen_geometry}")

    def _setup_ui(self):
        # We need a layout to hold the QLabel
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)

        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.image_label)

    def _setup_tray(self):
        self.tray_icon = QSystemTrayIcon(self)

        # Creating a red placeholder icon for the tray
        placeholder_icon = QPixmap(16, 16)
        placeholder_icon.fill(Qt.GlobalColor.red)
        self.tray_icon.setIcon(QIcon(placeholder_icon))

        self.tray_menu = QMenu(self)

        toggle_chat_action = QAction("Toggle Chat", self)
        toggle_chat_action.triggered.connect(self.toggle_chat)
        self.tray_menu.addAction(toggle_chat_action)

        look_action = QAction("Look at Screen", self)
        look_action.triggered.connect(self.look_at_screen)
        self.tray_menu.addAction(look_action)

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit_app)
        self.tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.show()

    def _setup_animation(self, sprite_path: str):
        # Placeholder dimensions, adjust these for actual sprite sheet
        frame_w = 64
        frame_h = 64
        frame_count = 4

        self.animator = SpriteAnimator(sprite_path, frame_w, frame_h, frame_count)
        self.animator.start(self._on_frame_updated)

    def _on_frame_updated(self, pixmap: QPixmap):
        self.image_label.setPixmap(pixmap)
        self.resize(pixmap.size())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_chat()
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def toggle_chat(self):
        if self.chat_widget.isVisible():
            self.chat_widget.hide()
        else:
            self.chat_widget.show()

    def look_at_screen(self):
        if self.vision_worker and self.vision_worker.isRunning():
            return  # Ignore if already looking

        self.vision_worker = VisionWorker()
        self.vision_worker.response_ready.connect(self._on_vision_response)
        self.vision_worker.error_occurred.connect(self._on_vision_error)
        self.vision_worker.finished.connect(self.vision_worker.deleteLater)
        self.vision_worker.start()

    def _on_vision_response(self, observation: str):
        self.chat_widget.history_display.append(f"<i><b>Pet sees:</b> {observation}</i>")

    def _on_vision_error(self, error_msg: str):
        self.chat_widget.history_display.append(f"<i><span style='color:red;'>System (Vision):</span> {error_msg}</i>")

    def quit_app(self):
        print("Stopping worker thread safely...")
        self.worker.stop()
        QApplication.instance().quit()

def main():
    app = QApplication(sys.argv)

    # Ensure application doesn't close when the main window is hidden
    # (Though we keep ours visible, it's good practice for tray apps)
    app.setQuitOnLastWindowClosed(False)

    # Placeholder sprite path
    SPRITE_SHEET_PATH = "placeholder_sprite.png"

    pet = PetWindow(SPRITE_SHEET_PATH)
    pet.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
