#!/usr/bin/env python3
"""SlothSync Classifier - Uses local Gemma 2B to classify files.

This module is the "brain" of SlothSync. It takes a file path and uses
the local Ollama Gemma 2B model to determine:
  1. What category the file belongs to (invoice, receipt, screenshot, etc.)
  2. A confidence score (0.0 = unsure, 1.0 = very sure)
  3. A standardized filename format: YYYY-MM-DD_[Category]_[Descriptor].[ext]

The prompt is engineered to force strict JSON output with no markdown,
making it easy to parse in the main daemon.
"""

import json
import ollama
from datetime import date


# ── Category Mapping ─────────────────────────────────────────────────────
# Maps the AI's category name to actual destination folder paths.
CATEGORIES = {
    "invoice":        "Documents/Invoices",
    "receipt":        "Documents/Invoices",
    "report":         "Documents/Reports",
    "screenshot":     "Pictures/Screenshots",
    "photo":          "Pictures/Screenshots",
    "archive":        "Archives",
    "download":       "Archives",
    "unknown":        "Documents/General",
}


# ── Classification Function ─────────────────────────────────────────────
def classify_file(file_path: str, ollama_model: str = "gemma2:2b") -> dict:
    """Classify a file using local Gemma 2B via Ollama.

    Args:
        file_path: Full path to the file (e.g. ~/Downloads/receipt.pdf)
        ollama_model: Name of the Gemma model to use (default: gemma2:2b)

    Returns:
        dict with keys: category, confidence, suggested_name
        Example: {"category": "receipt", "confidence": 0.95, "suggested_name": "2026-10-21_Receipts_grocery_shopping.pdf"}
    """

    # ── Extract filename components ─────────────────────────────────────
    # Get just the filename from the full path
    filename = file_path.rstrip("/").split("/")[-1]

    # Separate name and extension
    if "." in filename:
        name_part, ext = filename.rsplit(".", 1)
        ext = "." + ext  # re-add the dot
    else:
        name_part = filename
        ext = ""

    today = date.today().isoformat()  # YYYY-MM-DD format

    # ── Build the Prompt ────────────────────────────────────────────────
    # The prompt is carefully designed to:
    # - Specify exact output keys (category, confidence, suggested_name)
    # - Force deterministic output with temperature: 0.0
    # - Prevent markdown wrapping by stating "OUTPUT ONLY JSON"
    # - Provide clear examples of the suggested_name format
    prompt = f"""You are SlothSync, an offline file organization assistant.

Given a filename: "{filename}"

Classify this file into EXACTLY one of these categories:
- "invoice"  (financial receipts, bills, tax documents)
- "receipt"  (shopping receipts, restaurant checks)
- "report"   (documents, analysis reports, meeting notes)
- "screenshot" (screen captures, UI mockups)
- "photo"    (image files, pictures)
- "archive"  (zips, old backups, installers)
- "unknown"  (everything else)

Also generate a standardized filename in this format:
YYYY-MM-DD_[Category]_[Descriptor].[ext]

where:
- YYYY-MM-DD = today's date ({today})
- Category = one of the categories listed above
- Descriptor = 3-word max description extracted from the filename
- [ext] = original file extension (keep it CRITICAL)

CRITICAL INSTRUCTIONS:
1. Output NOTHING but a valid JSON object - no markdown, no explanations, no code blocks.
2. The JSON must have exactly these 3 keys: "category", "confidence", "suggested_name"
3. confidence must be a number between 0.0 and 1.0
4. suggested_name must follow the exact format: YYYY-MM-DD_[Category]_[Descriptor].[ext]

Example good output:
{{
  "category": "receipt",
  "confidence": 0.97,
  "suggested_name": "2026-10-21_Receipts_grocery_shopping_receipt.pdf"
}}

Example bad output (do NOT do this):
- Do NOT wrap in triple backticks ```json
- Do NOT add "Here is the classification:"
- Do NOT include extra keys like "reason" or "explanation"

Now classify the file and output ONLY the JSON:"""

    # ── Call Ollama API ───────────────────────────────────────────────
    try:
        response = ollama.chat(
            model=ollama_model,
            messages=[{"role": "user", "content": prompt}],
            options={"temperature": 0.0}  # Deterministic = same output every time
        )

        # Extract the model's response text
        raw_text = response["message"]["content"].strip()

        # ── Strip potential markdown code blocks ────────────────────────
        # Some models may wrap JSON in ```json ... ``` - handle that gracefully
        if raw_text.startswith("```"):
            lines = raw_text.split("\n")
            # Remove first and last lines (the ``` markers)
            raw_text = "\n".join(lines[1:-1]).strip()

        # ── Parse JSON ──────────────────────────────────────────────────
        try:
            result = json.loads(raw_text)
        except json.JSONDecodeError as e:
            print(f"⚠️ JSON parse error: {e}")
            print(f"   Raw response was: {raw_text[:300]}")
            return _fallback_classification(filename, ext, today)

        # ── Validate and normalize the result ───────────────────────────
        # Ensure category is one we recognize
        category = result.get("category", "unknown")
        if category not in CATEGORIES:
            category = "unknown"

        # Ensure confidence is a float between 0 and 1
        try:
            confidence = float(result.get("confidence", 0.5))
            if confidence < 0: confidence = 0.0
            if confidence > 1: confidence = 1.0
        except (ValueError, TypeError):
            confidence = 0.5

        # Ensure suggested_name exists and has right format
        suggested_name = result.get("suggested_name")
        if not suggested_name:
            suggested_name = _generate_default_name(today, category, name_part, ext)

        return {
            "category": category,
            "confidence": round(confidence, 2),
            "suggested_name": suggested_name
        }

    except ollama.ResponseError as e:
        # Ollama-specific errors (model not found, server not running, etc.)
        print(f"❌ Ollama error: {e}")
        return _fallback_classification(filename, ext, today)

    except Exception as e:
        # Catch-all for unexpected errors
        print(f"❌ Unexpected classification error: {type(e).__name__}: {e}")
        return _fallback_classification(filename, ext, today)


