# Koto Quick Start Guide - Phase 3A Ready

## 🚀 Getting Started in 5 Minutes

### 1. Verify Installation (1 min)
```bash
cd c:\Users\12524\Desktop\Koto

# Check Python
python --version
# Should be 3.10+

# Check required packages
python -c "import flask, numpy; print('✓ Dependencies OK')"
```

### 2. Test Everything (2 min)
```bash
# Run integration test
python test_phase2_3a.py

# Expected output:
# ✓ TEST 1 PASSED: Memory Manager
# ✓ TEST 2 PASSED: Vector Knowledge Base
# ✓ TEST 3 PASSED: Integration
```

### 3. Start the Server (1 min)
```bash
# Launch Flask dev server
python web/app.py

# Server starts at: http://localhost:5000
# Open in browser and test!
```

### 4. Try the Features (1 min)
In the browser:
1. **Memory** - Open Settings (⚙️), add a memory
2. **Markdown** - Send message with `$E=mc^2$` (KaTeX)
3. **Diagrams** - Try markdown with mermaid code block
4. **Tables** - Format: `| Header | Value |`
5. **Code** - Write code >5 lines, click ⟨/⟩ button

---

## 📚 What's New

### ✨ Phase 1: Frontend Enhancements
- 📐 **Math Formulas** - `$E=mc^2$` → renders as equation
- 📊 **Diagrams** - Mermaid graphs, charts, flowcharts
- 📋 **Tables** - Auto-styled with zebra stripes
- 🎨 **Artifacts Panel** - Side panel for code preview/edit

### 🧠 Phase 2A: Memory System
- 📝 **Persistent Memory** - Survives app restart
- 🔍 **Smart Search** - Keyword-based relevance
- 💬 **Auto-Injection** - AI uses your memories
- ⚙️ **Settings UI** - Manage memories easily

### 🔍 Phase 3A: Knowledge Base
- 📄 **Document Support** - TXT, MD, DOCX, PDF
- 🧩 **Smart Chunking** - Overlapping text blocks
- 🔎 **Vector Search** - Semantic similarity
- 💾 **Persistent Store** - Survives app restart

---

## 🎯 Key Commands

### Development
```bash
# Run tests
python test_phase2_3a.py

# Start server
python web/app.py

# Check syntax
python -m py_compile web/app.py web/memory_manager.py web/knowledge_base.py
```

### Using Memory (Python)
```python
from web.memory_manager import MemoryManager

mm = MemoryManager()
mm.add_memory("I like Python programming", category="preference")
results = mm.search_memories("Python")
context = mm.get_context_string(user_input)
```

### Using Knowledge Base (Python)
```python
from web.knowledge_base import KnowledgeBase

kb = KnowledgeBase()
kb.scan_directory("path/to/docs")
results = kb.search("relevant topic", top_k=3)
stats = kb.get_stats()
```

---

## 🔧 Configuration

### Optional: Enable Vector Search
```bash
# Windows
set GEMINI_API_KEY=sk-xxxxxxxxxxxxx

# Linux/Mac
export GEMINI_API_KEY=sk-xxxxxxxxxxxxx

# Then restart server
python web/app.py
```

Without this: System uses zero vectors (still works, just less intelligent)

### Install Optional File Support
```bash
pip install python-docx PyPDF2
```

---

## 📂 Where is Everything?

```
Koto/
├── web/
│   ├── app.py                    # Flask server
│   ├── memory_manager.py         # NEW: Memory system
│   ├── knowledge_base.py         # REVISED: Vector KB
│   ├── templates/
│   │   └── index.html            # UPDATED: UI
│   └── static/
│       ├── css/style.css         # UPDATED: Styles
│       └── js/app.js             # UPDATED: Frontend logic
│
├── config/
│   └── memory.json               # NEW: Your memories (auto-created)
│
├── workspace/knowledge_base/
│   ├── index.json                # NEW: Document metadata
│   └── chunks.json               # NEW: Vector chunks
│
├── test_phase2_3a.py             # NEW: Integration test
├── STATUS.md                      # NEW: Status report
├── FEATURES_QUICK_REFERENCE.md   # NEW: Feature guide
└── IMPLEMENTATION_CHECKLIST.md   # NEW: Checklist
```

