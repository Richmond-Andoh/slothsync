# SlothSync

**The Zero-Touch Offline Desktop & Inbox Tidier**

[![Hacktoberfest](https://img.shields.io/badge/Hacktoberfest-Open--Source--AI--Challenge-orange.svg)](https://hacktoberfest.dev/)
[![PRD](https://img.shields.io/badge/PRD-Phase--1--8-blue.svg)](PRD.md)

## 🦥 The Sloth Philosophy

> "Conserve your energy. Let automated offline AI do the work."

SlothSync is a lightweight desktop daemon that automatically inspects, categorizes, renames, and moves files into clean folder structures using **local open-weight AI models** — all while you relax.

**Key Value Proposition:**
- 🏠 **100% Local & Private:** Sensitive documents never leave your machine
- 💰 **Zero Recurring Cost:** Free forever on standard consumer hardware
- 📡 **Offline Reliable:** Operates without active internet connection

## 📋 Problem & Solution

**Problem:** Digital clutter wastes time and mental bandwidth. Manual file sorting is tedious, and cloud-based tools raise privacy risks.

**Solution:** SlothSync — an autonomous daemon running entirely offline using **Google Gemma-2** via **Ollama**. It automatically sorts files into standard folder schemas while generating daily activity summaries.

## 🛠️ Quick Start

### Prerequisites

1. **Python 3.10+**
2. **Ollama** installed from: [ollama.ai](https://ollama.ai)
3. **Gemma 2B model** pulled:

```bash
ollama pull gemma2:2b  # ~1.6GB
```

### Installation (Choose One Method)

---

### Option 1: Rich CLI (Recommended)

```bash
# 1. Clone the repo
git clone https://github.com/Richmond-Andoh/slothsync.git
cd slothsync

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/Mac: source venv/bin/activate
# Windows: venv\Scripts\activate

# 3. Install dependencies
pip install watchdog ollama pypdf rich

# 4. Run SlothSync
python3 daemon.py              # Real mode - actually moves files
python3 daemon.py --dry-run    # Preview mode - shows what would happen
```

### Option 2: Streamlit Web Dashboard

```bash
# Same steps 1-3 as above, then:
streamlit run streamlit_app.py
# → Opens at http://localhost:8501 in your browser
```

### Option 3: PyInstaller Executable (No Python Needed!)

```bash
# The executable is already built in dist/SlothSync
# Just download and run - no Python or venv required!

# Linux:
./dist/SlothSync

# Or double-click (Windows/macOS - separate builds)
```

> ⚠️ **All methods require:** Ollama + `gemma2:2b` model installed locally

## 📂 How It Works

### Directory Watcher

- Monitors `~/Downloads` (or custom directory) for new files
- **3-second debounce** after file write completes (prevents processing partial downloads)
- Uses `watchdog` library for efficient file monitoring

### Classification Engine

- Uses **Gemma 2B** via local Ollama API
- Strictly outputs **JSON** with: `category`, `confidence`, `suggested_name`
- `temperature: 0.0` for deterministic output
- Prompt-engineered to force valid JSON output (no markdown wrapping)

### File Routing

Files are automatically moved to standard directories:

| AI Category | Destination Folder |
|-------------|-------------------|
| `invoice` / `receipt` | `~/Documents/Invoices/` |
| `report` | `~/Documents/Reports/` |
| `screenshot` / `photo` | `~/Pictures/Screenshots/` |
| `archive` | `~/Archives/` |
| `unknown` | `~/Documents/General/` |

### Conflict Resolution

If a filename collision occurs, SlothSync appends `_v1`, `_v2`, etc. **Never** overwrites existing files silently.

### Dry-Run Mode

```bash
python3 daemon.py --dry-run
```

Previews all proposed file moves **without executing them**. Safe to test before running for real.

### History Logging

All file movements are logged to `~/.slothsync/history.json` with:
- Timestamp, original path, category, suggested name
- Confidence score, success/failure status
- Daily summaries: *"SlothSync tidied 18 files today while you relaxed."*

## 📦 What's Included

| File/Folder | Description |
|-------------|-------------|
| `classifier.py` | Gemma 2B file classifier - strict JSON output |
| `daemon.py` | Main Rich CLI daemon - watchdog + routing + history |
| `streamlit_app.py` | Streamlit web dashboard - browser-based UI |
| `dist/SlothSync` | PyInstaller executable - run without Python |
| `.gitignore` | Excludes venv/, __pycache__/, *.db |
| `venv/` | Python virtual environment (27 packages) |
| `README.md` | This file |

## 🐛 Troubleshooting

### "Ollama not running"

Start Ollama:
```bash
ollama serve
# Then: ollama pull gemma2:2b
```

### "Module not found"

Reinstall dependencies:
```bash
pip install --upgrade watchdog ollama pypdf rich
```

### "File not moving"

- Ensure `--dry-run` is NOT enabled if you want actual moves
- Check `~/Documents/Invoices/`, `~/Documents/Reports/`, etc. for destination folders
- History log: `~/.slothsync/history.json`

### "Classification seems wrong"

The AI classifies based on filename keywords. Rename files with descriptive terms, or use `--dry-run` to see what the AI sees.

## 🏆 Hacktoberfest

This project was built for the **Hacktoberfest Open-Source AI Challenge — Week 3** (*Theme: Slow and Steady*).

**Target Categories:**
- 🥉 **Best Use of Gemma** ($200)
- 🥇 **Overall Winner** ($250)

**To Submit:**
1. Fork this repo
2. Make improvements
3. Submit via Hacktoberfest
4. Write DEV.to post with `#devchallenge` `#hf26challenge` before Oct 25, 11:59 PM PDT

## 📄 License

MIT License - free for personal and commercial use. Attribution appreciated.

---

**Built with ❤️ using open-source AI (Gemma 2B via Ollama)**

*Your files never leave your machine. Your privacy is protected. No recurring costs.*