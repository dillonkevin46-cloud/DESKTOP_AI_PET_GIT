import sys
import time
import asyncio
import aiohttp
import mss
import base64
import random
import json
import re
import os
import chromadb
import pypdf
import docx
import pandas as pd
from duckduckgo_search import DDGS
from dataclasses import dataclass
from PyQt6.QtWidgets import (
    QApplication, QWidget, QLabel, QMenu, QSystemTrayIcon, QVBoxLayout,
    QTextEdit, QLineEdit, QDialog, QFormLayout, QDialogButtonBox,
    QSpinBox, QCheckBox
)
from PyQt6.QtCore import Qt, QTimer, QPoint, QRect, QThread, pyqtSignal, QPropertyAnimation, QSize
from PyQt6.QtGui import QPixmap, QAction, QIcon, QGuiApplication, QMovie

from database import init_db, ChatHistory, MemoryTraits

# Initialize the global sessionmaker
SessionLocal = init_db()

# Initialize ChromaDB for RAG
try:
    chroma_client = chromadb.PersistentClient(path="./pet_knowledge")
    knowledge_collection = chroma_client.get_or_create_collection(name="documents")
except Exception as e:
    print(f"Warning: Could not initialize ChromaDB. Local knowledge features will be disabled.\nError: {e}")
    chroma_client = None
    knowledge_collection = None

DEFAULT_CONFIG = {
    "ollama_url": "http://localhost:11434",
    "chat_model": "llama3",
    "vision_model": "llava",
    "pet_name": "Pet",
    "user_name": "User",
    "pet_size": 64,
    "lock_to_taskbar": True
}

def load_settings():
    if not os.path.exists("settings.json"):
        return DEFAULT_CONFIG.copy()
    try:
        with open("settings.json", "r") as f:
            config = json.load(f)
            # Ensure all default keys exist
            for k, v in DEFAULT_CONFIG.items():
                if k not in config:
                    config[k] = v
            return config
    except Exception as e:
        print(f"Error loading settings: {e}")
        return DEFAULT_CONFIG.copy()

