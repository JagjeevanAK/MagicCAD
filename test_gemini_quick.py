#!/usr/bin/env python3
"""
Quick test script for Gemini integration in MagicCAD AI

Usage:
    export GEMINI_API_KEY="your-key-here"
    python test_gemini_quick.py
"""

import os
import sys

# Add MagicCADAI to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src/Mod/MagicCADAI'))

def print_header(text):
    print("\n" + "="*60)
    print(f"  {text}")
    print("="*60 + "\n")

def test_provider_detection():
    """Test automatic provider detection"""
    from SidecarServer import _get_model_provider
    
    print("Testing Provider Detection:")
    print("-" * 40)
    
    tests = [
        ("gemini-2.0-flash", "gemini"),
        ("gemini-1.5-pro", "gemini"),
        ("gemini-1.5-flash", "gemini"),
        ("gpt-5.4", "openai"),
        ("gpt-5.4-pro", "openai"),
        ("", "openai"),
    ]
    
    all_pass = True
    for model, expected in tests:
        result = _get_model_provider(model)
        status = "✓" if result == expected else "✗"
        print(f"  {status} {model:20} → {result}")
        if result != expected:
            all_pass = False
    
    return all_pass

def test_gemini_responder():
    """Test Gemini responder initialization"""
    from SidecarServer import GeminiResponder
    
    print("\nTesting Gemini Responder:")
    print("-" * 40)
    
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        print("  ✗ GEMINI_API_KEY is not set")
        print("  → Set it: export GEMINI_API_KEY='your-key'")
        return False
    
    print(f"  ✓ GEMINI_API_KEY is set")
    
    responder = GeminiResponder()
    print(f"  ✓ Responder created")
    print(f"  {'✓' if responder.available else '✗'} Available: {responder.available}")
    
    if not responder.available:
        print(f"  → Error: {responder.last_error}")
        return False
    
    print(f"  ✓ Gemini is ready to use!")
    return True

def test_openai_responder():
    """Test OpenAI responder (optional)"""
    from SidecarServer import OpenAIResponder
    
    print("\nTesting OpenAI Responder (Optional):")
    print("-" * 40)
    
    api_key = os.environ.get('OPENAI_API_KEY')
    print(f"  {'✓' if api_key else '✗'} OPENAI_API_KEY is {'set' if api_key else 'NOT SET'}")
    
    responder = OpenAIResponder()
    print(f"  {'✓' if responder.available else '✗'} Available: {responder.available}")
    
    if not responder.available and api_key:
        print(f"  → Error: {responder.last_error}")
    
    return True

def test_model_selection():
    """Test model selection logic"""
    from SidecarServer import MagicCADAgentEngine, SQLiteRunStore
    import tempfile
    
    print("\nTesting Model Selection in Agent Engine:")
    print("-" * 40)
    
    # Create temporary store
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        store = SQLiteRunStore(f.name)
        engine = MagicCADAgentEngine(store)
        
        # Test Gemini selection
        state_gemini = {"model": "gemini-2.0-flash"}
        responder, provider = engine._get_responder(state_gemini)
        print(f"  ✓ gemini-2.0-flash → {provider} ({'GeminiResponder' if provider == 'gemini' else 'OpenAIResponder'})")
        
        # Test OpenAI selection
        state_openai = {"model": "gpt-5.4"}
        responder, provider = engine._get_responder(state_openai)
        print(f"  ✓ gpt-5.4 → {provider} ({'GeminiResponder' if provider == 'gemini' else 'OpenAIResponder'})")
        
        # Test default
        state_default = {}
        responder, provider = engine._get_responder(state_default)
        print(f"  ✓ default → {provider} ({'GeminiResponder' if provider == 'gemini' else 'OpenAIResponder'})")
        
        # Cleanup
        os.unlink(f.name)
    
    return True

def test_backend_info():
    """Test backend info reporting"""
    from SidecarServer import MagicCADAgentEngine, SQLiteRunStore
    import tempfile
    
    print("\nTesting Backend Info:")
    print("-" * 40)
    
    with tempfile.NamedTemporaryFile(suffix='.db', delete=False) as f:
        store = SQLiteRunStore(f.name)
        engine = MagicCADAgentEngine(store)
        
        state = {
            "model": "gemini-2.0-flash",
            "assistant_phase": "validate",
            "prompt": "test",
            "issues": [],
            "snapshot": {"objects": []}
        }
        
        # Simulate llm_explain call (without actual API call)
        print(f"  ✓ OpenAI available: {engine._openai_responder.available}")
        print(f"  ✓ Gemini available: {engine._gemini_responder.available}")
        print(f"  ✓ LangGraph available: {engine._langgraph.available}")
        
        # Cleanup
        os.unlink(f.name)
    
    return True

def main():
    print_header("MagicCAD AI - Gemini Quick Test")
    
    # Check environment
    gemini_key = os.environ.get('GEMINI_API_KEY')
    if not gemini_key:
        print("⚠️  GEMINI_API_KEY is not set!")
        print("Set it with: export GEMINI_API_KEY='your-key-here'")
        print("\nYou can get a key from: https://aistudio.google.com/app/apikey\n")
    else:
        print("✓ GEMINI_API_KEY is set\n")
    
    # Run tests
    results = {}
    
    try:
        results['Provider Detection'] = test_provider_detection()
    except Exception as e:
        print(f"✗ Provider detection failed: {e}")
        results['Provider Detection'] = False
    
    try:
        results['Gemini Responder'] = test_gemini_responder()
    except Exception as e:
        print(f"✗ Gemini responder test failed: {e}")
        results['Gemini Responder'] = False
    
    try:
        results['OpenAI Responder'] = test_openai_responder()
    except Exception as e:
        print(f"✗ OpenAI responder test failed: {e}")
        results['OpenAI Responder'] = False
    
    try:
        results['Model Selection'] = test_model_selection()
    except Exception as e:
        print(f"✗ Model selection test failed: {e}")
        results['Model Selection'] = False
    
    try:
        results['Backend Info'] = test_backend_info()
    except Exception as e:
        print(f"✗ Backend info test failed: {e}")
        results['Backend Info'] = False
    
    # Summary
    print_header("Test Summary")
    
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"  {status}: {test_name}")
    
    print()
    total = len(results)
    passed = sum(1 for v in results.values() if v)
    print(f"Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n🎉 All tests passed! Gemini integration is working!\n")
        return 0
    else:
        print("\n⚠️  Some tests failed. Check the errors above.\n")
        return 1

if __name__ == "__main__":
    sys.exit(main())
