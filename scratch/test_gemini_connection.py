import os
from dotenv import load_dotenv
import google.genai as genai

# Load environment variables
load_dotenv()

def test_connection():
    api_key = os.getenv("GEMINI_API_KEY")
    model_name = os.getenv("GEMINI_MODEL")
    
    if not api_key:
        print("[ERROR] GEMINI_API_KEY not found in .env file")
        return
    
    if not model_name:
        model_name = "gemini-2.0-flash"
        print(f"[WARNING] GEMINI_MODEL not found in .env, using default: {model_name}")

    print(f"Testing Gemini connection...")
    print(f"Model: {model_name}")
    print(f"API Key: {api_key[:5]}...{api_key[-5:]}")
    
    try:
        # Initialize client
        client = genai.Client(api_key=api_key)
        
        # Simple test prompt
        prompt = "Hello, please reply with 'Connection successful' and a short joke."
        
        print("Sending test request...")
        response = client.models.generate_content(
            model=model_name,
            contents=prompt
        )
        
        print("\n--- Response ---")
        print(response.text)
        print("----------------\n")
        print("[SUCCESS] Connection test PASSED!")
        
    except Exception as e:
        print(f"[ERROR] Connection test FAILED: {str(e)}")


if __name__ == "__main__":
    test_connection()
