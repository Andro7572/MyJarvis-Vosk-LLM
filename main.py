import os
import sys
import random
import subprocess
import platform
import json
import time
from vosk import (
    Model,
    KaldiRecognizer,
)  # Imports Vosk library for offline speech recognition
import pyaudio  # Imports PyAudio for microphone access
from gtts import gTTS  # Imports gTTS for Text-to-Speech
from playsound import playsound
from datetime import datetime
from rapidfuzz import fuzz  # Imports for fuzzy string matching (command comparison)
from openai import OpenAI
import requests

# Initialize OpenAI client to connect to a local LLM server (e.g., LM Studio)
client = OpenAI(base_url="http://localhost:1234/v1", api_key="lm-studio")

conversation_history = []
MAX_HISTORY = 3  # Maximum turns to keep for LLM context
last_operation = "None recorded."

# Keywords that force a direct call to the LLM, even if short
FORCED_LLM_WORDS = [
    "yes",
    "no",
    "okay",
    "ok",
    "yep",
    "nope",
    "yeah",
    "nah",
    "why",
    "who",
    "what",
    "where",
    "when",
    "how",
    "answer",
]


def speak(text):
    """Speaks the provided text using gTTS and playsound."""
    print(f"<< Jarvis: {text}")
    filename = "temp.mp3"
    try:
        # Cleanup " sir" variants for better TTS
        tts_text = (
            text.replace(" sir.", " sir")
            .replace(" sir!", " sir")
            .replace(" sir?", " sir")
        )

        tts = gTTS(text=tts_text, lang="en", slow=False)
        tts.save(filename)
        playsound(filename)
    except Exception as e:
        print(f"TTS Error (gTTS/playsound): {e}. Skipping speech.")
    finally:
        time.sleep(0.1)
        if os.path.exists(filename):
            try:
                os.remove(filename)  # Clean up temp file
            except PermissionError:
                pass


def open_app(command_list, name):
    """Universal function to open applications based on OS."""
    try:
        if platform.system() == "Windows":
            subprocess.Popen(["start"] + command_list, shell=True)
        elif platform.system() == "Darwin":  # macOS logic
            app_name = (
                name
                if name not in ["YouTube"]
                else ("Google Chrome" if "chrome" in name.lower() else "iTunes")
            )
            if app_name in ["Google Chrome", "iTunes"]:
                subprocess.Popen(["open", "-a", app_name])
            elif command_list and command_list[0].startswith("http"):
                subprocess.Popen(["open", command_list[0]])
            else:
                subprocess.Popen(command_list)
        else:
            subprocess.Popen(command_list)  # Generic Linux/other
        return f"Opening {name}"
    except Exception:
        return f"Could not open {name}"


def open_chrome():
    return open_app(["chrome"], "Google Chrome")


def open_youtube():
    return open_app(["https://www.youtube.com"], "YouTube")


def open_itunes():
    return open_app(["itunes"], "iTunes")


def ask_llm(user_text):
    """Sends a query to the local LLM with conversation history."""
    global last_operation

    history_messages = []
    # Prepare history for LLM context
    for turn in conversation_history:
        user_message = turn["user"]
        jarvis_message = (
            turn["jarvis"]
            .replace(" sir.", "")
            .replace(" sir!", "")
            .replace(" sir?", "")
        )

        history_messages.append({"role": "user", "content": user_message})
        history_messages.append({"role": "assistant", "content": jarvis_message})

    # System prompt defines Jarvis's persona and response rules
    system_instruction = (
        "You are Jarvis, Tony Stark's witty and superior AI assistant. "
        "Your responses must be in English. Answer in full sentences, but be **extremely concise** and **avoid any excessive politeness, introductions, or verbose filler phrases**. "
        "Answer all questions using your internal knowledge. Do not mention external search or real-time data needs. "
        "Maintain factual accuracy. Respond directly to the user's input with a touch of Jarvis's dry humor. "
        f"The last internal operation was: {last_operation}. "
    )

    messages = [{"role": "system", "content": system_instruction}]
    messages.extend(history_messages)
    messages.append({"role": "user", "content": user_text})

    try:
        # API call to the local LLM endpoint
        completion = client.chat.completions.create(
            model="local-model",
            messages=messages,
            temperature=0.2,
            timeout=15,
        )
        final_response = completion.choices[0].message.content.strip()

        last_operation = f"LLM Query: {user_text}, LLM Response: {final_response}"
        return final_response

    except requests.exceptions.Timeout:
        return "Sir, the network operation timed out while waiting for a response from the LLM."
    except Exception as e:
        return f"Sir, I seem to have lost connection to the mainframe. Error: {e}"


