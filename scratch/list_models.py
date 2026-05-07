import os
from dotenv import load_dotenv
import google.genai as genai

load_dotenv()

def list_available_models():
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("[ERROR] GEMINI_API_KEY not found")
        return

    client = genai.Client(api_key=api_key)
    print("Available Gemini Models:")
    try:
        # Use the models.list method
        for model in client.models.list():
            print(f"- {model.name}")
    except Exception as e:
        print(f"[ERROR] Could not list models: {str(e)}")

if __name__ == "__main__":
    list_available_models()
