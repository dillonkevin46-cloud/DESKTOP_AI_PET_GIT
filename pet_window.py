import os
import random
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QMenu, QSystemTrayIcon, QDialog, QApplication
from PyQt6.QtCore import Qt, QTimer, QPoint, QRect, QPropertyAnimation, QSize
from PyQt6.QtGui import QPixmap, QAction, QIcon, QGuiApplication, QMovie

from config import load_settings
from ui_components import DesktopProp, ChatWidget, SettingsDialog
from workers import PetState, StatDecayWorker, AIBrainWorker, KnowledgeIngestionWorker, MemoryExtractionWorker, VisionWorker, SessionLocal

class PetWindow(QWidget):
    """The main transparent, frameless window for the virtual pet."""
    def __init__(self, sprite_paths: dict[str, str], food_bowl: DesktopProp = None):
        super().__init__()

        self.config = load_settings()
        self.sprite_paths = sprite_paths
        self.food_bowl = food_bowl
        self.drag_position = QPoint()
        self.total_screen_geometry = QRect()

        self.state = PetState()

        self.chat_widget = ChatWidget(self.state, self.config, parent=self)
        self.vision_worker = None

        self.autonomy_triggered = False
        self.vision_mode = "manual"
        self.autonomous_worker = None
        self.walking_to_bowl = False
        self.ingestion_worker = None

        self.setAcceptDrops(True)

        self._setup_window()
        self._setup_multi_monitor()
        self._setup_ui()
        self._setup_tray()
        self._setup_animation()
        self._setup_worker()
        self._setup_roaming()

    def _setup_roaming(self):
        self.roam_animation = QPropertyAnimation(self, b"pos")
        self.roam_animation.finished.connect(self._on_roam_finished)

        self.roam_timer = QTimer(self)
        self.roam_timer.timeout.connect(self.wander)
        # Trigger wander every 15 to 30 seconds
        self.roam_timer.start(random.randint(15000, 30000))

    def _on_roam_finished(self):
        if self.walking_to_bowl:
            self.state.hunger = 0
            self.state.current_activity = 'eating'
            self.change_animation_state('eating')
            self.roam_timer.stop()
            self.walking_to_bowl = False
            QTimer.singleShot(5000, self.finish_eating)

    def finish_eating(self):
        self.state.current_activity = 'idle'
        self.change_animation_state('idle')
        self.roam_timer.start(random.randint(15000, 30000))

    def wander(self):
        if self.state.hunger >= 80 and self.food_bowl:
            print("[DEBUG WANDER] Pet is hungry! Walking to the food bowl.")
            target_pos = self.food_bowl.geometry().topLeft()
            self.walking_to_bowl = True
        else:
            self.walking_to_bowl = False
            screen = QGuiApplication.screenAt(self.geometry().center())
            if not screen:
                screen = QGuiApplication.primaryScreen()

            screen_geo = screen.availableGeometry()

            # Calculate random position within the current screen's available geometry
            min_x = screen_geo.left()
            max_x = screen_geo.right() - self.width()

            min_y = screen_geo.top()
            max_y = screen_geo.bottom() - self.height()

            print(f"[DEBUG WANDER] Pet dimensions: {self.width()}x{self.height()}")
            print(f"[DEBUG WANDER] Screen: {screen.name()} | Available Geo: {screen_geo}")
            print(f"[DEBUG WANDER] X Range: {min_x} to {max_x} | Y Range: {min_y} to {max_y}")

            if max_x <= min_x or max_y <= min_y:
                print("[WARNING] Invalid screen geometry boundaries. Forcing target_pos to (100, 100).")
                target_pos = QPoint(100, 100)
            else:
                target_x = random.randint(min_x, max_x)
                if self.config.get("lock_to_taskbar", True):
                    target_y = max_y
                else:
                    target_y = random.randint(min_y, max_y)
                target_pos = QPoint(target_x, target_y)

            print(f"[DEBUG WANDER] Calculated target_pos: ({target_pos.x()}, {target_pos.y()})")

        self.roam_animation.setDuration(random.randint(3000, 5000))
        self.roam_animation.setEndValue(target_pos)
        self.roam_animation.start()

        # Reset timer for next wander
        self.roam_timer.setInterval(random.randint(15000, 30000))

    def _setup_worker(self):
        self.worker = StatDecayWorker(self.state)
        self.worker.state_updated.connect(self.update_pet_state)
        self.worker.start()

        self.memory_worker = None
        self.memory_timer = QTimer(self)
        self.memory_timer.timeout.connect(self.extract_memories)
        self.memory_timer.start(300000)  # 5 minutes

        self.continuous_vision_timer = QTimer(self)
        self.continuous_vision_timer.timeout.connect(self.trigger_continuous_vision)
        self.continuous_vision_timer.start(90000)  # 90 seconds

    def extract_memories(self):
        if self.memory_worker and self.memory_worker.isRunning():
            print("[DEBUG MEMORY] Memory extraction already running. Skipping this cycle.")
            return

        print("[DEBUG MEMORY] Starting memory extraction cycle...")
        self.memory_worker = MemoryExtractionWorker(SessionLocal, self.config)
        self.memory_worker.extraction_finished.connect(lambda msg: print(f"[DEBUG MEMORY] {msg}"))
        self.memory_worker.finished.connect(self._cleanup_memory_worker)
        self.memory_worker.start()

    def trigger_continuous_vision(self):
        if (self.vision_worker and self.vision_worker.isRunning()) or \
           (self.autonomous_worker and self.autonomous_worker.isRunning()):
            return

        self.vision_mode = "autonomous"
        self.look_at_screen()

    def _cleanup_memory_worker(self):
        if self.memory_worker:
            self.memory_worker.deleteLater()
            self.memory_worker = None

    def update_pet_state(self, state: PetState):
        # Threshold Logic
        if state.energy < 10 and state.current_activity != 'sleeping':
            state.current_activity = 'sleeping'
            self.change_animation_state('sleeping')
            print("State change: Energy is low! Switching to sleep sprite.", flush=True)
        elif state.hunger > 80 and state.current_activity != 'hungry':
            state.current_activity = 'hungry'
            self.change_animation_state('hungry')
            print("State change: Very hungry! Switching to hungry sprite.", flush=True)
        elif state.energy >= 10 and state.hunger <= 80 and state.current_activity != 'idle':
            state.current_activity = 'idle'
            self.change_animation_state('idle')
            print("State change: Stats are normal. Switching to idle sprite.", flush=True)
        else:
            print(f"Tick - Energy: {state.energy}, Hunger: {state.hunger}, Boredom: {state.boredom}, Activity: {state.current_activity}", flush=True)

        if state.boredom >= 80 and not self.autonomy_triggered:
            print("State change: High boredom! Initiating autonomous interaction.", flush=True)
            self.autonomy_triggered = True
            self.vision_mode = "autonomous"
            self.look_at_screen()

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

        # Creating a green placeholder icon for the tray
        placeholder_icon = QPixmap(16, 16)
        placeholder_icon.fill(Qt.GlobalColor.green)
        self.tray_icon.setIcon(QIcon(placeholder_icon))

        self.tray_menu = QMenu(self)

        version_action = QAction("--- Version 4 (Vision & Roaming) ---", self)
        version_action.setEnabled(False)
        self.tray_menu.addAction(version_action)

        toggle_chat_action = QAction("Toggle Chat", self)
        toggle_chat_action.triggered.connect(self.toggle_chat)
        self.tray_menu.addAction(toggle_chat_action)

        look_action = QAction("Look at Screen", self)
        look_action.triggered.connect(self.look_at_screen)
        self.tray_menu.addAction(look_action)

        force_wander_action = QAction("Force Wander", self)
        force_wander_action.triggered.connect(self.wander)
        self.tray_menu.addAction(force_wander_action)

        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.open_settings)
        self.tray_menu.addAction(settings_action)

        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(self.quit_app)
        self.tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(self.tray_menu)
        self.tray_icon.show()

    def _setup_animation(self):
        self.movie = QMovie()
        pet_size = self.config.get("pet_size", 64)
        self.movie.setScaledSize(QSize(pet_size, pet_size))
        self.image_label.setMovie(self.movie)

        # Connect frame changed to resize window to gif size
        self.movie.frameChanged.connect(self._on_frame_changed)

        self.change_animation_state("idle")

    def _on_frame_changed(self):
        if self.movie.currentPixmap():
            self.resize(self.movie.currentPixmap().size())

    def change_animation_state(self, state_name: str):
        path = self.sprite_paths.get(state_name)
        pet_size = self.config.get("pet_size", 64)
        self.movie.setScaledSize(QSize(pet_size, pet_size))

        if not path or not os.path.exists(path):
            print(f"Warning: Missing animation file for state '{state_name}' at path '{path}'.")
            # Try falling back to idle
            path = self.sprite_paths.get("idle")

            if not path or not os.path.exists(path):
                print(f"Warning: Idle fallback missing. Using blue placeholder.")
                self.movie.stop()
                placeholder = QPixmap(pet_size, pet_size)
                placeholder.fill(Qt.GlobalColor.blue)
                self.image_label.setPixmap(placeholder)
                self.resize(placeholder.size())
                return

        self.movie.stop()
        self.movie.setFileName(path)
        self.movie.start()

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

    def contextMenuEvent(self, event):
        menu = QMenu(self)

        pet_action = QAction("Pet him", self)
        pet_action.triggered.connect(self._action_pet)
        menu.addAction(pet_action)

        feed_action = QAction("Feed him", self)
        feed_action.triggered.connect(self._action_feed)
        menu.addAction(feed_action)

        play_action = QAction("Play with him", self)
        play_action.triggered.connect(self._action_play)
        menu.addAction(play_action)

        sleep_action = QAction("Put to sleep", self)
        sleep_action.triggered.connect(self._action_sleep)
        menu.addAction(sleep_action)

        menu.exec(event.globalPos())

    def _action_pet(self):
        self.state.affection = min(100, self.state.affection + 20)
        print(f"[INTERACTION] You petted the pet. Affection is now {self.state.affection}.")
        self.update_pet_state(self.state)

    def _action_feed(self):
        self.state.hunger = 0
        self.state.current_activity = 'eating'
        self.change_animation_state('eating')
        self.roam_timer.stop()
        QTimer.singleShot(5000, self.finish_eating)
        print("[INTERACTION] You fed the pet. Hunger is now 0.")

    def _action_play(self):
        self.state.boredom = 0
        print("[INTERACTION] You played with the pet. Boredom is now 0.")
        self.update_pet_state(self.state)

    def _action_sleep(self):
        self.state.current_activity = 'sleeping'
        print("[INTERACTION] You put the pet to sleep.")
        self.update_pet_state(self.state)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event):
        if self.ingestion_worker and self.ingestion_worker.isRunning():
            self.chat_widget.history_display.append("<i><b>System:</b> I am already reading a document!</i>")
            event.ignore()
            return

        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.exists(file_path):
                ext = os.path.splitext(file_path)[1].lower()
                if ext in ['.pdf', '.docx', '.txt', '.xlsx']:
                    self.chat_widget.history_display.append(f"<i><b>System:</b> Pet is reading {os.path.basename(file_path)}...</i>")
                    self.ingestion_worker = KnowledgeIngestionWorker(file_path, self.config)
                    self.ingestion_worker.extraction_finished.connect(self._on_extraction_finished)
                    self.ingestion_worker.error_occurred.connect(self._on_extraction_error)
                    self.ingestion_worker.finished.connect(self._cleanup_ingestion_worker)
                    self.ingestion_worker.start()
                    break # Process only the first valid file for simplicity
                else:
                    self.chat_widget.history_display.append(f"<i><b>System:</b> Cannot read {ext} files. Only .pdf, .docx, .txt, .xlsx supported.</i>")

    def _on_extraction_finished(self, msg: str):
        pet_name = self.config.get("pet_name", "Pet")
        self.chat_widget.history_display.append(f"<b>{pet_name}:</b> {msg}")
        self.chat_widget.show()

    def _on_extraction_error(self, msg: str):
        self.chat_widget.history_display.append(f"<i><span style='color:red;'>System:</span> {msg}</i>")

    def _cleanup_ingestion_worker(self):
        if self.ingestion_worker:
            self.ingestion_worker.deleteLater()
            self.ingestion_worker = None

    def toggle_chat(self):
        if self.chat_widget.isVisible():
            self.chat_widget.hide()
        else:
            self.chat_widget.show()

    def open_settings(self):
        dialog = SettingsDialog(self.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.config = load_settings()
            # Update ChatWidget config reference
            self.chat_widget.config = self.config

    def look_at_screen(self):
        if self.vision_worker and self.vision_worker.isRunning():
            return  # Ignore if already looking

        self.vision_worker = VisionWorker(self.config)
        self.vision_worker.response_ready.connect(self._on_vision_response)
        self.vision_worker.error_occurred.connect(self._on_vision_error)
        self.vision_worker.finished.connect(self._cleanup_vision_worker)
        self.vision_worker.start()

    def _cleanup_vision_worker(self):
        if self.vision_worker:
            self.vision_worker.deleteLater()
            self.vision_worker = None

    def _on_vision_response(self, observation: str):
        pet_name = self.config.get("pet_name", "Pet")
        if self.vision_mode == "manual":
            self.chat_widget.history_display.append(f"<i><b>{pet_name} sees:</b> {observation}</i>")
        elif self.vision_mode == "autonomous":
            prompt = f"[System: You are extremely bored. You look at the user's screen and see: {observation}. Say something short, sassy, or needy to interrupt them and get their attention.]"
            self.autonomous_worker = AIBrainWorker(prompt, self.state, self.config)
            self.autonomous_worker.response_ready.connect(self._on_autonomous_response)
            self.autonomous_worker.error_occurred.connect(self._on_vision_error)
            self.autonomous_worker.finished.connect(self._cleanup_autonomous_brain)
            self.autonomous_worker.start()

    def _on_autonomous_response(self, response: str):
        pet_name = self.config.get("pet_name", "Pet")
        self.chat_widget.history_display.append(f"<b>{pet_name}:</b> {response}")
        self.chat_widget.show()
        self.vision_mode = "manual"

    def _cleanup_autonomous_brain(self):
        if self.autonomous_worker:
            self.autonomous_worker.deleteLater()
            self.autonomous_worker = None

    def _on_vision_error(self, error_msg: str):
        self.chat_widget.history_display.append(f"<i><span style='color:red;'>System (Vision):</span> {error_msg}</i>")
        if self.vision_mode == "autonomous":
            self.vision_mode = "manual"

    def quit_app(self):
        print("Stopping worker thread safely...")
        self.worker.stop()
        QApplication.instance().quit()
