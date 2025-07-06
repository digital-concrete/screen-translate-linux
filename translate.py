import subprocess
from PIL import Image
import pytesseract
import cv2
import numpy as np
import tkinter as tk
from tkinter import ttk
import threading
import os
import requests
import html
from dotenv import load_dotenv
from openai import OpenAI, OpenAIError

import xml.etree.ElementTree as ET
from pathlib import Path

# Load API keys
load_dotenv()
openai_key = os.getenv("OPENAI_API_KEY")
google_key = os.getenv("GOOGLE_API_KEY")  # make sure this is in your .env

client = OpenAI(api_key=openai_key)


def get_monitor_scaling_from_xml():
    config = Path.home() / ".config/monitors.xml"
    if not config.exists():
        return 1  # Default scaling if file not found
    
    try:
        tree = ET.parse(config)
        root = tree.getroot()
        scale_elements = root.findall(".//scale")

        if not scale_elements:
            return 1  # Default if no <scale> tags

        # Use first <scale> value, rounded to nearest int
        scale = float(scale_elements[0].text)
        return round(scale)
    except Exception:
        return 1  # Fallback default on any error

print("Scaling factors from monitors.xml:", get_monitor_scaling_from_xml())

SCALING_FACTOR = get_monitor_scaling_from_xml() #1.5

def capture_with_gnome_screenshot():
    output_path = "/tmp/screen.png"
    try:
        subprocess.run(["gnome-screenshot", "-a", "-f", output_path], check=True)
        return output_path
    except Exception as e:
        print("❌ Screenshot failed:", e)
        return None

def preprocess_image_for_tesseract(image_path):
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    gray = cv2.resize(gray, None, fx=2, fy=2, interpolation=cv2.INTER_LINEAR)
    gray = cv2.bilateralFilter(gray, 11, 17, 17)

    thresh = cv2.adaptiveThreshold(
        gray, 255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        15, 10
    )

    kernel = np.ones((2, 2), np.uint8)
    processed = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)

    processed_path = "/tmp/processed.png"
    cv2.imwrite(processed_path, processed)
    return processed_path

def extract_text_with_tesseract(image_path):
    processed_path = preprocess_image_for_tesseract(image_path)
    config = '--psm 6'
    text = pytesseract.image_to_string(Image.open(processed_path), lang='fra', config=config)
    return text

