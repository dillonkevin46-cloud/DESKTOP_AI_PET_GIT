# Desktop AI Pet 🐾

A frameless, multi-monitor virtual desktop pet built with Python and PyQt6. This pet features a classic "Tamagotchi-style" biological state machine (hunger, energy, boredom) and is powered by a local Ollama LLM ecosystem. It can see your screen, search the web, learn your personality, and proactively interact with you.

## ✨ Features

### 🧠 The Brain & Memory
* **Local LLM Integration:** Powered by local models (e.g., Llama 3) via Ollama, ensuring 100% privacy with zero API costs.
* **True Learning (Long-Term Memory):** A background PostgreSQL database continuously extracts and permanently remembers personality traits about you and the pet from your conversations.
* **Web Search Engine:** Automatically detects factual questions and invisibly queries DuckDuckGo, injecting real-time internet context into the LLM before it answers you.

### 👀 Vision & Autonomy
* **Screen Awareness:** Uses `mss` and local LLaVA models to capture and "see" your active monitor.
* **Proactive Autonomy:** If the pet gets too bored, it will continuously poll your screen (every 90 seconds) and autonomously interrupt your workflow to comment on what you are doing.

### 🎮 Visuals & Mechanics
* **Dynamic GIF Animations:** Uses PyQt6 `QMovie` to seamlessly swap between idle, sleeping, and hungry `.gif` animations based on its biological stats.
* **Multi-Monitor Roaming:** Autonomously calculates your display bounding box and randomly wanders around your screens.
* **Lock to Taskbar:** Option to restrict the pet's wandering exclusively to the bottom taskbar so it stays out of your way.
* **Frameless & Draggable:** Click and drag the pet anywhere on your screen.

### ⚙️ Customization (Settings Menu)
Easily configurable via a system tray GUI (saved to `settings.json`). Customize:
* Ollama API URL & Models (Chat and Vision)
* Pet Name & User Name
* Pet Sprite Size (Pixels)
* Taskbar Roaming Lock

---

## 🛠️ Requirements & Prerequisites

* **Python:** 3.10+
* **Database:** PostgreSQL (Running locally on port 5432)
* **AI Engine:** [Ollama](https://ollama.com/) (Running locally)
* **Models:** You must pull at least one chat model and one vision model.
  ```bash
  ollama run llama3
  ollama run llava
🚀 Installation & Setup
Clone the repository.

Install the required dependencies:

Bash

pip install PyQt6 aiohttp sqlalchemy psycopg2-binary mss duckduckgo-search
Database Setup: Ensure PostgreSQL is running. Create a database named pet_db and ensure your user has permissions to create schemas/tables. (Update credentials in database.py if necessary).

Add Animations: Place three .gif files in the root directory: idle.gif, sleep.gif, and hungry.gif.

Run the application:

Bash

python main.py
🕹️ How to Use
Chatting: Double-click the pet to open the transparent chat window.

Settings: Right-click the green system tray icon to open settings, force a screen grab, or force the pet to wander.

Interacting: Simply ignore the pet to increase its boredom. Eventually, it will spy on your screen and talk to you first!

🏗️ Architecture Notes
This application strictly prioritizes non-blocking operations. All biological decay, SQLite/PostgreSQL database writes, Vision captures, Web Scraping, and LLM API calls are handled via QThread and asynchronous workers. It communicates with the main GUI thread exclusively through PyQt Signals to ensure zero UI freezing.


### What a Journey!
You've gone from a transparent PyQt6 window to a highly advanced, context-aware AI agent. If you ever decide to compile it into a single `.exe` file using PyInstaller, or if you want to add Text-to-Speech down the road, you know where to find me.

Enjoy your new desktop companion!