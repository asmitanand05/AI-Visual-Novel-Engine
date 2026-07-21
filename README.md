# 📖 AI Visual Novel Engine

**MirAI School of Technology — AI Builder Track | Capstone Mini-Project**

An immersive, multi-modal "Choose Your Own Adventure" engine powered by Generative AI. This application orchestrates a stateful narrative where every decision you make generates a new chapter complete with AI-written text, custom illustrations, and spoken narration.

## ✨ Features

*   **Multi-Modal Storytelling:** Experience the story through three distinct mediums simultaneously:
    *   **Text:** Rich, dynamic narrative generation (via Google Gemini API or Pollinations Free AI).
    *   **Visuals:** Real-time scene illustrations based on AI-generated prompts (via Pollinations AI).
    *   **Audio:** Spoken narration of the story text (via Google Text-to-Speech / gTTS).
*   **Structured AI Brain:** Uses rigorous system prompting and JSON-mode forcing to ensure the AI always returns valid gameplay elements (story text, image prompts, and branching choices).
*   **Customizable World-Building:** Choose from a variety of Genres (e.g., Cyberpunk Noir, Cosmic Horror) and Art Styles (e.g., Studio Ghibli Watercolor, Vaporwave Neon) to set the exact tone of your adventure.
*   **Stateful Session Management:** 
    *   Your story progress is saved automatically.
    *   Previous sessions are serialized to disk (`.saved_sessions.json`) with Base64-encoded images, allowing you to load and resume past adventures.
*   **Graceful Degradation:** Built-in error handling ensures the game continues even if the image or audio servers time out. 

---

## 🛠️ Technology Stack

| Component | Technology / Library | Description |
| :--- | :--- | :--- |
| **Frontend & State** | [Streamlit](https://streamlit.io/) | Drives the dynamic UI and manages the complex turn-by-turn session state. |
| **Narrative Engine** | [Google Gemini API](https://aistudio.google.com/) | Utilized via the `openai` Python SDK (using Gemini's OpenAI-compatible endpoint) to generate structured JSON story nodes. |
| **Fallback AI** | [Pollinations Text](https://pollinations.ai/) | Zero-key required fallback for LLM text generation. |
| **Image Generation** | [Pollinations Image](https://pollinations.ai/) | Fast, on-the-fly image generation via URL encoding. |
| **Audio Narration** | [gTTS](https://gtts.readthedocs.io/en/latest/) | Converts the generated text chapters into temporary MP3 audio files. |

---

## 🚀 Getting Started

### Prerequisites

Ensure you have Python 3.9+ installed on your machine. 

🧠 How It Works (Under the Hood)
The engine is divided into four main operational phases:

Phase 1: Configuration & Session State
The app initializes Streamlit's st.session_state to track message history, turn counts, and user choices. It also deserializes any previously saved games from .saved_sessions.json, decoding the Base64 images back into byte streams so players can seamlessly resume older stories.

Phase 2: The Structured JSON Engine
When the user starts a game or makes a choice, a prompt is sent to the LLM.
The system prompt strictly enforces a JSON-only output containing:

story_text: The narrative paragraph.

image_prompt: A detailed prompt for the image generator, automatically appending the user's chosen art style.

options: An array of 2-3 choices for the player's next move.

Note: The code includes a robust regex-based JSON parser to strip out accidental markdown blocks or conversational filler the LLM might hallucinate.

Phase 3: Multi-Media Generation
Once the JSON is parsed, the engine processes the media concurrently (simulated via sequential spinners):

Images: The image_prompt is URL-encoded and sent to Pollinations AI. If the request times out, it gracefully falls back to shorter, safer prompts.

Audio: The story_text is passed to gTTS, which synthesizes human speech and saves it to an OS-level temporary file for Streamlit to play.

Phase 4: Dynamic UI Rendering
Streamlit builds the UI dynamically based on the length of the history array. Older turns are rendered for context, while the latest turn features the interactive choice buttons. Clicking a choice updates the pending_action state and triggers a rerun to start Phase 2 again.

⚠️ Limitations & Troubleshooting
Image Generation Timeouts: Pollinations AI can sometimes experience heavy load. The app has a built-in timeout of 25 seconds and fallback prompts. If an image fails, the game will notify you and continue with text only.

JSON Parsing Errors: If the AI model completely ignores the structural prompt (rare with gemini-1.5-flash or gemini-2.5-flash), the application catches the error, displays a toast notification, and allows you to retry the turn.

🎓 Acknowledgments
Developed as the Capstone Mini-Project for the MirAI School of Technology — AI Builder Track.

### 1. Clone & Setup
Clone your repository and navigate into the project directory:
```bash
git clone [https://github.com/asmitanand05/ai-visual-novel-engine.git](https://github.com/asmitanand05/ai-visual-novel-engine.git)
cd ai-visual-novel-engine