def translate_with_chatgpt(text, target_lang="English"):
    if not text.strip():
        return ""
    prompt = (
        f"Translate the following comic-style text to {target_lang}. Preserve any tone, humor, or emotion.\n\n"
        f"Text:\n{text}\n\n"
        f"Translation:"
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "You are a helpful translator."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=1000,
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except OpenAIError as e:
        print("❌ ChatGPT translation failed:", e)
        return text

def translate_with_google(text, target_lang="en"):
    if not text.strip():
        return ""
    url = "https://translation.googleapis.com/language/translate/v2"
    params = {
        "q": text,
        "target": target_lang,
        "key": google_key
    }
    try:
        response = requests.post(url, data=params)
        if response.status_code == 200:
            translated_html = response.json()["data"]["translations"][0]["translatedText"]
            return html.unescape(translated_html)  # ✅ Decode HTML entities
        else:
            print("❌ Google Translate API error:", response.text)
            return text
    except Exception as e:
        print("❌ Google Translate failed:", e)
        return text

def capture_and_translate(selected_translator):
    print("📸 Select a region with your mouse (GNOME screenshot)...")
    path = capture_with_gnome_screenshot()
    if not path or not os.path.exists(path):
        return

    print("🔍 Extracting text with Tesseract + preprocessing...")
    text = extract_text_with_tesseract(path)

    if not text.strip():
        print("❗No text found.")
        return

    print(f"⏳ Translating with {selected_translator}...")
    if selected_translator == "OpenAI GPT":
        translated = translate_with_chatgpt(text, target_lang="English")
    else:
        translated = translate_with_google(text, target_lang="en")

    show_popup(text, translated, selected_translator)

def show_popup(original, translated, selected_translator):
    def run():
        window = tk.Tk()
        window.title("OCR + Translation Result")
        window.attributes("-topmost", True)  # Always on top
        window.lift()  # Bring to front
        window.focus_force()  # Force focus

        base_width, base_height = 700, 500

        if SCALING_FACTOR != 1:
            scale = SCALING_FACTOR
        else:
            scale = 1

        window.geometry(f"{int(base_width * scale)}x{int(base_height * scale)}")

        frame_original = tk.Frame(window)
        frame_original.pack(fill=tk.BOTH, expand=False, padx=10, pady=10)

        label_orig = tk.Label(frame_original, text="📝 Original Text (editable):", font=("Arial", 14))
        label_orig.pack(anchor="w")

        original_text = tk.Text(frame_original, wrap=tk.WORD, font=("Arial", 14), height=10)
        original_text.insert(tk.END, original)
        original_text.pack(fill=tk.BOTH, expand=True)

        def retranslate():
            edited_text = original_text.get("1.0", tk.END).strip()
            if not edited_text:
                return
            retranslate_btn.config(state=tk.DISABLED, text="Translating...")
            window.update()

            if selected_translator == "OpenAI GPT":
                new_translation = translate_with_chatgpt(edited_text, target_lang="English")
            else:
                new_translation = translate_with_google(edited_text, target_lang="en")

            translated_text.config(state=tk.NORMAL)
            translated_text.delete("1.0", tk.END)
            translated_text.insert(tk.END, new_translation)
            translated_text.config(state=tk.DISABLED)
            retranslate_btn.config(state=tk.NORMAL, text="🔄 Retranslate")

        retranslate_btn = tk.Button(frame_original, text="🔄 Retranslate", font=("Arial", 12), command=retranslate)
        retranslate_btn.pack(pady=10)

        frame_translated = tk.Frame(window)
        frame_translated.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0,10))

        label_trans = tk.Label(frame_translated, text="🌍 Translated Text:", font=("Arial", 14))
        label_trans.pack(anchor="w")

        translated_text = tk.Text(frame_translated, wrap=tk.WORD, font=("Arial", 14), height=10, state=tk.DISABLED)
        translated_text.pack(fill=tk.BOTH, expand=True)
        translated_text.config(state=tk.NORMAL)
        translated_text.insert(tk.END, translated)
        translated_text.config(state=tk.DISABLED)

        window.mainloop()

    threading.Thread(target=run).start()

def launch_gui():
    window = tk.Tk()
    window.attributes("-topmost", True)  # Always on top
    window.lift()  # Bring to front
    window.focus_force()  # Force focus

    # Apply scaling for DPI (this scales fonts and widget sizes automatically)
    window.tk.call('tk', 'scaling', SCALING_FACTOR)

    window.title("Screen Translate")

    # Multiply base width and height by scaling factor
    base_width, base_height = 350, 150
    if SCALING_FACTOR != 1:
        scale = SCALING_FACTOR
    else:
        scale = 1

    window.geometry(f"{int(base_width * scale)}x{int(base_height * scale)}")

    translator_var = tk.StringVar(value="OpenAI GPT")

    # Use scaled font size
    base_font_size = 12
    font_size = int(base_font_size * SCALING_FACTOR * 0.75)
    label_font = ("Arial", font_size)
    button_font = ("Arial", font_size)

    label = tk.Label(window, text="Select Translator:", font=label_font)
    label.pack(pady=(int(SCALING_FACTOR), int(SCALING_FACTOR)))

    dropdown = ttk.Combobox(window, textvariable=translator_var,
                            values=["OpenAI GPT", "Google Translate"], state="readonly",
                            font=label_font)
    dropdown.pack(pady=int(SCALING_FACTOR))

    def on_click():
        threading.Thread(target=capture_and_translate, args=(translator_var.get(),), daemon=True).start()

    btn = tk.Button(window, text="🖼️ Capture & Translate", command=on_click, font=button_font)
    btn.pack(pady=int(SCALING_FACTOR))

    window.mainloop()

if __name__ == "__main__":
    launch_gui()
