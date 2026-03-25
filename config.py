import os
import json

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