def save_settings(config):
    try:
        with open("settings.json", "w") as f:
            json.dump(config, f, indent=4)
    except Exception as e:
        print(f"Error saving settings: {e}")

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

            if ticks_passed >= 30:
                if self.state.current_activity == 'sleeping':
                    # Sleeping regens energy, doesn't increase hunger/boredom
                    self.state.energy = min(100, self.state.energy + 10)
                else:
                    # Drain energy, increase hunger and boredom
                    self.state.energy = max(0, self.state.energy - 2)
                    self.state.hunger = min(100, self.state.hunger + 3)
                    self.state.boredom = min(100, self.state.boredom + 3)

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

    def __init__(self, user_message: str, pet_state: PetState, config: dict, history_limit: int = 5):
        super().__init__()
        self.user_message = user_message
        self.pet_state = pet_state
        self.config = config
        self.history_limit = history_limit
        self.url = f"{self.config.get('ollama_url').rstrip('/')}/api/chat"

    def run(self):
        asyncio.run(self.process_message())

    def _needs_web_search(self, msg: str) -> bool:
        if msg.startswith("[System:"):
            return False
        lower_msg = msg.lower()
        keywords = ["what is", "who is", "search for", "weather", "news", "current event", "tell me about"]
        return any(keyword in lower_msg for keyword in keywords)

    async def process_message(self):
        messages = self._build_context()

        # Save user message to DB
        self._save_to_db("user", self.user_message)

        # RAG Knowledge Retrieval
        if knowledge_collection and not self.user_message.startswith("[System:"):
            try:
                # Get embedding for user message
                embed_url = f"{self.config.get('ollama_url').rstrip('/')}/api/embeddings"
                embed_payload = {"model": "nomic-embed-text", "prompt": self.user_message}

                async with aiohttp.ClientSession() as session:
                    async with session.post(embed_url, json=embed_payload, timeout=10) as response:
                        if response.status == 200:
                            data = await response.json()
                            user_embedding = data.get("embedding")

                            if user_embedding:
                                # This query blocks but is fast; to be fully async you'd run in executor,
                                # but chromadb local is generally fast enough.
                                results = knowledge_collection.query(
                                    query_embeddings=[user_embedding],
                                    n_results=2
                                )

                                docs = results.get("documents", [])
                                if docs and docs[0]:
                                    rag_context = "Retrieved Local Knowledge:\n"
                                    for doc in docs[0]:
                                        rag_context += f"- {doc}\n"
                                    messages.append({"role": "system", "content": rag_context})
            except Exception as e:
                print(f"[DEBUG BRAIN] RAG retrieval failed: {e}")

        # Web Search Integration
        if self._needs_web_search(self.user_message):
            try:
                results = DDGS().text(self.user_message, max_results=3)
                if results:
                    search_context = "Web Search Results:\n"
                    for r in results:
                        search_context += f"- {r.get('body', '')}\n"
                    messages.append({"role": "system", "content": search_context})
            except Exception as e:
                print(f"[DEBUG BRAIN] DuckDuckGo search failed: {e}")

        # Append the new user message at the very end
        messages.append({"role": "user", "content": self.user_message})

        payload = {
            "model": self.config.get("chat_model"),
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
        pet_name = self.config.get("pet_name", "Pet")
        user_name = self.config.get("user_name", "User")

        # Base system prompt dynamically injected with current stats
        system_content = (
            f"You are a virtual desktop pet named {pet_name}. You are talking to your owner, {user_name}. "
            f"Your current stats are: Energy {self.pet_state.energy}/100, Hunger {self.pet_state.hunger}/100, "
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

class KnowledgeIngestionWorker(QThread):
    """Background thread that parses and ingests local documents into ChromaDB for RAG."""
    ingestion_finished = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, file_path: str, config: dict):
        super().__init__()
        self.file_path = file_path
        self.config = config
        self.url = f"{self.config.get('ollama_url').rstrip('/')}/api/embeddings"
        self.embed_model = "nomic-embed-text"

    def run(self):
        if not knowledge_collection:
            self.error_occurred.emit("Knowledge collection not initialized.")
            return
        asyncio.run(self.process_file())

    async def process_file(self):
        try:
            filename = os.path.basename(self.file_path)
            ext = os.path.splitext(filename)[1].lower()
            text = ""

            if ext == '.txt':
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    text = f.read()
            elif ext == '.pdf':
                reader = pypdf.PdfReader(self.file_path)
                for page in reader.pages:
                    extracted = page.extract_text()
                    if extracted:
                        text += extracted + "\n"
            elif ext == '.docx':
                doc = docx.Document(self.file_path)
                text = "\n".join([para.text for para in doc.paragraphs])
            elif ext == '.xlsx':
                df = pd.read_excel(self.file_path)
                text = df.to_string(index=False)
            else:
                self.error_occurred.emit(f"Unsupported file type: {ext}")
                return

            if not text.strip():
                self.error_occurred.emit(f"No readable text found in {filename}.")
                return

            # Chunk text roughly by paragraphs or a fixed word count.
            # Here we chunk by double newlines or arbitrarily if too long.
            raw_chunks = [c.strip() for c in text.split('\n\n') if c.strip()]

            chunks = []
            for rc in raw_chunks:
                words = rc.split()
                for i in range(0, len(words), 500):
                    chunks.append(" ".join(words[i:i+500]))

            embeddings = []
            valid_chunks = []
            ids = []

            async with aiohttp.ClientSession() as session:
                for idx, chunk in enumerate(chunks):
                    payload = {
                        "model": self.embed_model,
                        "prompt": chunk
                    }
                    async with session.post(self.url, json=payload, timeout=60) as response:
                        if response.status == 200:
                            data = await response.json()
                            embedding = data.get("embedding")
                            if embedding:
                                embeddings.append(embedding)
                                valid_chunks.append(chunk)
                                ids.append(f"{filename}_{idx}")
                        else:
                            print(f"[DEBUG RAG] Failed to embed chunk {idx} of {filename}: HTTP {response.status}")

            if valid_chunks:
                knowledge_collection.add(
                    embeddings=embeddings,
                    documents=valid_chunks,
                    metadatas=[{"filename": filename} for _ in valid_chunks],
                    ids=ids
                )
                self.ingestion_finished.emit(f"I have finished reading {filename}!")
            else:
                self.error_occurred.emit(f"Failed to generate any embeddings for {filename}.")

        except Exception as e:
            self.error_occurred.emit(f"Error processing {os.path.basename(self.file_path)}: {e}")

class MemoryExtractionWorker(QThread):
    """Background thread that extracts new memory traits from recent chat history."""
    extraction_finished = pyqtSignal(str)

    def __init__(self, db_sessionmaker, config: dict):
        super().__init__()
        self.db_sessionmaker = db_sessionmaker
        self.config = config
        self.url = f"{self.config.get('ollama_url').rstrip('/')}/api/chat"

        pet_name = self.config.get("pet_name", "pet")
        user_name = self.config.get("user_name", "user")

        self.prompt = (
            f"You are a memory extraction engine. Read the chat transcript between {pet_name} (the pet) and {user_name} (the user) "
            f"and extract 1 to 2 new, permanent facts about the user or the pet's personality. "
            f"Return strictly a JSON list of objects with keys 'entity' (must be '{user_name}' or '{pet_name}') and 'trait'. "
            f"Example: [{{\"entity\": \"{user_name}\", \"trait\": \"Loves Python\"}}]. Do not include markdown formatting or extra text."
        )

    def run(self):
        if not self.db_sessionmaker:
            self.extraction_finished.emit("Extraction aborted: No DB sessionmaker.")
            return
        asyncio.run(self.process_extraction())

    async def process_extraction(self):
        try:
            with self.db_sessionmaker() as db:
                history = db.query(ChatHistory).order_by(ChatHistory.timestamp.desc()).limit(10).all()
                if len(history) < 2:
                    self.extraction_finished.emit("Extraction aborted: Not enough chat history.")
                    return

                transcript = "\n".join([f"{msg.role}: {msg.content}" for msg in reversed(history)])
        except Exception as e:
            self.extraction_finished.emit(f"Extraction failed during DB read: {e}")
            return

        payload = {
            "model": self.config.get("chat_model"),
            "messages": [
                {"role": "system", "content": self.prompt},
                {"role": "user", "content": f"Here is the transcript:\n{transcript}"}
            ],
            "stream": False
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(self.url, json=payload, timeout=45) as response:
                    if response.status == 200:
                        data = await response.json()
                        llm_reply = data.get("message", {}).get("content", "").strip()
                        self._parse_and_save(llm_reply)
                    else:
                        self.extraction_finished.emit(f"HTTP {response.status}: Failed to reach Ollama for memory.")
        except asyncio.TimeoutError:
            self.extraction_finished.emit("Memory extraction timed out.")
        except aiohttp.ClientError as e:
            self.extraction_finished.emit(f"Connection error to Ollama for memory: {e}")
        except Exception as e:
            self.extraction_finished.emit(f"Unexpected Memory extraction error: {e}")

    def _parse_and_save(self, reply: str):
        try:
            # Try to find JSON array in case there is markdown or extra text
            match = re.search(r'\[.*\]', reply, re.DOTALL)
            if not match:
                self.extraction_finished.emit("Failed to parse JSON array from LLM reply.")
                return

            json_str = match.group(0)
            traits = json.loads(json_str)

            if not traits:
                self.extraction_finished.emit("No new traits extracted.")
                return

            with self.db_sessionmaker() as db:
                added = 0
                for item in traits:
                    entity = item.get("entity", "").lower()
                    trait = item.get("trait", "").strip()
                    if entity in ("user", "pet") and trait:
                        new_trait = MemoryTraits(entity_type=entity, trait_description=trait)
                        db.add(new_trait)
                        added += 1
                db.commit()
                self.extraction_finished.emit(f"Successfully extracted {added} traits.")
        except json.JSONDecodeError as e:
            self.extraction_finished.emit(f"JSON decode error: {e}")
        except Exception as e:
            self.extraction_finished.emit(f"Failed to save traits to DB: {e}")

class VisionWorker(QThread):
    """Background thread that handles screen capture and LLaVA vision inference."""
    response_ready = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, config: dict):
        super().__init__()
        self.config = config
        self.url = f"{self.config.get('ollama_url').rstrip('/')}/api/generate"

        pet_name = self.config.get("pet_name", "cute desktop pet")
        user_name = self.config.get("user_name", "the user")

        self.prompt = f"Briefly describe what {user_name} is doing on their screen in one short sentence. Act as a {pet_name} observing them."

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
                "model": self.config.get("vision_model"),
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
        self.ingestion_workers = []

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
        for url in event.mimeData().urls():
            file_path = url.toLocalFile()
            if os.path.exists(file_path):
                ext = os.path.splitext(file_path)[1].lower()
                if ext in ['.pdf', '.docx', '.txt', '.xlsx']:
                    self.chat_widget.history_display.append(f"<i><b>System:</b> Pet is reading {os.path.basename(file_path)}...</i>")
                    worker = KnowledgeIngestionWorker(file_path, self.config)
                    worker.ingestion_finished.connect(self._on_ingestion_finished)
                    worker.error_occurred.connect(self._on_ingestion_error)
                    worker.finished.connect(lambda w=worker: self._cleanup_ingestion_worker(w))
                    self.ingestion_workers.append(worker)
                    worker.start()
                else:
                    self.chat_widget.history_display.append(f"<i><b>System:</b> Cannot read {ext} files. Only .pdf, .docx, .txt, .xlsx supported.</i>")

    def _on_ingestion_finished(self, msg: str):
        pet_name = self.config.get("pet_name", "Pet")
        self.chat_widget.history_display.append(f"<b>{pet_name}:</b> {msg}")
        self.chat_widget.show()

    def _on_ingestion_error(self, msg: str):
        self.chat_widget.history_display.append(f"<i><span style='color:red;'>System:</span> {msg}</i>")

    def _cleanup_ingestion_worker(self, worker):
        if worker in self.ingestion_workers:
            self.ingestion_workers.remove(worker)
        worker.deleteLater()

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