# --- Vosk and PyAudio Setup ---

if not os.path.exists("model"):
    print("Error: Vosk model 'model' folder not found. Please download and unpack it.")
    sys.exit(1)

model = Model("model")  # Load the speech recognition model
rec = KaldiRecognizer(model, 16000)

p = pyaudio.PyAudio()
try:
    # Open microphone stream
    stream = p.open(
        format=pyaudio.paInt16,
        channels=1,
        rate=16000,
        input=True,
        frames_per_buffer=8000,
    )
    stream.start_stream()
except Exception as e:
    print(
        f"FATAL ERROR: Could not open PyAudio stream. Check your microphone drivers or if another application is using the microphone. Error: {e}"
    )
    sys.exit(1)

# --- Hardcoded Commands Dictionary ---

commands = {
    "time": {
        "keywords": [
            "time",
            "what time",
            "what time is it",
            "current time",
            "tell me the time",
            "whats the time",
            "time right now",
            "what is the time now",
            "do you know the time",
            "what's the current hour",
            "check the clock",
            "the time please",
            "what hour is it",
            "exact time now",
            "time check",
        ],
        "responses": [
            lambda: f"The time is {datetime.now().strftime('%I:%M %p')}",
            lambda: f"Right now it's {datetime.now().strftime('%I:%M %p')}",
            lambda: f"It's currently {datetime.now().strftime('%I:%M %p')}",
            lambda: f"The current time is {datetime.now().strftime('%I:%M %p')}",
        ],
    },
    "date": {
        "keywords": [
            "date",
            "what's the date",
            "today's date",
            "whats the date today",
            "tell me the date",
            "current date",
            "what day is it",
            "what day is today",
            "what is today's date",
            "can you tell me the date",
            "date check",
            "what day of the week",
            "the date today",
        ],
        "responses": [
            lambda: f"Today is {datetime.now().strftime('%B %d, %Y')}",
            lambda: f"The date today is {datetime.now().strftime('%B %d, %Y')}",
            lambda: f"It's {datetime.now().strftime('%B %d, %Y')} today",
            lambda: f"Today's date is {datetime.now().strftime('%A, %B %d, %Y')}",
        ],
    },
    "how_are_you": {
        "keywords": [
            "how are you",
            "how's it going",
            "how do you feel",
            "whats up",
            "what's up",
            "how you doing",
            "how are things",
            "how ya doing",
            "you good",
            "how's your day",
            "what are you up to",
            "how do you function",
            "tell me how you feel",
        ],
        "responses": [
            "I'm just a bunch of code, but I'm running perfectly!",
            "Feeling operational! Thanks for asking.",
            "All systems go. How can I assist you today?",
            "Fantastic! Ready to help you!",
            "I'm doing great, thanks for asking!",
        ],
    },
    "joke": {
        "keywords": [
            "tell me a joke",
            "joke",
            "make me laugh",
            "say something funny",
            "I need a joke",
            "got any jokes",
            "tell a joke please",
            "amuse me",
            "crack a joke",
            "say a funny thing",
            "tell me a funny story",
            "I'm bored tell a joke",
            "make me chuckle",
        ],
        "responses": [
            "Why did the computer go to the doctor? Because it caught a virus!",
            "Why do programmers prefer dark mode? Because light attracts bugs!",
            "I would tell you a UDP joke, but you might not get it.",
            "Why do Java developers wear glasses? Because they can't C sharp!",
            "How many programmers does it take to change a light bulb? None, that's a hardware problem!",
        ],
    },
    "thanks": {
        "keywords": [
            "thank you",
            "thanks",
            "thx",
            "thank you so much",
            "thanks a lot",
            "appreciate it",
            "much appreciated",
            "cheers",
            "you're the best",
            "thanks jarvis",
            "good job",
            "nice one",
            "i thank you",
            "i am grateful",
            "many thanks",
            "apology",
            "i'm sorry",
            "i am sorry",
            "sorry",
        ],
        "responses": [
            "You're welcome!",
            "No problem, happy to help!",
            "Anytime, my friend.",
            "My pleasure!",
            "Glad I could assist!",
            "Understood, apology accepted.",
        ],
    },
    "hello": {
        "keywords": [
            "hello",
            "hi",
            "hey",
            "hi there",
            "greetings",
            "hello jarvis",
            "hey there",
            "good day",
            "howdy",
            "what's up",
            "hey assistant",
            "good evening",
            "good afternoon",
            "morning",
            "afternoon",
            "good morning",
            "top of the morning",
            "good morning to you",
        ],
        "responses": [
            "Hello! How can I help you today?",
            "Hi there! Great to see you!",
            "Hey! What's on your mind?",
            "Greetings! Ready to assist!",
            "Hi! What can I do for you?",
            "Good morning! Ready for a productive day?",
        ],
    },
    "chrome": {
        "keywords": [
            "open chrome",
            "launch chrome",
            "start chrome",
            "chrome",
            "google",
            "open browser",
            "start the browser",
            "launch google chrome",
            "open google",
            "can you open chrome",
        ],
        "responses": [open_chrome],  # Calls the function to open the app
    },
    "youtube": {
        "keywords": [
            "open youtube",
            "youtube",
            "launch youtube",
            "start youtube",
            "open videos",
            "youtube videos",
            "access youtube",
            "go to youtube",
            "launch the youtube website",
        ],
        "responses": [open_youtube],  # Calls the function to open the URL
    },
    "itunes": {
        "keywords": [
            "open itunes",
            "itunes",
            "launch itunes",
            "start itunes",
            "music",
            "play music",
            "open my music app",
            "launch apple music",
            "start apple music",
            "can you open itunes",
        ],
        "responses": [open_itunes],  # Calls the function to open the app
    },
    "shut down": {
        "keywords": [
            "shut down",
            "stop",
            "turn off",
            "exit",
            "quit",
            "terminate",
            "end program",
            "close jarvis",
            "stop listening",
            "exit application",
            "i'm done",
            "goodbye and shut down",
        ],
        "responses": ["Shutting down. Goodbye!"],
    },
}


