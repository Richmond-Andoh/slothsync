#!/usr/bin/env python3
"""SlothSync Daemon - Directory watcher + file router.

SlothSync: The Zero-Touch Offline Desktop & Inbox Tidier

Background process that monitors target directories, classifies files using
local Gemma 2B via Ollama, and automatically organizes them into clean
folder structures while generating daily action summaries.
"""

import sys
import os
import time
import json
import shutil
import argparse
from pathlib import Path
from datetime import datetime

from rich.console import Console
from rich.live import Live
from rich.table import Table
from rich.progress import Progress, TextColumn, BarColumn, TaskID
from rich.panel import Panel
from rich import print as rprint
from watchdog.events import FileSystemEventHandler

# Add project root to path so we can import classifier
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from classifier import classify_file, CATEGORIES, _generate_default_name

# ── Rich Console ─────────────────────────────────────────────────────────
console = Console()

# ── Constants ────────────────────────────────────────────────────────────
# Default target directory - user's Downloads folder
DEFAULT_WATCH_DIR = Path.home() / "Downloads"

# History log path: ~/.slothsync/history.json
HISTORY_PATH = Path.home() / ".slothsync" / "history.json"

# Debounce timer in seconds - wait this long after file stops writing
DEBOUNCE_SECONDS = 3

# ── Category Colors ──────────────────────────────────────────────────────
# Color mapping for categories in the CLI display
CATEGORY_COLORS = {
    "invoice": "green",
    "receipt": "green",
    "report": "blue",
    "screenshot": "magenta",
    "photo": "magenta",
    "archive": "yellow",
    "unknown": "white",
}

