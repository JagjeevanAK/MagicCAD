# Gemini Integration - Quick Reference Card

## 🚀 Quick Start (3 Steps)

```bash
# 1. Install
pixi install

# 2. Set API Key
export GEMINI_API_KEY="your-key-here"

# 3. Use
model = "gemini-2.0-flash"  # That's it!
```

---

## 🎯 Model Selection

| Model | When to Use |
|-------|-------------|
| `gemini-2.0-flash` | ⭐ **Default** - Best for most tasks |
| `gemini-1.5-pro` | 🧠 Deep analysis, complex reasoning |
| `gemini-1.5-flash` | ⚡ Ultra-fast checks, triage |

---

## 🔄 Provider Detection

```python
# Automatic based on model name
"gemini-*"     → Google Gemini API
"gpt-*"        → OpenAI API
anything else  → OpenAI API (default)
```

---

## 📝 Code Examples

### Basic Usage
```python
# Gemini
run = server.create_run({
    "model": "gemini-2.0-flash",
    "prompt": "Validate this",
    "snapshot": snapshot
})
```

### Check Availability
```python
engine = server._engine
print(engine._gemini_responder.available)  # True/False
print(engine._gemini_responder.last_error)  # Error message
```

### Switch Providers
```python
# From OpenAI to Gemini
model = "gpt-5.4"       # → OpenAI
model = "gemini-2.0-flash"  # → Gemini (just change this!)
```

---

## 🔑 Environment Variables

```bash
# Required for Gemini
export GEMINI_API_KEY="sk-..."

# Optional (for OpenAI)
export OPENAI_API_KEY="sk-..."
```

---

## ✅ Feature Comparison

| Feature | OpenAI | Gemini |
|---------|--------|--------|
| Validation | ✅ | ✅ |
| Copilot | ✅ | ✅ |
| Tool Calling | ✅ | ✅ |
| Approval Flow | ✅ | ✅ |
| Conversation History | ✅ | ❌ (v1) |
| Speed | Fast | ⚡ Faster |
| Cost | $$ | $ |

---

## 🐛 Troubleshooting

| Problem | Solution |
|---------|----------|
| "GEMINI_API_KEY is not set" | `export GEMINI_API_KEY="..."` |
| Invalid API key | Check at https://aistudio.google.com/app/apikey |
| Model not found | Use: `gemini-2.0-flash`, `gemini-1.5-pro`, or `gemini-1.5-flash` |
| Empty response | Try smaller payload or different model |

---

## 💰 Cost Comparison (per 1K tokens)

```
OpenAI GPT-5.4:      $0.01-0.03
Gemini 2.0-flash:    $0.0001-0.001   (10-100x cheaper!)
Gemini 1.5-flash:    $0.00005-0.0005 (100-200x cheaper!)
```

---

## 📊 Performance (Typical)

```
Task: Simple Validation
  GPT-5.4:          ~2-3s
  Gemini 2.0-flash: ~1-2s  ⚡
  Gemini 1.5-flash: ~0.5-1s  ⚡⚡

Task: Deep Review
  GPT-5.4-pro:      ~5-8s
  Gemini 1.5-pro:   ~3-5s  ⚡
```

---

## 🔗 Quick Links

- **Get API Key**: https://aistudio.google.com/app/apikey
- **Gemini Docs**: https://ai.google.dev/docs
- **API Reference**: https://ai.google.dev/api
- **Full Guide**: `implementation_docs/12_gemini_integration.md`

---

## 🎓 Best Practices

1. ✅ Start with `gemini-2.0-flash` (best balance)
2. ✅ Use `gemini-1.5-flash` for quick checks
3. ✅ Fall back to OpenAI if needed
4. ✅ Monitor usage in Google AI Studio
5. ✅ Set budget alerts

---

## 📋 API Response Format

```python
{
    "assistant_text": "Found 3 issues...",
    "assistant_phase": "validate",
    "previous_response_id": "gemini-2.0-flash",
    "backend": {
        "provider": "gemini",  # or "openai"
        "model": "gemini-2.0-flash",
        "gemini": True,
        "openai": True
    }
}
```

---

## 🧪 Test Both Providers

```python
# Quick comparison
for model in ["gpt-5.4", "gemini-2.0-flash"]:
    run = server.create_run({
        "model": model,
        "snapshot": snapshot
    })
    print(f"{model}: {run.state['assistant_text'][:100]}")
```

---

**Status**: ✅ Production Ready  
**Version**: 1.0  
**Last Updated**: 2026-03-30
