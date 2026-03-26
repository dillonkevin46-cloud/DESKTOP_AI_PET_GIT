# Desktop AI Pet 🐾

A frameless, multi-monitor virtual desktop pet built with Python and PyQt6. This pet is a fully autonomous AI agent featuring a classic "Tamagotchi-style" biological state machine, powered entirely by local AI models. It can see your screen, search the web, read your documents, learn your personality, and proactively interact with you—all while keeping your data 100% private.

## ✨ Features

### 🧠 The Brain & Knowledge Base (RAG)
* **Local LLM Integration:** Powered by local models (e.g., Llama 3) via Ollama, ensuring zero API costs and full privacy.
* **Drag-and-Drop Memory (ChromaDB):** Drag PDFs, Word Docs, Text files, or Excel sheets directly onto the pet. It will read, chunk, and embed them into a local vector database to answer your specific questions.
* **True Learning (PostgreSQL):** A background worker continuously extracts and permanently remembers personality traits about you and the pet from your conversations.
* **Web Search & Feedback Loop:** Automatically queries DuckDuckGo for factual questions. If a web search helps you, the pet permanently memorizes the answer into its vector database so it never has to search for it again.

### 👀 Vision & Autonomy
* **Proactive Screen Advice:** Uses `mss` and local LLaVA models to peek at your active monitor every 90 seconds. If you are working, it offers helpful tips. If you are slacking off, it judges you.
* **Biological State Machine:** Gets hungry, bored, and tired over time. Sleeping regenerates energy.
* **Proactive Autonomy:** If the pet gets too bored, it will autonomously interrupt your workflow and pop open a chat window to demand attention.

### 🎮 Visuals & Mechanics
* **Dynamic GIF Animations:** Seamlessly swaps between `idle.gif`, `sleeping.gif`, `hungry.gif`, and `eating.gif` based on its real-time biological stats.
* **Multi-Monitor Roaming:** Autonomously calculates your display bounding box and randomly wanders around your screens.
* **Taskbar Lock:** Option to restrict the pet's wandering exclusively to the top of your bottom taskbar.
* **Interactive Props:** Includes a physical "Food Bowl" (`bowl.png`) you can drag around your screen. When hunger hits 80, the pet autonomously tracks down the bowl and eats.
* **Direct Interactions:** Right-click the pet's body to directly Feed, Pet, Play, or Put to Sleep.

### ⚙️ Customization (Settings Menu)
Easily configurable via a system tray GUI (saved to `settings.json`). Customize:
* Ollama API URLs & Models (Chat, Vision, Embeddings)
* Pet Name & User Name
* Pet Sprite Size (Pixels)
* Taskbar Roaming Lock

---

## 🏗️ Project Structure
To maintain thread safety and prevent database locking, the application is modularized:
* `main.py` - The clean entry point that boots the application.
* `pet_window.py` - The main frameless GUI, roaming logic, and drag-and-drop event handlers.
* `workers.py` - Contains all async `QThread` workers (Brain, Vision, Stats, Memory Extraction, and Knowledge Ingestion) protected by strict threading locks.
* `ui_components.py` - Contains the Chat Widget, Settings Dialog, and Desktop Props (Food Bowl).
* `config.py` - Handles loading and saving the `settings.json` file.
* `database.py` - Manages the PostgreSQL connection for chat history and personality traits.

---

## 🛠️ Requirements & Prerequisites

* **Python:** 3.10+
* **Database:** PostgreSQL (Running locally on port 5432)
* **AI Engine:** [Ollama](https://ollama.com/) (Running locally)
* **Required Models:** You must pull the chat, vision, and embedding models:
  ```bash
  ollama run llama3
  ollama run llava
  ollama pull nomic-embed-text
🚀 Installation & Setup
Clone the repository.

Install the required dependencies:

Bash

pip install PyQt6 aiohttp sqlalchemy psycopg2-binary mss duckduckgo-search chromadb pypdf python-docx pandas openpyxl
Database Setup: Ensure PostgreSQL is running. Create a database named pet_db and ensure your user has permissions to create schemas/tables. (Update credentials in database.py if necessary).

Add Visual Assets: Place your .gif files (idle.gif, sleeping.gif, hungry.gif, eating.gif) and your prop image (bowl.png) in the root directory.

Run the application:

Bash

python main.py
🕹️ How to Use
Train it: Drag and drop a PDF onto the pet. Wait for it to say it finished reading, then ask it a question!

Chatting: Double-click the pet to open the chat window.

Settings: Right-click the green system tray icon to open settings.

Interacting: Right-click the pet itself to manually feed it, put it to sleep, or pet it.


### What's Next?
Whenever you are ready, let me know if you want to tackle creating the final standalone `.exe` file so you don't have to launch this through your terminal anymore!