# ── History Log Management ───────────────────────────────────────────────
def _ensure_history_dir():
    """Create the .slothsync directory if it doesn't exist."""
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_history():
    """Load the JSON history log from disk."""
    if HISTORY_PATH.exists():
        try:
            with open(HISTORY_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return []
    return []


def _save_history(history):
    """Persist the history log to disk after each operation."""
    _ensure_history_dir()
    with open(HISTORY_PATH, "w") as f:
        json.dump(history, f, indent=2)


def _add_to_history(entry):
    """Add a single entry to the history log and save."""
    history = _load_history()
    history.append(entry)
    # Keep only last 100 entries to prevent unbounded growth
    if len(history) > 100:
        history = history[-100:]
    _save_history(history)


# ── Conflict Resolution ──────────────────────────────────────────────────
def _resolve_destination(category: str) -> Path:
    """Return the absolute path for a given category folder.

    Expands ~ to home directory and creates the folder if it doesn't exist.
    """
    # Map category to folder path
    folder_name = CATEGORIES.get(category, "Documents/General")
    # Convert relative path like "Documents/Invoices" to absolute
    if not os.path.isabs(folder_name):
        folder_path = Path.home() / folder_name
    else:
        folder_path = Path(folder_name)

    # Ensure the directory exists
    folder_path.mkdir(parents=True, exist_ok=True)
    return folder_path


def _resolve_collision(dest_folder: Path, filename: str) -> Path:
    """Handle file name collisions by appending _v1, _v2, etc.

    If dest_folder/file.txt already exists, return:
      - dest_folder/file_v1.txt
    If that also exists, return:
      - dest_folder/file_v2.txt
    And so on. If no collision, return the original path.
    """
    file_path = dest_folder / filename

    if not file_path.exists():
        # No collision - safe to use original name
        return file_path

    # Collision detected - add version counter
    # Split into stem and suffix (extension)
    stem = file_path.stem  # e.g., "file"
    suffix = file_path.suffix  # e.g., ".txt"

    counter = 1
    while True:
        new_name = f"{stem}_v{counter}{suffix}"
        new_path = dest_folder / new_name
        if not new_path.exists():
            return new_path
        counter += 1


# ── File Classification & Routing ────────────────────────────────────────
def classify_and_route(file_path: Path, dry_run: bool = False) -> dict:
    """Classify a file and move it to the correct destination.

    Args:
        file_path: Path object for the file to classify and move
        dry_run: If True, preview the move without actually moving

    Returns:
        dict with: category, suggested_name, success, message
    """
    file_path = Path(file_path).resolve()  # Resolve to absolute path

    # Skip if file no longer exists (race condition)
    if not file_path.exists():
        return {"category": "unknown", "suggested_name": None, "success": False, "message": "File vanished before processing"}

    # Skip if it's a directory (safety check)
    if file_path.is_dir():
        return {"category": "unknown", "suggested_name": None, "success": False, "message": "Path is a directory, not a file"}

    # ── Step 1: Classify the file using Gemma 2B ─────────────────────
    try:
        classification = classify_file(str(file_path))
    except Exception as e:
        return {"category": "unknown", "suggested_name": None, "success": False, "message": f"Classification error: {e}"}

    category = classification["category"]
    confidence = classification["confidence"]
    suggested_name = classification["suggested_name"]

    # ── Step 2: Determine destination folder ──────────────────────────
    dest_folder = _resolve_destination(category)

    # ── Step 3: Resolve filename collision if needed ───────────────────
    # The AI suggests a name, but we need to ensure it doesn't collide
    # with existing files. If collision, add _v1, _v2, etc.

    # Use the AI's suggested name if available and valid, otherwise generate default
    if suggested_name and "_" in suggested_name:
        suggested_filename = suggested_name
    else:
        suggested_filename = _generate_default_name(
            datetime.now().strftime("%Y-%m-%d"),
            category,
            file_path.stem,
            file_path.suffix
        )

    # Handle collision for the suggested name too
    dest_file_path = _resolve_collision(dest_folder, suggested_filename)

    # ── Step 4: Execute or preview the move ───────────────────────────
    if dry_run:
        # Preview mode - just report what WOULD happen
        category_color = CATEGORY_COLORS.get(category, "white")
        return {
            "category": category,
            "suggested_name": suggested_filename,
            "dest_file": str(dest_file_path),
            "success": True,
            "message": f"[DRY-RUN] Would move: {file_path.name} → [{category_color}]{category}[/] {dest_file_path.name}",
            "dry_run": True,
            "category_color": category_color
        }

    # Actual move execution
    try:
        # Move the file - shutil.move is atomic on same filesystem
        shutil.move(str(file_path), str(dest_file_path))

        # ── Step 5: Log the transaction ────────────────────────────────
        entry = {
            "timestamp": datetime.now().isoformat(),
            "original_path": str(file_path),
            "original_name": file_path.name,
            "category": category,
            "suggested_name": suggested_filename,
            "dest_path": str(dest_file_path),
            "confidence": confidence,
            "success": True
        }
        _add_to_history(entry)

        category_color = CATEGORY_COLORS.get(category, "white")
        return {
            "category": category,
            "suggested_name": suggested_filename,
            "dest_file": str(dest_file_path),
            "success": True,
            "message": f"✅ Moved: {file_path.name} → [{category_color}]{category}[/] {dest_file_path.name}",
            "dry_run": False,
            "category_color": category_color
        }

    except Exception as e:
        # Move failed - log the failure
        entry = {
            "timestamp": datetime.now().isoformat(),
            "original_path": str(file_path),
            "original_name": file_path.name,
            "category": category,
            "suggested_name": suggested_filename,
            "dest_path": None,
            "confidence": confidence,
            "success": False,
            "message": f"❌ Move failed: {e}"
        }
        _add_to_history(entry)

        return {
            "category": category,
            "suggested_name": suggested_filename,
            "dest_file": None,
            "success": False,
            "message": f"❌ Move failed: {e}",
            "dry_run": False
        }


# ── Watchdog Event Handler ──────────────────────────────────────────────
class SlothHandler(FileSystemEventHandler):
    """watchdog event handler that debounces file write events."""

    def __init__(self, dry_run: bool = False, watch_dir: Path = DEFAULT_WATCH_DIR):
        super().__init__()
        self.dry_run = dry_run
        self.watch_dir = watch_dir.resolve()
        self.pending = {}  # filename -> timestamp of first event

    def on_created(self, event):
        """Called when a new file or directory is created in watched folder."""
        src_path = Path(event.src_path)
        if src_path.is_file():
            filename = src_path.name
            # Record the time of this event
            # If we've seen this file before, update the timestamp (reset debounce)
            if filename in self.pending:
                self.pending[filename] = time.time()
            else:
                # First time seeing this file
                self.pending[filename] = time.time()

    on_modified = on_created  # Treat modifications same as creation

    def get_pending(self):
        """Return files that have been pending long enough to process.

        Returns list of (filepath, filename) tuples that have exceeded
        the debounce timeout.
        """
        now = time.time()
        ready = []

        # Check which files have waited longer than DEBOUNCE_SECONDS
        finished = []
        for filename, timestamp in list(self.pending.items()):
            if now - timestamp >= DEBOUNCE_SECONDS:
                # Debounce period finished - this file is ready to process
                filepath = self.watch_dir / filename
                if filepath.exists() and filepath.is_file():
                    ready.append((filepath, filename))
                finished.append(filename)

        # Remove processed files from tracking
        for filename in finished:
            del self.pending[filename]

        return ready


# ── History Summary ──────────────────────────────────────────────────────
def _build_history_summary(history):
    """Build a rich Table summarizing classification history.

    Returns a Table with columns: Category, Count, Confidence Avg.
    """
    table = Table(title="📜 SlothSync Activity Log", show_header=True)
    table.add_column("Category", style="cyan", width=15)
    table.add_column("Count", justify="right", width=8)
    table.add_column("Avg Confidence", justify="right", width=14)

    # Count files by category
    category_counts = {}
    category_confidence = {}

    for entry in history:
        cat = entry.get("category", "unknown")
        category_counts[cat] = category_counts.get(cat, 0) + 1
        category_confidence[cat] = category_confidence.get(cat, 0) + entry.get("confidence", 0)

    # Calculate averages and add rows
    for cat, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True):
        avg_conf = category_confidence[cat] / count if count > 0 else 0
        color = CATEGORY_COLORS.get(cat, "white")
        table.add_row(f"[{color}]{cat}[/]", str(count), f"{avg_conf:.2f}")

    return table


