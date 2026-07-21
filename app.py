"""
MirAI School of Technology — AI Builder Track
Capstone Mini-Project: The Multi-Modal Visual Novel

A stateful "Choose Your Own Adventure" engine that orchestrates:
  - Google Gemini API / Pollinations AI for structured (JSON) narrative generation
  - Pollinations for scene illustration
  - gTTS for spoken narration
  - Streamlit for dynamic, AI-driven UI
"""

import io
import json
import os
import re
import tempfile
import time

import requests
import streamlit as st
from openai import OpenAI
from gtts import gTTS



# Page & global configuration

st.set_page_config(
    page_title="AI Visual Novel Engine",
    layout="wide",
    initial_sidebar_state="expanded",
)

GENRES = [
    "High Fantasy", "Cyberpunk Noir", "Cosmic Horror",
    "Post-Apocalyptic Survival", "Space Opera", "Steampunk Mystery",
]

ART_STYLES = [
    "Studio Ghibli Watercolor", "Cinematic Digital Painting",
    "Dark Gothic Illustration", "Retro Anime Cel-Shading",
    "Photorealistic Concept Art", "Vaporwave Neon",
]

POLLINATIONS_URL = "https://image.pollinations.ai/prompt/{prompt}"
POLLINATIONS_TIMEOUT = 25  # seconds

SYSTEM_PROMPT_TEMPLATE = """You are the narrative engine for an interactive visual novel.

Genre: {genre}
Art Style: {art_style}

RULES:
1. You must respond to EVERY message with a single valid JSON object and NOTHING else.
   Do not wrap it in markdown code fences. Do not add commentary before or after it.
2. The JSON object must have exactly these three keys:
   - "story_text": a vivid, immersive narrative paragraph (3-6 sentences) continuing the story.
   - "image_prompt": a heavily detailed, comma-separated visual prompt describing the current
     scene, written for an AI image generator, explicitly incorporating the "{art_style}" style.
   - "options": a JSON array of 2 to 3 short, distinct strings describing what the protagonist
     could do next.
3. Keep continuity with everything that has happened so far in this conversation.
4. Never break character, never mention that you are an AI, and never output anything other
   than the raw JSON object.

Begin the story now, in the "{genre}" genre.
"""


# Phase 1 — Cached AI client

@st.cache_resource(show_spinner=False)
def get_ai_client(api_key: str, provider: str):
    """Configure and cache the AI client for Gemini or Free Pollinations."""
    if provider == "Pollinations Free AI (Zero Key Required)":
        return OpenAI(
            api_key="pk-free",
            base_url="https://text.pollinations.ai/openai",
        )
    return OpenAI(
        api_key=api_key,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    )


import base64

SESSIONS_FILE = os.path.join(os.path.dirname(__file__), ".saved_sessions.json")


def save_sessions_to_disk(sessions_dict: dict):
    """Serialize saved sessions to disk with base64 encoded images."""
    try:
        serializable = {}
        for s_id, sess in sessions_dict.items():
            sess_copy = dict(sess)
            serialized_history = []
            for turn in sess.get("history", []):
                turn_copy = dict(turn)
                if turn_copy.get("image_bytes"):
                    turn_copy["image_bytes"] = base64.b64encode(turn_copy["image_bytes"]).decode("ascii")
                serialized_history.append(turn_copy)
            sess_copy["history"] = serialized_history
            serializable[s_id] = sess_copy

        with open(SESSIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2)
    except Exception as err:
        print(f"[DISK PERSIST ERROR] {err}")


def load_saved_sessions_from_disk() -> dict:
    """Deserialize saved sessions from disk."""
    if not os.path.exists(SESSIONS_FILE):
        return {}
    try:
        with open(SESSIONS_FILE, "r", encoding="utf-8") as f:
            raw = json.load(f)
        sessions_dict = {}
        for s_id, sess in raw.items():
            sess_copy = dict(sess)
            deserialized_history = []
            for turn in sess.get("history", []):
                turn_copy = dict(turn)
                if turn_copy.get("image_bytes"):
                    try:
                        turn_copy["image_bytes"] = base64.b64decode(turn_copy["image_bytes"])
                    except Exception:
                        turn_copy["image_bytes"] = None
                deserialized_history.append(turn_copy)
            sess_copy["history"] = deserialized_history
            sessions_dict[s_id] = sess_copy
        return sessions_dict
    except Exception as err:
        print(f"[DISK LOAD ERROR] {err}")
        return {}


