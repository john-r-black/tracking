#!/usr/bin/env python3
"""
apply_manifest.py — Black Land Project Change Manifest Applier

Reads a JSON change manifest and applies operations to the six tracking files.
Produces a detailed log of all operations attempted and their outcomes.

Usage:
    python3 apply_manifest.py manifest.json [--dir ./tracking_files] [--dry-run]

Options:
    --dir       Directory containing the tracking files (default: current directory)
    --dry-run   Show what would be done without modifying files
"""

import json
import sys
import os
import re
import shutil
from datetime import datetime
from pathlib import Path

TRACKING_FILES = [
    "01_FAMILY_ENTITY_STRUCTURE.md",
    "02_PROPERTY_INVENTORY.md",
    "03_DEED_CHAIN_SUMMARY.md",
    "04_MINERAL_RIGHTS_TRACKER.md",
    "05_OPEN_ISSUES.md",
    "06_TECHNICAL_SPEC.md",
]

TIMESTAMP_PATTERN = re.compile(r'^\*Last updated:.*?\*', re.DOTALL)


class ManifestError(Exception):
    pass


class OperationResult:
    def __init__(self, filename, op_index, action, description, success, message):
        self.filename = filename
        self.op_index = op_index
        self.action = action
        self.description = description
        self.success = success
        self.message = message

    def __str__(self):
        status = "✓" if self.success else "✗"
        return f"  {status} [{self.action}] {self.description}\n    → {self.message}"


def load_manifest(path):
    """Load and validate the manifest JSON."""
    with open(path, 'r', encoding='utf-8') as f:
        manifest = json.load(f)

    required_keys = ["manifest_version", "batch_id", "date", "files"]
    for key in required_keys:
        if key not in manifest:
            raise ManifestError(f"Missing required key: {key}")

    if manifest["manifest_version"] != "1.0":
        raise ManifestError(f"Unsupported manifest version: {manifest['manifest_version']}")

    for fname in TRACKING_FILES:
        if fname not in manifest["files"]:
            raise ManifestError(f"Missing file entry: {fname}")

    return manifest


def find_unique(content, needle, filename):
    """
    Find a string in content. Returns (start_index, end_index) if found exactly once.
    Raises ManifestError if not found or found multiple times.
    """
    count = content.count(needle)
    if count == 0:
        # Show a preview of what we were looking for
        preview = needle[:120].replace('\n', '\\n')
        raise ManifestError(f"String not found in {filename}: \"{preview}...\"")
    if count > 1:
        preview = needle[:120].replace('\n', '\\n')
        raise ManifestError(
            f"String found {count} times in {filename} (must be unique): \"{preview}...\""
        )
    start = content.index(needle)
    return start, start + len(needle)


def apply_replace(content, op, filename):
    """Apply a replace operation."""
    find_str = op["find"]
    replace_str = op["replace_with"]
    start, end = find_unique(content, find_str, filename)
    return content[:start] + replace_str + content[end:]


def apply_insert_after(content, op, filename):
    """Apply an insert_after operation. Inserts content after the line containing the anchor."""
    anchor = op["anchor"]
    new_content = op["content"]
    start, end = find_unique(content, anchor, filename)

    # Find the end of the line containing the anchor
    line_end = content.find('\n', end)
    if line_end == -1:
        # Anchor is on the last line with no trailing newline
        return content + '\n' + new_content
    else:
        return content[:line_end + 1] + new_content + '\n' + content[line_end + 1:]


def apply_insert_before(content, op, filename):
    """Apply an insert_before operation. Inserts content before the line containing the anchor."""
    anchor = op["anchor"]
    new_content = op["content"]
    start, _ = find_unique(content, anchor, filename)

    # Find the start of the line containing the anchor
    line_start = content.rfind('\n', 0, start)
    if line_start == -1:
        # Anchor is on the first line
        return new_content + '\n' + content
    else:
        return content[:line_start + 1] + new_content + '\n' + content[line_start + 1:]