def generate_daily_summary(history):
    """Generate a human-readable daily summary from history entries.

    Returns a string like: 'SlothSync tidied 18 files today while you relaxed.'
    """
    from datetime import datetime

    # Filter entries from today
    today = datetime.now().strftime("%Y-%m-%d")
    today_entries = []

    for entry in history:
        entry_date = entry.get("timestamp", "")
        if entry_date.startswith(today):
            today_entries.append(entry)

    if not today_entries:
        return None

    # Count by category
    category_counts = {}
    for entry in today_entries:
        cat = entry.get("category", "unknown")
        category_counts[cat] = category_counts.get(cat, 0) + 1

    total_files = sum(category_counts.values())

    # Build category sentences
    if len(category_counts) == 1:
        # Only one category
        cat = list(category_counts.keys())[0]
        count = category_counts[cat]
        return f"SlothSync tidied {count} file{'s' if count != 1 else ''} today while you relaxed."
    else:
        # Multiple categories - list them
        parts = []
        for cat, count in category_counts.items():
            color = CATEGORY_COLORS.get(cat, "white")
            parts.append(f"[{color}]{count}[/] {cat}")
        categories_str = " + ".join(parts)
        return f"SlothSync organized {total_files} file{'s' if total_files != 1 else ''} ({categories_str}) while you relaxed."