# ── Fallback Classification ─────────────────────────────────────────────
def _fallback_classification(filename: str, ext: str, today: str) -> dict:
    """Fallback when Ollama fails - uses simple heuristic rules."""

    # Simple keyword-based classification as fallback
    lower = filename.lower()

    if any(kw in lower for kw in ["invoice", "bill", "tax", "payment"]):
        category = "invoice"
    elif any(kw in lower for kw in ["receipt", "shopping", "store"]):
        category = "receipt"
    elif any(kw in lower for kw in ["report", "analysis", "summary"]):
        category = "report"
    elif any(kw in lower for kw in ["screen", "screenshot", "capture"]):
        category = "screenshot"
    elif any(kw in lower for kw in ["photo", "image", "picture", "png", "jpg"]):
        category = "photo"
    elif any(kw in lower for kw in ["zip", "rar", "backup", "old"]):
        category = "archive"
    else:
        category = "unknown"

    suggested_name = f"{today}_{category}_{filename}{ext}"
    return {
        "category": category,
        "confidence": 0.3,  # Low confidence for fallback
        "suggested_name": suggested_name
    }


def _generate_default_name(today: str, category: str, name_part: str, ext: str) -> str:
    """Generate a default suggested name when AI doesn't provide one."""

    # Use first few words from filename as descriptor
    words = name_part.split()
    descriptor = words[0] if words else "file"
    # Take max 3 words
    descriptor = " ".join(words[:3])

    return f"{today}_{category}_{descriptor}{ext}"


# ── CLI Test Entry Point ────────────────────────────────────────────────
if __name__ == "__main__":
    """Quick test: classify a sample file when run directly."""

    import sys

    # Use first CLI arg as file path, or default test file
    test_file = sys.argv[1] if len(sys.argv) > 1 else None

    if test_file:
        # Expand ~ to home directory if present
        if test_file.startswith("~"):
            import os
            test_file = os.path.expanduser(test_file)

        # Check file exists (optional - we'll try anyway)
        result = classify_file(test_file)
        print("\n=== Classification Result ===")
        print(json.dumps(result, indent=2))
    else:
        # Demo with a few example filenames
        test_files = [
            "receipt_grocery_store01.pdf",
            "screenshot_screen_capture_03.png",
            "project_report_q3_2026.docx",
        ]

        print("=== Sample Classifications ===\n")
        for tf in test_files:
            result = classify_file(tf)
            print(f"File: {tf}")
            print(f"  → Category: {result['category']}")
            print(f"  → Confidence: {result['confidence']}")
            print(f"  → Suggested Name: {result['suggested_name']}")
            print()