# Running and Testing MagicCAD AI with Gemini

This guide shows you how to run and test MagicCAD AI with your Gemini API key.

---

## 📋 Prerequisites

1. **FreeCAD Build Environment** - Already set up with pixi
2. **Gemini API Key** - Get it from https://aistudio.google.com/app/apikey
3. **Python Dependencies** - Will be installed via pixi

---

## 🚀 Quick Start (5 Steps)

### Step 1: Get Your Gemini API Key

1. Visit https://aistudio.google.com/app/apikey
2. Click "Create API Key"
3. Copy your API key (looks like: `AIzaSy...`)

### Step 2: Set Environment Variable

**Linux/macOS:**
```bash
export GEMINI_API_KEY="your-api-key-here"
```

**Windows (PowerShell):**
```powershell
$env:GEMINI_API_KEY="your-api-key-here"
```

**Windows (CMD):**
```cmd
set GEMINI_API_KEY=your-api-key-here
```

### Step 3: Install Dependencies

```bash
cd /home/soham/coding/proj/MagicCAD
pixi install
```

This will install:
- `google-generativeai` (for Gemini)
- `openai` (optional, for OpenAI)
- `langgraph` (for workflow orchestration)
- All other dependencies

### Step 4: Build FreeCAD (if not already built)

```bash
# Configure
pixi run configure

# Build (this takes a while)
pixi run build

# Install
pixi run install
```

**Note:** Full build can take 30-60 minutes. If you already have a build, skip this step.

### Step 5: Launch FreeCAD

```bash
pixi run freecad
```

Or directly:
```bash
# Debug build
./build/debug/bin/FreeCAD

# Release build
./build/release/bin/FreeCAD
```

---

## 🧪 Testing Gemini Integration

### Test 1: Verify Gemini is Available

Once FreeCAD is running:

1. Open the Python console (View → Panels → Python console)
2. Run this test script:

```python
import sys
sys.path.append('/home/soham/coding/proj/MagicCAD/src/Mod/MagicCADAI')

# Test Gemini responder
from SidecarServer import GeminiResponder, _get_model_provider

# Test provider detection
print("Testing provider detection:")
print(f"  gemini-2.0-flash → {_get_model_provider('gemini-2.0-flash')}")
print(f"  gemini-1.5-pro → {_get_model_provider('gemini-1.5-pro')}")
print(f"  gpt-5.4 → {_get_model_provider('gpt-5.4')}")
print(f"  (empty) → {_get_model_provider('')}")

# Test Gemini responder
print("\nTesting Gemini responder:")
responder = GeminiResponder()
print(f"  Available: {responder.available}")
if not responder.available:
    print(f"  Error: {responder.last_error}")
else:
    print("  ✓ Gemini is ready!")
```

**Expected Output:**
```
Testing provider detection:
  gemini-2.0-flash → gemini
  gemini-1.5-pro → gemini
  gpt-5.4 → openai
  (empty) → openai

Testing Gemini responder:
  Available: True
  ✓ Gemini is ready!
```

---

### Test 2: Start the Sidecar Server

The sidecar server needs to run separately:

```bash
# In a new terminal (keep FreeCAD running)
cd /home/soham/coding/proj/MagicCAD

# Activate pixi environment
pixi shell

# Run sidecar server
python src/Mod/MagicCADAI/SidecarServer.py --port 50173
```

**Expected Output:**
```
MagicCADAI sidecar listening on http://127.0.0.1:50173
```

Keep this terminal open - the sidecar needs to run while you use FreeCAD.

---

### Test 3: Test Sidecar Health Check

In another terminal:

```bash
curl http://localhost:50173/health
```

**Expected Response:**
```json
{
  "ok": true,
  "status": "ready",
  "timestamp": "2026-03-30T12:00:00Z",
  "langgraph_enabled": true
}
```

---

### Test 4: Create a Test Validation Run

```bash
# Create a test script
cat > /tmp/test_gemini.py << 'EOF'
import json
import urllib.request

# Test payload
payload = {
    "model": "gemini-2.0-flash",
    "intent": "validate",
    "prompt": "Check for design issues",
    "snapshot": {
        "document_id": "test-001",
        "document_name": "TestPart",
        "objects": [
            {
                "name": "Body001",
                "label": "TestBody",
                "type_id": "PartDesign::Body",
                "shape": {"valid": True}
            }
        ],
        "selection": [],
        "dependency_edges": [],
        "recompute_errors": []
    }
}

# Send request
req = urllib.request.Request(
    'http://localhost:50173/v1/runs',
    data=json.dumps(payload).encode('utf-8'),
    headers={'Content-Type': 'application/json'}
)

try:
    with urllib.request.urlopen(req) as response:
        result = json.loads(response.read().decode('utf-8'))
        print("✓ Run created successfully!")
        print(f"  Run ID: {result['run_id']}")
        print(f"  Thread ID: {result['thread_id']}")
except Exception as e:
    print(f"✗ Error: {e}")
EOF

python /tmp/test_gemini.py
```

