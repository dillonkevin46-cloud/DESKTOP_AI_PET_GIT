Project README.md
Here is a clean, professional README.md that documents your current progress and outlines the roadmap for the upcoming phases.

Markdown

# Desktop AI Pet 🐾

A frameless, multi-monitor virtual desktop pet built with Python and PyQt6. This pet features a classic "Tamagotchi-style" biological state machine (hunger, energy, boredom) and is designed to eventually integrate with a local Ollama LLM for conversational memory and LLaVA for screen-aware vision.

## Current Features (Phases 1 & 2)
* **Frameless & Transparent UI:** The pet lives directly on your desktop without window borders.
* **Always-on-Top:** Persists above other applications without interrupting your workflow.
* **Draggable:** Click and drag the pet to move it anywhere on your screen.
* **System Tray Integration:** Run quietly in the background with a system tray icon for easy exiting.
* **Sprite Animation Engine:** Dynamically loads and loops through sprite sheets.
* **Biological State Machine:** A background `QThread` safely drains energy and increases hunger over time without freezing the UI.
* **Multi-Monitor Awareness:** Automatically calculates the total bounding geometry of all connected displays (preparation for autonomous roaming).

## Requirements
* Python 3.10+
* `PyQt6`

## Installation & Setup

1. Clone the repository.
2. Install the required dependencies:
   ```bash
   pip install PyQt6
Place a sprite sheet named placeholder_sprite.png in the root directory.

Run the application:

Bash

python main.py
## Development Roadmap
* **Phase 1: The Shell (Complete)** - Frameless UI, system tray, and sprite animator.
* **Phase 2: The Engine (Complete)** - Background state machine and UI state triggers.
* **Phase 3: The Brain (Complete)** - Successfully integrated a local PostgreSQL instance via SQLAlchemy for long-term memory and local Ollama (Llama 3) via `aiohttp` for chatting.
* **Phase 4: The Eyes & Legs (Complete)** - Uses `mss` and local LLaVA for screen grabbing and vision, alongside `QPropertyAnimation` for autonomous screen roaming.
* **Phase 5: The Soul (Complete)** - Proactive Autonomy (the pet initiates conversation when boredom is high) and True Learning (a background extraction worker saves facts to `MemoryTraits` in PostgreSQL).
* **Phase 6: Dynamic Sprites (Complete)** - Real-time sprite sheet swapping based on biological state.

## Troubleshooting
* **Crash on Chat**: If the pet crashes when sending a message, ensure the local Ollama service is running.
* **Database Failure**: If the application fails to connect to the database, ensure your Postgres user has the necessary ownership and permissions for the `pet_db` schema.

## Architecture Notes
This application strictly prioritizes non-blocking operations. All biological decay and future LLM API calls are handled via QThread or asynchronous workers, communicating with the main GUI thread exclusively through PyQt Signals.


---

Would you like me to provide the highly-detailed Phase 3 prompt so we can start wiri