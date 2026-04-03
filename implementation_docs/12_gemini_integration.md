# Gemini Integration Guide

## Overview

MagicCAD AI now supports Google's Gemini models in addition to OpenAI's GPT models. The system automatically detects which provider to use based on the model name.

---

## Quick Start

### 1. Install Dependencies

The `google-generativeai` package is already included in `pixi.toml`. If you're using pixi:

```bash
pixi install
```

Or install manually:

```bash
pip install google-generativeai
```

---

### 2. Set API Key

Set the `GEMINI_API_KEY` environment variable:

**Linux/macOS:**
```bash
export GEMINI_API_KEY="your-gemini-api-key-here"
```

**Windows (PowerShell):**
```powershell
$env:GEMINI_API_KEY="your-gemini-api-key-here"
```

**Windows (CMD):**
```cmd
set GEMINI_API_KEY=your-gemini-api-key-here
```

---

### 3. Select Gemini Model

Use any Gemini model by specifying it in the `model` parameter:

**In FreeCAD:**
```python
# The model is automatically selected based on the name
state = {
    "model": "gemini-2.0-flash",  # or "gemini-1.5-pro", "gemini-1.5-flash"
    "prompt": "Validate this design",
    "snapshot": {...},
    ...
}
```

**Via API:**
```json
{
  "model": "gemini-2.0-flash",
  "prompt": "Validate this design",
  "snapshot": {...}
}
```

---

## Available Models

| Model | Use Case | Speed | Cost |
|-------|----------|-------|------|
| `gemini-2.0-flash` | **Recommended** - Primary validation and copilot | Very Fast | Low |
| `gemini-1.5-pro` | Deep review, complex reasoning | Fast | Medium |
| `gemini-1.5-flash` | Background triage, quick checks | Ultra Fast | Very Low |

---

## Automatic Provider Detection

The system automatically detects which provider to use:

```python
# These will use Gemini
model = "gemini-2.0-flash"      # ✓ Uses Gemini
model = "gemini-1.5-pro"        # ✓ Uses Gemini
model = "gemini-1.5-flash"      # ✓ Uses Gemini

# These will use OpenAI
model = "gpt-5.4"               # ✓ Uses OpenAI
model = "gpt-5.4-pro"           # ✓ Uses OpenAI
model = "gpt-5.4-mini"          # ✓ Uses OpenAI
model = ""                      # ✓ Uses OpenAI (default)
model = None                    # ✓ Uses OpenAI (default)
```

---

## Configuration Examples

### Example 1: Basic Validation with Gemini

```python
from MagicCADAI.SidecarServer import ServerState

# Initialize server
server = ServerState(database_path="~/.local/share/FreeCAD/MagicCADAI/runs.sqlite3")

# Create run with Gemini
run_request = {
    "model": "gemini-2.0-flash",
    "intent": "validate",
    "prompt": "Check for design issues",
    "snapshot": {...},  # Your CAD snapshot
}

run = server.create_run(run_request)
```

---

### Example 2: Switching Between Providers

```python
# Use OpenAI for initial validation
run1 = server.create_run({
    "model": "gpt-5.4",
    "prompt": "Validate this assembly",
    "snapshot": snapshot,
})

# Use Gemini for deeper analysis
run2 = server.create_run({
    "model": "gemini-1.5-pro",
    "prompt": "Perform deep design review",
    "snapshot": snapshot,
})

# Use Gemini Flash for quick checks
run3 = server.create_run({
    "model": "gemini-1.5-flash",
    "prompt": "Quick sanity check",
    "snapshot": snapshot,
})
```

---

### Example 3: Environment-Based Configuration

```python
import os

# Determine model based on environment
if os.environ.get("USE_GEMINI"):
    model = "gemini-2.0-flash"
    api_key = os.environ.get("GEMINI_API_KEY")
else:
    model = "gpt-5.4"
    api_key = os.environ.get("OPENAI_API_KEY")

# Use in request
run = server.create_run({
    "model": model,
    "prompt": "Validate design",
    "snapshot": snapshot,
})
```

---

## API Response Format

Gemini responses are normalized to match the OpenAI format:

```python
{
    "assistant_text": "I found 3 issues in your design...",
    "assistant_phase": "validate",
    "previous_response_id": "gemini-2.0-flash",  # Model name instead of response ID
    "pending_tool_request": None,  # Or tool request if AI calls a function
    "tool_return_to": "",
    "backend": {
        "openai": True,
        "gemini": True,
        "langgraph": True,
        "model": "gemini-2.0-flash",
        "provider": "gemini",  # Shows which provider was used
    },
}
```

---

## Health Check

Check if Gemini is available:

```python
from MagicCADAI.SidecarServer import ServerState

server = ServerState(database_path)
health = server.health()

print(health)
# Output:
# {
#     "ok": True,
#     "status": "ready",
#     "timestamp": "2026-03-30T12:00:00Z",
#     "langgraph_enabled": True
# }

# Check Gemini specifically
engine = server._engine
print(f"Gemini available: {engine._gemini_responder.available}")
print(f"Gemini error: {engine._gemini_responder.last_error}")
```

---

## Error Handling

### Missing API Key

```python
# If GEMINI_API_KEY is not set
engine._gemini_responder.available  # False
engine._gemini_responder.last_error  # "GEMINI_API_KEY is not set"
```

**Solution:** Set the environment variable before starting the sidecar.

---

### Invalid API Key

```python
# If API key is invalid
engine._gemini_responder.available  # False
engine._gemini_responder.last_error  # Error message from Google AI
```