def update_timestamp(content, date_str, summary, filename):
    """
    Strip ALL *Last updated: ...* blocks from the file and prepend the new one.
    Handles multi-line timestamp blocks and duplicate timestamps from old workflow.
    """
    new_timestamp = f"*Last updated: {date_str} — {summary}*"

    def strip_one_timestamp(text):
        """Remove one *Last updated: ...* block. Returns (modified_text, found)."""
        marker = "*Last updated:"
        idx = text.find(marker)
        if idx == -1:
            return text, False

        # Find the closing * (not part of **)
        pos = idx + len(marker)
        while pos < len(text):
            if text[pos] == '*':
                if pos + 1 < len(text) and text[pos + 1] == '*':
                    pos += 2
                    continue
                if pos > 0 and text[pos - 1] == '*':
                    pos += 1
                    continue
                # Found closing *
                end_pos = pos + 1
                # Skip trailing newlines (up to 1)
                if end_pos < len(text) and text[end_pos] == '\n':
                    end_pos += 1
                return text[:idx] + text[end_pos:], True
            pos += 1

        # Fallback: strip to end of first line
        first_newline = text.find('\n', idx)
        if first_newline == -1:
            return text[:idx], True
        return text[:idx] + text[first_newline + 1:], True

    # Strip all existing timestamp blocks
    found = True
    while found:
        content, found = strip_one_timestamp(content)

    # Remove any leading whitespace/blank lines left behind
    content = content.lstrip('\n')

    return new_timestamp + "\n" + content


def process_file(filename, file_spec, manifest_date, file_dir, dry_run):
    """Process all operations for a single file. Returns list of OperationResult."""
    results = []

    if not file_spec.get("changed", False):
        results.append(OperationResult(
            filename, -1, "skip", "No changes needed", True, "File unchanged"
        ))
        return results

    filepath = Path(file_dir) / filename
    if not filepath.exists():
        results.append(OperationResult(
            filename, -1, "read", "Read file", False, f"File not found: {filepath}"
        ))
        return results

    # Read current content
    content = filepath.read_text(encoding='utf-8')
    original_content = content

    # Apply operations in order
    operations = file_spec.get("operations", [])
    for i, op in enumerate(operations):
        action = op.get("action", "unknown")
        description = op.get("description", f"Operation {i+1}")

        try:
            if action == "replace":
                content = apply_replace(content, op, filename)
                results.append(OperationResult(
                    filename, i, action, description, True, "Replaced successfully"
                ))
            elif action == "insert_after":
                content = apply_insert_after(content, op, filename)
                results.append(OperationResult(
                    filename, i, action, description, True, "Inserted after anchor"
                ))
            elif action == "insert_before":
                content = apply_insert_before(content, op, filename)
                results.append(OperationResult(
                    filename, i, action, description, True, "Inserted before anchor"
                ))
            else:
                results.append(OperationResult(
                    filename, i, action, description, False, f"Unknown action: {action}"
                ))
        except ManifestError as e:
            results.append(OperationResult(
                filename, i, action, description, False, str(e)
            ))

    # Update timestamp
    timestamp_summary = file_spec.get("timestamp_summary")
    if timestamp_summary:
        try:
            content = update_timestamp(content, manifest_date, timestamp_summary, filename)
            results.append(OperationResult(
                filename, -1, "timestamp", "Update timestamp", True,
                f"Set to: {manifest_date} — {timestamp_summary}"
            ))
        except Exception as e:
            results.append(OperationResult(
                filename, -1, "timestamp", "Update timestamp", False, str(e)
            ))

    # Check if anything actually changed
    if content == original_content:
        results.append(OperationResult(
            filename, -1, "verify", "Content check", True,
            "WARNING: File marked as changed but no content differences detected"
        ))
        return results

    # Write (or report for dry-run)
    if dry_run:
        # Count changes
        orig_lines = original_content.splitlines()
        new_lines = content.splitlines()
        results.append(OperationResult(
            filename, -1, "dry-run", "Would write changes", True,
            f"Lines: {len(orig_lines)} → {len(new_lines)} (diff: {len(new_lines) - len(orig_lines):+d})"
        ))
    else:
        # Write updated content (git is the backup)
        filepath.write_text(content, encoding='utf-8')
        results.append(OperationResult(
            filename, -1, "write", "Write file", True,
            f"Written."
        ))

    return results


