#!/usr/bin/env python
"""List available Gemini models"""

import sys
sys.path.insert(0, 'src')

import google.genai as genai
from config.settings import settings

print("\n" + "="*80)
print("🔍 CHECKING AVAILABLE GEMINI MODELS")
print("="*80 + "\n")

try:
    # Initialize client
    client = genai.Client(api_key=settings.GEMINI_API_KEY)
    
    # List available models
    print("Available models:\n")
    models = client.models.list()
    
    available_models = []
    for model in models:
        model_name = model.name
        print(f"  - {model_name}")
        available_models.append(model_name)
    
    print("\n" + "="*80)
    print(f"Total models available: {len(available_models)}")
    print("="*80 + "\n")
    
    # Find flash models
    flash_models = [m for m in available_models if 'flash' in m.lower()]
    pro_models = [m for m in available_models if 'pro' in m.lower()]
    
    if flash_models:
        print("💡 Flash models (recommended for fast inference):")
        for m in flash_models:
            print(f"   {m}")
    
    if pro_models:
        print("\n💡 Pro models (most capable):")
        for m in pro_models:
            print(f"   {m}")
    
    print("\n" + "="*80)
    
except Exception as e:
    print(f"❌ Error: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