# ── Main Daemon Loop ────────────────────────────────────────────────────
def run_daemon(watch_dir: Path = DEFAULT_WATCH_DIR,
               dry_run: bool = False,
               poll_interval: float = 0.5):
    """Main daemon loop that watches a directory and processes files.

    Uses watchdog library for efficient file monitoring with polling fallback.

    Args:
        watch_dir: Directory to monitor for new files
        dry_run: If True, preview moves without executing them
        poll_interval: How often to check for new files (seconds)
    """

    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    # Ensure watch directory exists
    watch_dir.mkdir(parents=True, exist_ok=True)

    # Initialize history
    history = _load_history()

    # Set up watchdog observer
    event_handler = SlothHandler(dry_run=dry_run, watch_dir=watch_dir)
    observer = Observer()
    observer.schedule(event_handler, str(watch_dir), recursive=False)
    observer.start()

    # Daemon statistics
    total_processed = 0
    total_moved = 0
    total_dry = 0 if dry_run else None

    # Debounce tracking
    debounce_task = None

    # ── Rich Live Display ──────────────────────────────────────────────
    # We use Live to update the terminal in real-time without spamming output
    # The display shows: current file being processed, classification result,
    # and a summary table of recent activity.
    with Live(console=console, refresh_per_second=4) as live:
        try:
            print("🦥 SlothSync Daemon starting...")
            console.print(f"   Watch directory: {watch_dir}", style="dim")
            console.print(f"   Dry-run mode: {'YES' if dry_run else 'NO'}", style="dim")
            console.print(f"   Debounce delay: {DEBOUNCE_SECONDS}s", style="dim")
            console.print()

            # Main loop - check for debounced files periodically
            while True:
                # Get files that have finished their debounce period
                ready_files = event_handler.get_pending()

                # Process each ready file
                for filepath, filename in ready_files:
                    total_processed += 1

                    # Classify and route the file
                    result = classify_and_route(filepath, dry_run=dry_run)

                    # Update statistics
                    if result["success"]:
                        if dry_run:
                            total_dry = total_dry + 1 if total_dry else 1
                        else:
                            total_moved += 1

                    # Add to history (already done inside classify_and_route,
                    # but we also load the updated history for display)
                    history = _load_history()

                    # Update the Live display
                    # Build a summary of what just happened
                    category = result.get("category", "unknown")
                    color = CATEGORY_COLORS.get(category, "white")

                    # Create a nice status panel
                    status_panel = Panel(
                        f"[bold {color}]{category}[/] "
                        f"• {result.get('message', '').strip()}",
                        title="📂 Current Action",
                        style="black",
                        border_style=color,
                        subtitle=f"File: {filepath.name}"
                    )

                    # Also update history summary table
                    summary_table = _build_history_summary(history)

                    # Layout: current action on top, history below
                    live.update(Panel(
                        f"{status_panel}\n\n{summary_table}",
                        title=f"🦥 SlothSync | Processed: {total_processed} | Moved: {total_moved} | Dry-run: {total_dry or 0}",
                        border_style="blue",
                        subtitle="Ctrl+C to stop"
                    ))

                    # Small delay to let the display update
                    time.sleep(0.3)

                # Sleep before next poll cycle
                time.sleep(poll_interval)

                # Periodic cleanup/optimization
                if total_processed % 10 == 0:
                    # Refresh history every 10 files
                    history = _load_history()

        except KeyboardInterrupt:
            # Show daily summary on shutdown
            history = _load_history()
            summary = generate_daily_summary(history)
            if summary:
                console.print(f"\n📊 {summary}", style="green")
            else:
                console.print("\n💤 SlothSync shutting down...", style="yellow")
            observer.stop()

        except Exception as e:
            console.print(f"\n❌ Unexpected error: {e}", style="red")
            observer.stop()

        finally:
            observer.join()


# ── CLI Entry Point ─────────────────────────────────────────────────────
def main():
    """Command-line interface for SlothSync daemon."""

    parser = argparse.ArgumentParser(
        prog="slothsync",
        description="SlothSync: The Zero-Touch Offline Desktop & Inbox Tidier",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument(
        "--dir",
        type=str,
        default=None,
        help="Directory to watch (default: ~/Downloads)"
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview file moves without actually moving anything"
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose output (classification details)"
    )

    args = parser.parse_args()

    # Determine watch directory
    watch_dir = Path(args.dir) if args.dir else DEFAULT_WATCH_DIR

    # Verify directory exists
    if not watch_dir.exists():
        console.print(f"❌ Watch directory does not exist: {watch_dir}", style="red")
        console.print("   Creating it...", style="yellow")
        watch_dir.mkdir(parents=True, exist_ok=True)

    # Print startup banner using rich
    console.print("=" * 60)
    console.print("  SlothSync - The Zero-Touch Offline Desktop & Inbox Tidier")
    console.print("=" * 60)
    console.print()

    # Run the daemon
    run_daemon(watch_dir=watch_dir, dry_run=args.dry_run, poll_interval=0.5)


if __name__ == "__main__":
    main()