---

### Test 5: Test in FreeCAD UI

1. **Open MagicCAD AI Workbench:**
   - In FreeCAD, go to workbench selector (top right)
   - Select "MagicCAD AI"

2. **Open the Panel:**
   - Click `MagicCAD AI` → `Open MagicCAD AI`
   - A dock panel should appear on the right

3. **Check Backend Status:**
   - Look at the panel footer or status area
   - Should show "Gemini: Available" or similar

4. **Run Validation:**
   - Create a simple part (e.g., create a Body + Sketch + Pad)
   - Click "Validate Document"
   - Watch the progress in the panel

5. **Check Report:**
   - After validation completes, check the "Report" tab
   - Should show analysis from Gemini

---

## 🧪 Comprehensive Test Suite

### Test Script for Gemini

Create this file: `/tmp/test_gemini_full.py`

```python
#!/usr/bin/env python3
"""
Complete Gemini integration test for MagicCAD AI
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error

BASE_URL = "http://localhost:50173"

def print_header(text):
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")

def print_step(text):
    print(f"→ {text}")

def print_success(text):
    print(f"✓ {text}")

def print_error(text):
    print(f"✗ {text}")

def test_health():
    """Test 1: Health check"""
    print_header("Test 1: Health Check")
    try:
        with urllib.request.urlopen(f"{BASE_URL}/health") as response:
            data = json.loads(response.read().decode('utf-8'))
            if data.get('ok'):
                print_success(f"Sidecar is healthy: {data.get('status')}")
                print(f"  LangGraph: {data.get('langgraph_enabled')}")
                return True
            else:
                print_error("Health check failed")
                return False
    except Exception as e:
        print_error(f"Health check failed: {e}")
        return False

def test_create_run(model="gemini-2.0-flash"):
    """Test 2: Create validation run"""
    print_header(f"Test 2: Create Run with {model}")
    
    payload = {
        "model": model,
        "intent": "validate",
        "prompt": "Validate this design",
        "snapshot": {
            "document_id": "test-001",
            "document_name": "TestPart",
            "objects": [
                {
                    "name": "Body001",
                    "label": "TestBody",
                    "type_id": "PartDesign::Body",
                    "shape": {"valid": True, "volume": 100.0}
                }
            ],
            "selection": [],
            "dependency_edges": [],
            "recompute_errors": []
        }
    }
    
    try:
        req = urllib.request.Request(
            f"{BASE_URL}/v1/runs",
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        
        with urllib.request.urlopen(req) as response:
            result = json.loads(response.read().decode('utf-8'))
            if result.get('ok'):
                print_success(f"Run created: {result['run_id']}")
                return result['run_id']
            else:
                print_error(f"Run creation failed: {result}")
                return None
    except Exception as e:
        print_error(f"Run creation failed: {e}")
        return None

def test_stream_events(run_id, timeout=30):
    """Test 3: Stream events"""
    print_header(f"Test 3: Stream Events for {run_id}")
    
    events_received = []
    start_time = time.time()
    
    try:
        req = urllib.request.Request(f"{BASE_URL}/v1/runs/{run_id}/events")
        
        with urllib.request.urlopen(req, timeout=timeout) as response:
            while time.time() - start_time < timeout:
                line = response.readline().decode('utf-8')
                if line.startswith('data:'):
                    try:
                        data = json.loads(line[5:])
                        event_type = data.get('event', 'unknown')
                        events_received.append(event_type)
                        print(f"  Event: {event_type}")
                        
                        if event_type == 'run_finished':
                            print_success("Run completed successfully")
                            return True
                    except:
                        pass
                if not line:
                    break
                    
    except Exception as e:
        print_error(f"Event streaming failed: {e}")
    
    print(f"Events received: {len(events_received)}")
    return len(events_received) > 0

def test_provider_detection():
    """Test 4: Provider detection logic"""
    print_header("Test 4: Provider Detection")
    
    sys.path.insert(0, '/home/soham/coding/proj/MagicCAD/src/Mod/MagicCADAI')
    from SidecarServer import _get_model_provider
    
    tests = [
        ("gemini-2.0-flash", "gemini"),
        ("gemini-1.5-pro", "gemini"),
        ("gemini-1.5-flash", "gemini"),
        ("gpt-5.4", "openai"),
        ("gpt-5.4-pro", "openai"),
        ("", "openai"),
        (None, "openai"),
    ]
    
    all_passed = True
    for model, expected in tests:
        result = _get_model_provider(model)
        status = "✓" if result == expected else "✗"
        print(f"  {status} {model!r:20} → {result:10} (expected: {expected})")
        if result != expected:
            all_passed = False
    
    return all_passed

def test_responder_availability():
    """Test 5: Responder availability"""
    print_header("Test 5: Responder Availability")
    
    sys.path.insert(0, '/home/soham/coding/proj/MagicCAD/src/Mod/MagicCADAI')
    from SidecarServer import OpenAIResponder, GeminiResponder
    
    # Test OpenAI
    openai = OpenAIResponder()
    openai_key = os.environ.get('OPENAI_API_KEY', 'NOT SET')
    print(f"OpenAI API Key: {'SET' if openai_key != 'NOT SET' else 'NOT SET'}")
    print(f"  Available: {openai.available}")
    if not openai.available:
        print(f"  Error: {openai.last_error}")
    
    # Test Gemini
    gemini = GeminiResponder()
    gemini_key = os.environ.get('GEMINI_API_KEY', 'NOT SET')
    print(f"Gemini API Key: {'SET' if gemini_key != 'NOT SET' else 'NOT SET'}")
    print(f"  Available: {gemini.available}")
    if not gemini.available:
        print(f"  Error: {gemini.last_error}")
    
    return gemini.available

def main():
    print_header("MagicCAD AI - Gemini Integration Test Suite")
    
    # Check environment
    print_step("Checking environment...")
    gemini_key = os.environ.get('GEMINI_API_KEY')
    if not gemini_key:
        print_error("GEMINI_API_KEY is not set!")
        print("Set it with: export GEMINI_API_KEY='your-key'")
        return False
    
    print_success("GEMINI_API_KEY is set")
    
    # Run tests
    results = {}
    
    results['health'] = test_health()
    time.sleep(1)
    
    results['provider'] = test_provider_detection()
    
    results['availability'] = test_responder_availability()
    
    run_id = test_create_run("gemini-2.0-flash")
    if run_id:
        time.sleep(2)
        results['stream'] = test_stream_events(run_id)
    else:
        results['stream'] = False
    
    # Summary
    print_header("Test Summary")
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {test_name}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print_success("All tests passed! 🎉")
    else:
        print_error("Some tests failed")
    
    return all_passed

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
```