def init_session_state():
    disk_sessions = load_saved_sessions_from_disk()
    defaults = {
        "messages": [],            # Message list for API (OpenAI chat format)
        "history": [],             # Turn dicts: story_text, image_bytes, audio_path, options
        "game_started": False,
        "genre": GENRES[0],
        "art_style": ART_STYLES[0],
        "turn_count": 0,
        "pending_action": None,    # user's chosen option
        "provider": "Pollinations Free AI (Zero Key Required)",
        "saved_sessions": disk_sessions,     # Keyed dict of saved session snapshots
        "current_session_id": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def save_current_session():
    """Snapshot current story state into saved_sessions dict and save to disk."""
    if not getattr(st.session_state, "current_session_id", None) or not st.session_state.history:
        return
    st.session_state.saved_sessions[st.session_state.current_session_id] = {
        "session_id": st.session_state.current_session_id,
        "title": f"{st.session_state.genre} ({st.session_state.art_style}) - Turn {st.session_state.turn_count}",
        "messages": list(st.session_state.messages),
        "history": list(st.session_state.history),
        "game_started": st.session_state.game_started,
        "genre": st.session_state.genre,
        "art_style": st.session_state.art_style,
        "turn_count": st.session_state.turn_count,
        "provider": st.session_state.provider,
    }
    save_sessions_to_disk(st.session_state.saved_sessions)


def load_session(sess: dict):
    """Restore state from a saved session snapshot."""
    st.session_state.messages = list(sess["messages"])
    st.session_state.history = list(sess["history"])
    st.session_state.game_started = sess["game_started"]
    st.session_state.genre = sess["genre"]
    st.session_state.art_style = sess["art_style"]
    st.session_state.turn_count = sess["turn_count"]
    st.session_state.provider = sess["provider"]
    st.session_state.current_session_id = sess["session_id"]
    st.session_state.pending_action = None
    st.session_state.last_error = None
    st.rerun()


# Phase 2 — Structured JSON engine

def parse_story_json(raw_text: str) -> dict | None:
    """
    Parse AI response into a dict with story_text / image_prompt / options.
    Defensive against responses that wrap JSON in markdown fences or add stray whitespace.
    """
    if not raw_text:
        return None

    cleaned = raw_text.strip()
    cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
    cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None

    required = {"story_text", "image_prompt", "options"}
    if not required.issubset(data.keys()):
        return None
    if not isinstance(data["options"], list) or not data["options"]:
        return None

    return data


def request_next_turn(client: OpenAI, prompt_or_choice: str, is_initial: bool = False) -> dict | None:
    """
    Send a message to the AI client and return the parsed story dict, or None if failed.
    """
    try:
        st.session_state.last_error = None
        
        if is_initial:
            st.session_state.messages = [
                {"role": "system", "content": prompt_or_choice},
                {"role": "user", "content": "Begin Chapter 1 of the story now."}
            ]
        else:
            st.session_state.messages.append({"role": "user", "content": prompt_or_choice})
        
        provider = st.session_state.get("provider", "Pollinations Free AI (Zero Key Required)")
        if provider == "Pollinations Free AI (Zero Key Required)":
            models_to_try = ["openai", "qwen", "mistral"]
        else: # Google Gemini API
            selected = st.session_state.get("selected_model", "gemini-2.5-flash")
            models_to_try = [selected, "gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash-exp"]

        response = None
        primary_err = None

        for model in models_to_try:
            # Try with json_object format first
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=st.session_state.messages,
                    response_format={"type": "json_object"},
                )
                break
            except Exception as e:
                if primary_err is None:
                    primary_err = e
            
            # Fallback trying without response_format constraint
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=st.session_state.messages,
                )
                break
            except Exception as e:
                if primary_err is None:
                    primary_err = e
                continue

        if response is None:
            raise primary_err or Exception("Failed to receive response from AI model.")

        assistant_reply = response.choices[0].message.content
        parsed = parse_story_json(assistant_reply)
        if parsed is not None:
            st.session_state.messages.append({"role": "assistant", "content": assistant_reply})
        else:
            if not is_initial and st.session_state.messages and st.session_state.messages[-1]["role"] == "user":
                st.session_state.messages.pop()
            raise Exception("Failed to parse valid JSON story object from model output.")

        return parsed
    except Exception as exc:  # noqa: BLE001
        err_msg = str(exc)
        print(f"[API ERROR] {err_msg}")
        st.session_state.last_error = err_msg
        st.toast(f"The storyteller stumbled: {err_msg}")
        return None


