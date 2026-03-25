import threading
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
from PyQt6.QtCore import QThread, pyqtSignal

from database import init_db, ChatHistory, MemoryTraits

SessionLocal = init_db()

CHROMA_LOCK = threading.Lock()

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
        if not self.user_message.startswith("[System:"):
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
                                with CHROMA_LOCK:
                                    chroma_client = chromadb.PersistentClient(path="./pet_knowledge")
                                    collection = chroma_client.get_or_create_collection(name="documents")

                                    # This query blocks but is fast; to be fully async you'd run in executor,
                                    # but chromadb local is generally fast enough.
                                    results = collection.query(
                                        query_embeddings=[user_embedding],
                                        n_results=2
                                    )
                                    del chroma_client

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
    extraction_finished = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(self, file_path: str, config: dict):
        super().__init__()
        self.file_path = file_path
        self.config = config
        self.url = f"{self.config.get('ollama_url').rstrip('/')}/api/embeddings"
        self.embed_model = "nomic-embed-text"

    def run(self):
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
                for i in range(0, len(words), 200):
                    chunks.append(" ".join(words[i:i+200]))

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
                with CHROMA_LOCK:
                    chroma_client = chromadb.PersistentClient(path="./pet_knowledge")
                    collection = chroma_client.get_or_create_collection(name="documents")
                    collection.add(
                        embeddings=embeddings,
                        documents=valid_chunks,
                        metadatas=[{"filename": filename} for _ in valid_chunks],
                        ids=ids
                    )
                    del chroma_client

                self.extraction_finished.emit(f"I have finished reading {filename}!")
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