def strip_all_timestamps(file_dir, dry_run):
    """One-time cleanup: strip all old timestamp blocks and replace with clean single-line."""
    today = datetime.now().strftime("%Y-%m-%d")
    print(f"Stripping legacy timestamp blocks from all tracking files...")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print()

    for fname in TRACKING_FILES:
        filepath = Path(file_dir) / fname
        if not filepath.exists():
            print(f"  ✗ {fname}: not found")
            continue

        content = filepath.read_text(encoding='utf-8')
        original = content

        # Count existing timestamps
        count = content.count("*Last updated:")
        if count == 0:
            print(f"  — {fname}: no timestamps found")
            continue

        # Strip all timestamp blocks
        new_content = update_timestamp(content, today, "Legacy timestamps stripped; git history is the audit trail", fname)

        if new_content == original:
            print(f"  — {fname}: no changes needed")
            continue

        orig_lines = len(original.splitlines())
        new_lines = len(new_content.splitlines())

        if dry_run:
            print(f"  ✓ {fname}: would strip {count} timestamp block(s), "
                  f"lines {orig_lines} → {new_lines} ({new_lines - orig_lines:+d})")
        else:
            backup = filepath.with_suffix('.md.bak')
            shutil.copy2(filepath, backup)
            filepath.write_text(new_content, encoding='utf-8')
            print(f"  ✓ {fname}: stripped {count} timestamp block(s), "
                  f"lines {orig_lines} → {new_lines} ({new_lines - orig_lines:+d}). "
                  f"Backup: {backup.name}")

    print()
    if dry_run:
        print("Dry run complete. No files modified.")
    else:
        print("Done. Review with: git diff")
        print("Then commit: git commit -am 'cleanup: strip legacy timestamp blocks'")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Apply a Black Land Project change manifest")
    parser.add_argument("manifest", nargs="?", help="Path to the manifest JSON file")
    parser.add_argument("--dir", default=".", help="Directory containing tracking files")
    parser.add_argument("--dry-run", action="store_true", help="Show changes without applying")
    parser.add_argument("--strip-timestamps", action="store_true",
                        help="One-time cleanup: strip all old timestamp blocks from all files "
                             "and replace with a clean single-line timestamp. No manifest needed.")
    args = parser.parse_args()

    if args.strip_timestamps:
        strip_all_timestamps(args.dir, args.dry_run)
        sys.exit(0)

    if not args.manifest:
        parser.error("manifest is required unless --strip-timestamps is used")

    # Load manifest
    try:
        manifest = load_manifest(args.manifest)
    except (json.JSONDecodeError, ManifestError) as e:
        print(f"ERROR: Failed to load manifest: {e}", file=sys.stderr)
        sys.exit(1)

    # Print header
    print(f"{'='*60}")
    print(f"Black Land Project — Change Manifest Applier")
    print(f"{'='*60}")
    print(f"Manifest:  {args.manifest}")
    print(f"Batch:     {manifest['batch_id']}")
    print(f"Date:      {manifest['date']}")
    if manifest.get('documents_analyzed'):
        print(f"Documents: {', '.join(manifest['documents_analyzed'])}")
    if manifest.get('batch_summary'):
        print(f"Summary:   {manifest['batch_summary'][:100]}...")
    print(f"Mode:      {'DRY RUN' if args.dry_run else 'LIVE'}")
    print(f"{'='*60}")
    print()

    # Process each file
    all_results = []
    any_failures = False

    for fname in TRACKING_FILES:
        file_spec = manifest["files"][fname]
        print(f"--- {fname} ---")

        results = process_file(fname, file_spec, manifest["date"], args.dir, args.dry_run)
        all_results.extend(results)

        for r in results:
            print(str(r))
            if not r.success:
                any_failures = True

        print()

    # Summary
    total_ops = len([r for r in all_results if r.op_index >= 0])
    success_ops = len([r for r in all_results if r.op_index >= 0 and r.success])
    failed_ops = len([r for r in all_results if r.op_index >= 0 and not r.success])
    files_changed = len([f for f in TRACKING_FILES if manifest["files"][f].get("changed", False)])

    print(f"{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Files changed:     {files_changed} / 6")
    print(f"Operations:        {success_ops} succeeded, {failed_ops} failed (of {total_ops} total)")

    if any_failures:
        print()
        print("⚠️  SOME OPERATIONS FAILED. Review the log above.")
        print("   Failed operations were skipped — the file may be partially updated.")
        print("   Fix the manifest and re-run, or apply failed changes manually.")
        sys.exit(1)
    elif not args.dry_run:
        print()
        print("✓ All operations applied successfully.")
        print("  Review changes with: git diff")
    else:
        print()
        print("Dry run complete. No files were modified.")


if __name__ == "__main__":
    main()