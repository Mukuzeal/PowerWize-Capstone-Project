#!/usr/bin/env python
"""Test Qwen3.5 VL selfie validation."""

import requests
from PIL import Image, ImageDraw
import io

print("=== Testing Qwen3.5 VL Selfie Validation ===\n")

# Test 1: Create a fake "selfie with ID" image (for testing)
print("[1] Creating test image (selfie with ID)...")
img = Image.new('RGB', (400, 300), color='white')
draw = ImageDraw.Draw(img)

# Draw a simple face-like area
draw.ellipse([150, 50, 250, 150], outline='black', width=2)
draw.text((170, 90), "FACE", fill='black')

# Draw a simple ID-like area
draw.rectangle([50, 160, 350, 280], outline='black', width=2)
draw.text((60, 180), "ID CARD", fill='black')
draw.text((60, 210), "NAME: JOHN DOE", fill='black')
draw.text((60, 240), "ID: 123456789", fill='black')

img_bytes = io.BytesIO()
img.save(img_bytes, format='JPEG')
img_bytes.seek(0)

print("    Image created: 400x300, JPEG")

# Test 2: Upload selfie to validation endpoint
print("\n[2] Testing /api/face-match endpoint...")

try:
    r = requests.post('http://127.0.0.1:5000/api/face-match',
        files={'selfie': ('test_selfie.jpg', img_bytes, 'image/jpeg')},
        timeout=15)

    print(f"    Status: {r.status_code}")

    if r.status_code == 200:
        data = r.json()
        print(f"    Valid: {data.get('valid')}")
        print(f"    Reason: {data.get('reason')}")

        details = data.get('details', {})
        print(f"\n    Validation Details:")
        for key, value in details.items():
            print(f"      - {key}: {value}")

        if data.get('filename'):
            print(f"    Saved as: {data['filename']}")
    else:
        print(f"    Error: {r.status_code}")
        print(f"    Response: {r.text[:300]}")

except requests.exceptions.ConnectionError:
    print("    ERROR: Cannot connect to Flask server")
    print("    Make sure Flask is running on http://127.0.0.1:5000")
except Exception as e:
    print(f"    ERROR: {type(e).__name__}: {e}")

# Test 3: Check if LMStudio is accessible
print("\n[3] Checking LMStudio...")
try:
    r = requests.get("http://localhost:1234/v1/models", timeout=5)
    if r.status_code == 200:
        models = r.json().get("data", [])
        print(f"    LMStudio is running")
        print(f"    Models available: {len(models)}")
        for model in models:
            print(f"      - {model.get('id')}")
    else:
        print(f"    LMStudio error: {r.status_code}")
except Exception as e:
    print(f"    LMStudio not accessible: {e}")

print("\n=== Test Complete ===")
print("\nNote: The AI validation result depends on:")
print("  - Whether Qwen3.5 VL can recognize faces in test images")
print("  - Test image quality (real selfies will validate better)")
print("\nNext steps:")
print("  1. Try with a real selfie + ID photo")
print("  2. Try a blurry photo (should be rejected)")
print("  3. Try without ID (should be rejected)")