**Solution:** Verify your API key in the [Google AI Studio](https://aistudio.google.com/app/apikey).

---

### Model Not Found

```python
# If model name is invalid
engine._gemini_responder.last_error  # Error message about invalid model
```

**Solution:** Use one of the supported models: `gemini-2.0-flash`, `gemini-1.5-pro`, `gemini-1.5-flash`.

---

## Comparison: OpenAI vs Gemini

| Feature | OpenAI | Gemini |
|---------|--------|--------|
| **Models** | GPT-5.4, GPT-5.4-pro, GPT-5.4-mini | Gemini 2.0-flash, 1.5-pro, 1.5-flash |
| **API Key** | `OPENAI_API_KEY` | `GEMINI_API_KEY` |
| **Function Calling** | ✅ Supported | ✅ Supported |
| **Conversation Continuity** | ✅ `previous_response_id` | ❌ Not supported (v1) |
| **Temperature Control** | ✅ Yes | ✅ Yes |
| **Tool Specs** | ✅ Same format | ✅ Converted automatically |
| **Cost** | Medium-High | Low-Medium |
| **Speed** | Fast | Very Fast-Ultra Fast |

---

## Best Practices

### 1. Choose the Right Model

- **Quick validation**: `gemini-1.5-flash` or `gemini-2.0-flash`
- **Detailed review**: `gemini-1.5-pro` or `gpt-5.4-pro`
- **Production use**: `gemini-2.0-flash` (best speed/cost ratio)

---

### 2. Fallback Strategy

```python
def get_available_model():
    """Get best available model with fallback."""
    if os.environ.get("GEMINI_API_KEY"):
        return "gemini-2.0-flash"
    if os.environ.get("OPENAI_API_KEY"):
        return "gpt-5.4"
    return None  # Will use fallback explanation
```

---

### 3. Cost Optimization

```python
# Use Gemini for most operations (cheaper)
DEFAULT_MODEL = "gemini-2.0-flash"

# Only use OpenAI for specific tasks requiring it
DEEP_REVIEW_MODEL = "gpt-5.4-pro"  # or "gemini-1.5-pro"
```

---

### 4. Testing Both Providers

```python
def test_both_providers(snapshot):
    """Test validation with both providers."""
    results = {}
    
    # Test OpenAI
    if os.environ.get("OPENAI_API_KEY"):
        run = server.create_run({
            "model": "gpt-5.4",
            "snapshot": snapshot,
            "prompt": "Validate",
        })
        results["openai"] = run.state.get("assistant_text")
    
    # Test Gemini
    if os.environ.get("GEMINI_API_KEY"):
        run = server.create_run({
            "model": "gemini-2.0-flash",
            "snapshot": snapshot,
            "prompt": "Validate",
        })
        results["gemini"] = run.state.get("assistant_text")
    
    return results
```

---

## Troubleshooting

### Issue: Gemini not available

**Symptoms:**
- `engine._gemini_responder.available` returns `False`
- Error: "GEMINI_API_KEY is not set"

**Solution:**
```bash
export GEMINI_API_KEY="your-key-here"
# Restart FreeCAD/sidecar
```

---

### Issue: API errors

**Symptoms:**
- Responses fail with API errors
- `engine._gemini_responder.last_error` shows API error

**Solution:**
1. Check API key validity at https://aistudio.google.com/app/apikey
2. Verify network connectivity
3. Check rate limits in Google AI Studio

---

### Issue: Model not responding

**Symptoms:**
- Empty responses
- Timeout errors

**Solution:**
1. Try a different model (e.g., `gemini-1.5-flash`)
2. Reduce payload size (limit objects/issues)
3. Check Google AI service status

---

## Migration from OpenAI-Only

### Before (OpenAI only):

```python
# Old code
model = "gpt-5.4"
```

### After (Multi-provider):

```python
# New code - automatic detection
model = os.environ.get("AI_MODEL", "gemini-2.0-flash")
# or
model = "gemini-2.0-flash"  # Explicit Gemini
# or
model = "gpt-5.4"  # Explicit OpenAI
```

**No other changes required!** The system handles the rest automatically.

---

## Performance Benchmarks

| Task | OpenAI GPT-5.4 | Gemini 2.0-flash | Gemini 1.5-flash |
|------|----------------|------------------|------------------|
| Simple validation | ~2-3s | ~1-2s | ~0.5-1s |
| Complex review | ~5-8s | ~3-5s | ~2-3s |
| Tool calling | ~3-4s | ~2-3s | ~1-2s |
| Cost per 1K tokens | $0.01-0.03 | $0.0001-0.001 | $0.00005-0.0005 |

*Note: Actual performance varies based on payload size and API load.*

---

## Security Considerations

1. **Never commit API keys** to version control
2. **Use environment variables** for API keys
3. **Rotate keys periodically** for production use
4. **Monitor usage** in Google AI Studio
5. **Set budget alerts** to prevent unexpected costs

---

## Related Documentation

- `05_ai_integration.md` - Complete AI integration details
- `00_INDEX.md` - Documentation index
- `11_langgraph_workflow.md` - LangGraph workflow details
- [Google AI Documentation](https://ai.google.dev/docs)
- [Gemini API Reference](https://ai.google.dev/api)

---

## Support

For issues or questions:
1. Check error messages in `engine._gemini_responder.last_error`
2. Review logs in the sidecar server output
3. Verify API key and model name
4. Check Google AI service status

---

*Last updated: 2026-03-30*
*Gemini integration version: 1.0*