# Phase 4 — Multi-media generation (image + TTS), wrapped for graceful failure

def generate_scene_image(image_prompt: str) -> bytes | None:
    """Fetch a generated illustration from Pollinations with multi-stage fallback to ensure success."""
    art_style = getattr(st.session_state, "art_style", "Digital Art")
    genre = getattr(st.session_state, "genre", "Fantasy")

    # Clean prompt and sanitize characters
    clean_prompt = re.sub(r"[^\w\s,.-]", "", image_prompt).strip()
    truncated_prompt = clean_prompt[:180]

    prompts_to_try = [
        truncated_prompt,
        f"{art_style}, {genre} scene, detailed visual novel concept art",
        f"artistic visual novel scene in {art_style} style",
    ]

    for p in prompts_to_try:
        try:
            encoded = requests.utils.quote(p)
            url = f"https://image.pollinations.ai/prompt/{encoded}?nologo=true&width=768&height=768"
            resp = requests.get(url, timeout=POLLINATIONS_TIMEOUT)
            if resp.status_code == 200 and len(resp.content) > 1000:
                return resp.content
            print(f"[IMAGE WARN] Pollinations returned HTTP {resp.status_code} for prompt: {p[:30]}...")
        except Exception as err:
            print(f"[IMAGE WARN] Retry attempt failed: {err}")

    st.toast("Image server is busy, skipping visual...")
    return None


def generate_narration_audio(story_text: str) -> str | None:
    """Convert story_text to speech via gTTS. Returns a temp file path, or None on failure."""
    try:
        tts = gTTS(text=story_text, lang="en", slow=False)
        tmp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp3")
        tts.save(tmp_file.name)
        return tmp_file.name
    except Exception as err:  # noqa: BLE001
        print(f"[AUDIO ERROR] {err}")
        st.toast("Narration engine is busy, continuing without audio...")
        return None


def build_turn(story_dict: dict) -> dict:
    """Assemble a complete turn (text + image + audio) from a parsed story dict."""
    with st.spinner("Painting the scene..."):
        image_bytes = generate_scene_image(story_dict["image_prompt"])
    with st.spinner("Recording the narration..."):
        audio_path = generate_narration_audio(story_dict["story_text"])

    return {
        "story_text": story_dict["story_text"],
        "image_bytes": image_bytes,
        "audio_path": audio_path,
        "options": story_dict["options"],
    }


# Phase 1 — Sidebar / Director's Cut