---

## ❓ FAQ

### Q: Do I need to set GEMINI_API_KEY?
**A:** No, it's optional. System works without it (uses zero vectors). With it, vector search is smarter.

### Q: Where are my memories saved?
**A:** `config/memory.json` - Plain JSON file, easy to edit or backup.

### Q: Can I add my own documents to the knowledge base?
**A:** Yes! Use `KnowledgeBase.add_document()` or `scan_directory()`.

### Q: Are my memories sent to the cloud?
**A:** No, they're stored locally in `config/memory.json`.

### Q: Why does the app restart when I edit code?
**A:** Normal development behavior. Production uses a proper WSGI server.

### Q: Can I export my memories?
**A:** Yes! Copy `config/memory.json` to backup or share.

---

## 🐛 Troubleshooting

### Memory Section Doesn't Appear
- [ ] Refresh browser (Ctrl+F5 for hard refresh)
- [ ] Check browser console for errors (F12)
- [ ] Restart Flask server

### Math/Diagrams Not Rendering
- [ ] Check internet (needs CDN for KaTeX/Mermaid)
- [ ] Clear browser cache
- [ ] Try different browser

### Knowledge Base Search Returns Nothing
- [ ] Add documents first: `kb.scan_directory()`
- [ ] Check `workspace/knowledge_base/` exists
- [ ] View stats: `kb.get_stats()`

### API Errors
- Console shows `[MemoryManager]` or `[KnowledgeBase]` errors?
- Check Flask terminal for stack trace
- Usually just needs server restart

---

## 📊 System Status

| Component | Status | Notes |
|-----------|--------|-------|
| Memory System | ✅ READY | Tested & integrated |
| Knowledge Base | ✅ READY | Vector search enabled |
| Frontend | ✅ READY | All markdown features |
| Artifacts Panel | ✅ READY | Code preview/edit |
| Integration | ✅ READY | Phase 2+3A working |

---

## 🚀 What's Next?

After Phase 1-3A, the roadmap includes:

- **Phase 4** - Agent Planning (smart task execution)
- **Phase 2B-D** - Memory system enhancements
- **Phase 5-10** - Advanced features (TBD)

---

## 💬 Usage Tips

### Getting the Most from Memory
1. Store unique information regularly
2. Use consistent categories
3. AI will reference relevant memories automatically

### Getting the Most from KB
1. Organize documents logically
2. Use descriptive file names
3. Chunk size is automatic (500 chars)

### Getting the Most from Markdown
1. Use math for scientific content: `$formula$`
2. Use diagrams for explanations: Mermaid
3. Use tables for structured data
4. Use artifacts for long code blocks

---

## 📞 Support Resources

1. **Quick Reference**: `FEATURES_QUICK_REFERENCE.md`
2. **Status Report**: `STATUS.md`
3. **Checklist**: `IMPLEMENTATION_CHECKLIST.md`
4. **Completion Report**: `PHASE_COMPLETION_REPORT.md`

---

## ✅ Verification Checklist

Before reporting issues, verify:

- [ ] Python 3.10+ installed
- [ ] Flask server runs: `python web/app.py`
- [ ] Test passes: `python test_phase2_3a.py`
- [ ] Browser loads http://localhost:5000
- [ ] Memory file exists: `config/memory.json`
- [ ] KB directory exists: `workspace/knowledge_base/`

---

## 🎉 Ready to Use!

When you see "✓ TEST 3 PASSED: Integration working", your Koto is ready to rock.

**Enjoy the enhanced experience with memory, knowledge base, and advanced markdown!**

---

**Version**: Phase 3A Complete  
**Last Updated**: Today  
**Status**: ✅ Production Ready

---

Need help? Check the documentation files in the repo root!