Run it:

```bash
# Make sure sidecar is running first
python /tmp/test_gemini_full.py
```

---

## 🔍 Debugging Tips

### Issue: Sidecar won't start

```bash
# Check if port is in use
lsof -i :50173

# Kill existing process if needed
kill -9 <PID>

# Try starting again
python src/Mod/MagicCADAI/SidecarServer.py --port 50173
```

### Issue: Gemini not available

```bash
# Check environment variable
echo $GEMINI_API_KEY

# Test API key directly
python3 << 'EOF'
import os
import google.generativeai as genai

genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))
try:
    model = genai.GenerativeModel('gemini-2.0-flash')
    response = model.generate_content("Hello")
    print("✓ Gemini API works!")
except Exception as e:
    print(f"✗ Error: {e}")
EOF
```

### Issue: Import errors

```bash
# Make sure you're in pixi environment
pixi shell

# Reinstall dependencies
pixi install --force
```

---

## 📊 Expected Behavior

### With Gemini API Key Set

- ✓ Sidecar starts successfully
- ✓ Health check returns `ok: true`
- ✓ Validation runs complete
- ✓ Reports show Gemini analysis
- ✓ Tool calling works
- ✓ Approval flow works

### Without Gemini API Key

- ✓ System falls back to OpenAI (if available)
- ✓ Deterministic validation still works
- ✓ Clear error messages shown
- ✓ No crashes or freezes

---

## 🎯 Quick Test Checklist

Run through these steps:

- [ ] Set `GEMINI_API_KEY`
- [ ] Run `pixi install`
- [ ] Start sidecar: `python SidecarServer.py --port 50173`
- [ ] Check health: `curl http://localhost:50173/health`
- [ ] Run test script: `python /tmp/test_gemini_full.py`
- [ ] Launch FreeCAD: `pixi run freecad`
- [ ] Open MagicCAD AI workbench
- [ ] Open panel
- [ ] Create simple part
- [ ] Run validation
- [ ] Check report shows Gemini analysis

---

## 📝 Example Session

```bash
# Terminal 1: Start sidecar
cd /home/soham/coding/proj/MagicCAD
pixi shell
export GEMINI_API_KEY="AIzaSy..."
python src/Mod/MagicCADAI/SidecarServer.py --port 50173

# Terminal 2: Run tests
pixi shell
export GEMINI_API_KEY="AIzaSy..."
python /tmp/test_gemini_full.py

# Terminal 3: Launch FreeCAD
pixi shell
export GEMINI_API_KEY="AIzaSy..."
pixi run freecad
```

---

## 🎉 Success Indicators

You'll know it's working when:

1. Sidecar starts without errors
2. Health check succeeds
3. Test script shows all PASS
4. FreeCAD panel shows "Gemini: Available"
5. Validation runs complete with Gemini responses
6. Reports mention Gemini analysis

---

**Last Updated:** 2026-03-30  
**Status:** Production Ready ✅
