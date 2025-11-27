import os
import sys
import json
import random
import asyncio
import platform
import subprocess
from threading import Thread
from vosk import Model, KaldiRecognizer
import pyaudio
from playsound import playsound
from gtts import gTTS
from openai import OpenAI
from rapidfuzz import process, fuzz

# ------------------- Настройки -------------------
client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")

SYSTEM_PROMPT = (
    "You are Jarvis, Tony Stark's sophisticated AI assistant. "
    "Keep responses short, varied, and natural. 1-2 sentences max."
)

# ------------------- Разговорные словари -------------------
conversation_db = {
    "greetings": {
        "triggers": [
            "hello",
            "hi",
            "hey",
            "greetings",
            "здравствуй",
            "привет",
            "добрый день",
        ],
        "responses": [
            "Hello, sir. How may I assist you today?",
            "Greetings. What can I do for you?",
            "Good to see you, sir.",
            "Hello. Systems are fully operational.",
            "Greetings, sir. Ready for your command.",
        ],
    },
    "how_are_you": {
        "triggers": [
            "how are you",
            "как дела",
            "как ты",
            "как поживаешь",
            "как настроение",
        ],
        "responses": [
            "I'm functioning optimally, sir.",
            "All systems are running smoothly.",
            "Feeling exceptional, sir.",
            "No malfunctions detected, doing well.",
            "At peak performance, ready for tasks.",
        ],
    },
    "who_are_you": {
        "triggers": ["who are you", "ты кто", "кто ты", "что ты", "скажи кто ты"],
        "responses": [
            "I'm Jarvis, your personal AI assistant.",
            "Jarvis, sir. Designed to assist you at all times.",
            "A sophisticated AI system developed to help you.",
            "Your trusted assistant and system manager.",
            "Jarvis at your service, sir.",
        ],
    },
    "thanks": {
        "triggers": ["thanks", "thank you", "спасибо", "благодарю"],
        "responses": [
            "You're welcome, sir.",
            "My pleasure.",
            "Anytime, sir.",
            "Glad I could assist.",
            "Always here to help.",
        ],
    },
    "goodbye": {
        "triggers": ["goodbye", "bye", "до свидания", "пока", "увидимся"],
        "responses": [
            "Goodbye, sir. It's been a pleasure.",
            "See you soon, sir.",
            "Farewell. Until next time.",
            "Take care, sir.",
            "Until we meet again.",
        ],
    },
}

COMMANDS = {
    "open_chrome": [
        "chrome",
        "google",
        "browser",
        "open chrome",
        "открой хром",
        "открой гугл",
        "браузер",
    ],
    "open_youtube": ["youtube", "open youtube", "ютуб", "открой ютуб"],
    "open_music": [
        "itunes",
        "open music",
        "music",
        "apple music",
        "открой музыку",
        "музыка",
    ],
}


# ------------------- Вспомогательные функции -------------------
def speak(text, blocking=False):
    """Озвучка. blocking=True — ждать до конца воспроизведения."""

    def _play_audio():
        try:
            tts = gTTS(text=text, lang="en", slow=False)
            filename = "temp.mp3"
            tts.save(filename)
            playsound(filename)
            os.remove(filename)
        except Exception as e:
            print(f"[TTS Error]: {e}")

    if blocking:
        _play_audio()
    else:
        Thread(target=_play_audio, daemon=True).start()


def format_response(text):
    if random.random() < 0.33 and "sir" not in text.lower():
        return text.rstrip(".!?") + ", sir."
    return text


def match_trigger(text, db):
    """Ищет лучшее совпадение с rapidfuzz."""
    all_triggers = []
    mapping = {}
    for key, entry in db.items():
        for trig in entry["triggers"]:
            all_triggers.append(trig)
            mapping[trig] = key

    match, score, _ = process.extractOne(
        text, all_triggers, scorer=fuzz.token_sort_ratio
    )
    if match and score >= 70:
        category = mapping[match]
        return category, score
    return None, 0


def run_command(cmd):
    try:
        system = platform.system().lower()
        if cmd == "open_chrome":
            url = "https://www.google.com"
        elif cmd == "open_youtube":
            url = "https://www.youtube.com"
        elif cmd == "open_music":
            if system == "windows":
                os.startfile("itunes.exe")
                return "Opening iTunes"
            elif system == "darwin":
                subprocess.Popen(["open", "-a", "iTunes"])
                return "Opening iTunes"
            else:
                subprocess.Popen(["xdg-open", "https://music.apple.com"])
                return "Opening music"
        if system == "windows":
            os.startfile(url)
        elif system == "darwin":
            subprocess.Popen(["open", url])
        else:
            subprocess.Popen(["xdg-open", url])
        return f"Opening {url}"
    except Exception as e:
        print(f"[Command Error]: {e}")
        return "Could not execute command"


async def ask_llm(query):
    try:
        completion = client.chat.completions.create(
            model="local-model",
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": query},
            ],
            temperature=0.7,
            max_tokens=60,
            timeout=10,
        )
        return completion.choices[0].message.content.strip()
    except Exception as e:
        print(f"[LLM Error]: {e}")
        return "I seem to have lost connection to the network."


# ------------------- Основной цикл -------------------
async def main():
    if not os.path.exists("model"):
        print("❌ Vosk model folder 'model' not found.")
        sys.exit(1)
    model = Model("model")
    rec = KaldiRecognizer(model, 16000)

    p = pyaudio.PyAudio()
    try:
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            frames_per_buffer=8000,
        )
        stream.start_stream()
    except Exception as e:
        print(f"❌ PyAudio Error: {e}")
        sys.exit(1)

    speak(random.choice(["Systems online, sir.", "Jarvis online."]))
    print("Listening...")

    while True:
        data = stream.read(4000, exception_on_overflow=False)
        if rec.AcceptWaveform(data):
            result = json.loads(rec.Result())
            text = result.get("text", "").lower().strip()
            if not text:
                continue

            print(f">> You: {text}")

            # Выключение
            if any(
                w in text
                for w in ["shut down", "exit", "quit", "выключись", "заверши работу"]
            ):
                resp = "Shutting down. Goodbye!"
                print(f"<< Jarvis: {resp}")
                speak(resp, blocking=True)
                print("-" * 30)
                break

            # Быстрые разговорные ответы
            category, score = match_trigger(text, conversation_db)
            if category:
                resp = format_response(
                    random.choice(conversation_db[category]["responses"])
                )
                print(f"<< Jarvis: {resp}")
                speak(resp)
                print("-" * 30)
                print("Listening...")
                continue

            # Команды
            cmd_cat, cmd_score = match_trigger(
                text, {k: {"triggers": v} for k, v in COMMANDS.items()}
            )
            if cmd_cat:
                resp = format_response(run_command(cmd_cat))
                print(f"<< Jarvis: {resp}")
                speak(resp)
                print("-" * 30)
                print("Listening...")
                continue

            # Если ничего не подошло — LLM
            print("...Consulting LLM...")
            resp = await ask_llm(text)
            resp = format_response(resp)
            print(f"<< Jarvis: {resp}")
            speak(resp)
            print("-" * 30)
            print("Listening...")


if __name__ == "__main__":
    asyncio.run(main())