def format_for_tts(response, add_sir):
    """Adds ' sir.' to the end of the response if the flag is set, cleaning up existing punctuation."""
    if not add_sir:
        return response

    stripped_resp = response.strip()
    punctuation = [".", "!", "?", ","]

    while stripped_resp and stripped_resp[-1] in punctuation:
        stripped_resp = stripped_resp[:-1]  # Remove trailing punctuation

    return stripped_resp + " sir."


greetings = [
    "Systems online, sir.",
    "Mini Jarvis online and operational.",
    "Greetings. How may I be of assistance?",
    "Online. Proceed with your query.",
]

speak(random.choice(greetings))
print("Listening...")

# --- Main Recognition Loop ---
while True:
    data = stream.read(4000, exception_on_overflow=False)

    if rec.AcceptWaveform(data):
        result = rec.Result()
        try:
            text = json.loads(result).get("text", "").lower()
        except json.JSONDecodeError:
            continue

        if not text:
            continue

        print(f">> You: {text}")

        found_command = False
        raw_response = ""

        add_sir_flag = random.random() < 0.33  # 33% chance to add "sir"

        # Check for short, conversational forced LLM words
        is_forced_llm = False
        if len(text.split()) <= 2:
            for word in FORCED_LLM_WORDS:
                if fuzz.ratio(text, word) > 90:
                    is_forced_llm = True
                    break

        if not is_forced_llm:
            # Check for hardcoded commands
            for cmd, info in commands.items():
                for kw in info["keywords"]:
                    similarity = fuzz.ratio(text, kw.lower())
                    partial_similarity = fuzz.partial_ratio(text, kw.lower())

                    # Skip if keyword is much longer than input to avoid false positives
                    if cmd not in ["chrome", "youtube", "itunes"]:
                        length_ratio = len(kw) / max(len(text), 1)
                        if length_ratio < 0.5 and similarity < 90:
                            continue

                    if similarity > 85 or partial_similarity > 98:  # Match threshold

                        raw_resp = info["responses"]
                        if isinstance(raw_resp, list):
                            item = random.choice(raw_resp)
                            raw_response = item() if callable(item) else item
                        else:
                            raw_response = (
                                raw_resp() if callable(raw_resp) else raw_response
                            )

                        if cmd == "shut down":
                            speak(raw_response)
                            exit()  # Terminate program

                        final_response = format_for_tts(raw_response, add_sir_flag)
                        speak(final_response)

                        last_operation = (
                            f"Hard Command: {text}, Response: {final_response}"
                        )
                        found_command = True
                        break
                if found_command:
                    break

        if not found_command:
            # Fallback to LLM if no command matched
            print("...Consulting Gemma 3 via LM Studio...")

            raw_response = ask_llm(text)

            if not raw_response:
                raw_response = "I have received your query, but the network response was null. Could you repeat that that, sir?"

            final_response = format_for_tts(raw_response, add_sir_flag)
            speak(final_response)

        # Update and trim conversation history
        conversation_history.append({"user": text, "jarvis": final_response})

        if len(conversation_history) > MAX_HISTORY:
            conversation_history.pop(0)

        print("-" * 30)