def get_api_key() -> str:
    """Retrieve API key from env, secrets, or manual user input."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
    if not key:
        try:
            key = st.secrets.get("GEMINI_API_KEY") or st.secrets.get("GOOGLE_API_KEY", "")
        except Exception:
            key = ""
    return key.strip()


def render_sidebar(default_key: str) -> tuple[str | None, str]:
    with st.sidebar:
        st.markdown("## Story Settings")

        api_key = st.text_input(
            "Gemini API Key",
            value=default_key,
            type="password",
            help="Enter your Gemini API key from Google AI Studio",
        ).strip()
        
        api_key_present = bool(api_key)
        st.session_state.provider = "Google Gemini API"
        st.session_state.selected_model = st.selectbox(
            "Gemini Model",
            ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-2.0-flash-exp"],
            index=0,
            disabled=st.session_state.game_started,
        )

        st.session_state.genre = st.selectbox(
            "Story Genre", GENRES,
            index=GENRES.index(st.session_state.genre),
            disabled=st.session_state.game_started,
        )
        st.session_state.art_style = st.selectbox(
            "Art Style", ART_STYLES,
            index=ART_STYLES.index(st.session_state.art_style),
            disabled=st.session_state.game_started,
        )

        st.divider()

        if st.session_state.game_started:
            if st.button("+ New Story Session", use_container_width=True):
                st.session_state.game_started = False
                st.session_state.messages = []
                st.session_state.history = []
                st.session_state.turn_count = 0
                st.session_state.current_session_id = None
                st.session_state.pending_action = None
                st.session_state.last_error = None
                st.rerun()

        if getattr(st.session_state, "saved_sessions", None):
            with st.expander("Saved Story Sessions", expanded=True):
                for s_id, sess in list(st.session_state.saved_sessions.items()):
                    st.markdown(f"**{sess['title']}**")
                    if s_id == st.session_state.get("current_session_id"):
                        st.caption("Active Session")
                    else:
                        if st.button("Load & Continue", key=f"resume_{s_id}", use_container_width=True):
                            load_session(sess)
                    st.divider()

        if not st.session_state.game_started:
            if not api_key_present:
                st.warning("Add your Gemini API key to begin.")
            start_clicked = st.button(
                "Begin Your Adventure",
                type="primary",
                use_container_width=True,
                disabled=not api_key_present,
            )
        else:
            start_clicked = False
            with st.expander("Active Story Settings"):
                st.write(f"**Genre**: {st.session_state.genre}")
                st.write(f"**Style**: {st.session_state.art_style}")

            st.caption(f"Turn {st.session_state.turn_count}")
            if st.button("Restart Story", use_container_width=True):
                for key in ("messages", "history", "game_started",
                            "turn_count", "pending_action", "last_error", "current_session_id"):
                    st.session_state.pop(key, None)
                st.cache_resource.clear()
                st.rerun()

        st.divider()
        with st.expander("About this engine"):
            st.markdown(
                "Built for the MirAI School of Technology AI Builder Track. "
                "Combines a stateful LLM narrative session, structured JSON output, "
                "Pollinations image generation, and gTTS narration."
            )

        return ("start" if start_clicked else None), api_key


# Phase 3 — Rendering the story so far + dynamic option buttons

def render_history():
    if not st.session_state.history:
        st.info("Story initialized, but no chapters have been generated yet.")
        return

    for i, turn in enumerate(st.session_state.history):
        is_latest = i == len(st.session_state.history) - 1
        with st.container(border=True):
            col_img, col_content = st.columns([1, 1.3], gap="large")

            with col_img:
                if turn["image_bytes"]:
                    st.image(turn["image_bytes"], use_container_width=True)
                else:
                    st.info("No visual available for this scene.")

            with col_content:
                st.markdown(f"### Chapter {i + 1}")
                st.write(turn["story_text"])
                if turn["audio_path"] and os.path.exists(turn["audio_path"]):
                    st.audio(turn["audio_path"], format="audio/mp3")

                if is_latest:
                    st.markdown("---")
                    st.markdown("**What do you do?**")
                    for idx, option_text in enumerate(turn["options"]):
                        if st.button(
                            option_text,
                            key=f"option_{st.session_state.turn_count}_{idx}",
                            use_container_width=True,
                        ):
                            st.session_state.pending_action = option_text
                            st.rerun()


# Main application flow

def main():
    st.title("AI Visual Novel Engine")
    st.caption("A stateful, multi-modal Choose-Your-Own-Adventure powered by Gemini API + Pollinations + gTTS")

    default_api_key = get_api_key()
    init_session_state()

    action, api_key = render_sidebar(default_api_key)

    # Surface API error banner prominently at top of page if present
    if getattr(st.session_state, "last_error", None):
        st.error(f"API Error: {st.session_state.last_error}")

    if action == "start" and not st.session_state.game_started:
        st.session_state.current_session_id = f"session_{int(time.time())}"
        client = get_ai_client(api_key, st.session_state.provider)
        system_prompt = SYSTEM_PROMPT_TEMPLATE.format(
            genre=st.session_state.genre,
            art_style=st.session_state.art_style,
        )

        story_dict = None
        with st.spinner("The storyteller is thinking..."):
            story_dict = request_next_turn(client, system_prompt, is_initial=True)

        if story_dict is None:
            st.toast("Could not start the story. Please check your API key and try again.")
        else:
            st.session_state.history.append(build_turn(story_dict))
            st.session_state.turn_count += 1
            st.session_state.game_started = True
            save_current_session()
        st.rerun()

    if st.session_state.pending_action:
        user_choice = st.session_state.pending_action
        st.session_state.pending_action = None
        client = get_ai_client(api_key, st.session_state.provider)

        with st.spinner(f"You chose: '{user_choice}' -- continuing the story..."):
            story_dict = request_next_turn(client, user_choice, is_initial=False)

        if story_dict is None:
            st.toast("The story couldn't continue this turn. Try clicking again.")
        else:
            st.session_state.history.append(build_turn(story_dict))
            st.session_state.turn_count += 1
            save_current_session()
        st.rerun()

    if not st.session_state.game_started:
        st.info(
            "Choose a genre and art style in the sidebar, then click "
            "Begin Your Adventure to generate your first scene."
        )
    else:
        render_history()


if __name__ == "__main__":
    main()