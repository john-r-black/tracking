#!/usr/bin/env python3
"""
split_issues.py — Split 05_OPEN_ISSUES.md into open and resolved files.

Moves RESOLVED / PERMANENTLY CLOSED issues to 05A_RESOLVED_ISSUES.md,
leaving one-line stubs in 05_OPEN_ISSUES.md.

Usage:
    python3 split_issues.py [--dir ./tracking_files] [--dry-run]
"""

import re
import sys
from pathlib import Path
from datetime import datetime

RESOLVED_STATUSES = [
    "RESOLVED",
    "PERMANENTLY CLOSED",
]


def is_issue_header(line):
    """Check if a line starts an issue block. Returns issue number or None."""
    # Matches: **ISSUE-NN: ... or ### ISSUE-NN: ...
    m = re.match(r'^(?:\*\*|### )ISSUE-(\d+)', line.strip())
    return m.group(1) if m else None


def is_separator(line):
    """Check if a line is a --- separator."""
    return line.strip() == '---'


def get_issue_status(lines):
    """Extract status from an issue block's lines."""
    for line in lines:
        if '**Status**' in line:
            return line
    return None


def is_resolved(status_line):
    """Determine if a status line indicates resolution."""
    if not status_line:
        return False
    # Exclude partial/substantial resolutions — these are still active
    if "PARTIALLY RESOLVED" in status_line or "SUBSTANTIALLY RESOLVED" in status_line:
        return False
    for s in RESOLVED_STATUSES:
        if s in status_line:
            return True
    return False


def get_issue_title(header_line):
    """Extract the issue title from the header line, stripping the ISSUE-NN: prefix."""
    title = header_line.strip()
    title = title.replace('### ', '').replace('**', '')
    # Remove the ISSUE-NN: prefix since make_stub adds it back
    title = re.sub(r'^ISSUE-\d+:\s*', '', title)
    # Strip trailing resolution markers
    title = re.sub(r'\s*—\s*RESOLVED.*$', '', title)
    title = re.sub(r'\s*—\s*PERMANENTLY CLOSED.*$', '', title)
    return title.strip()


def parse_file(filepath):
    """
    Parse 05_OPEN_ISSUES.md into structured blocks.
    
    Returns a list of blocks, where each block is a dict:
    {
        'type': 'preamble' | 'section_header' | 'issue' | 'separator',
        'lines': [...],
        'issue_num': int or None,
        'resolved': bool,
        'title': str or None,
    }
    """
    with open(filepath, 'r', encoding='utf-8') as f:
        all_lines = f.readlines()

    blocks = []
    current_block = {'type': 'preamble', 'lines': [], 'issue_num': None, 'resolved': False, 'title': None}
    in_issue = False

    for line in all_lines:
        issue_num = is_issue_header(line)

        if issue_num:
            # Save previous block
            if current_block['lines']:
                blocks.append(current_block)
            # Start new issue block
            current_block = {
                'type': 'issue',
                'lines': [line],
                'issue_num': int(issue_num),
                'resolved': False,
                'title': get_issue_title(line),
            }
            in_issue = True

        elif is_separator(line):
            # Save current block
            if current_block['lines']:
                blocks.append(current_block)
            # Add separator
            blocks.append({'type': 'separator', 'lines': [line], 'issue_num': None, 'resolved': False, 'title': None})
            # Reset
            current_block = {'type': 'preamble', 'lines': [], 'issue_num': None, 'resolved': False, 'title': None}
            in_issue = False

        else:
            current_block['lines'].append(line)

    # Don't forget the last block
    if current_block['lines']:
        blocks.append(current_block)

    # Now determine resolved status for issue blocks
    for block in blocks:
        if block['type'] == 'issue':
            status_line = get_issue_status(block['lines'])
            block['resolved'] = is_resolved(status_line)

    return blocks


def make_stub(block):
    """Create a one-line stub for a resolved issue."""
    title = block['title']
    return f"**ISSUE-{block['issue_num']}**: {title} — **RESOLVED** (see 05A_RESOLVED_ISSUES.md)\n"


def build_open_file(blocks, today):
    """Build the content of the new 05_OPEN_ISSUES.md."""
    lines = []
    lines.append(f"*Last updated: {today} — Resolved issues moved to 05A_RESOLVED_ISSUES.md*\n")

    # Track if we need to add a resolved stubs section
    resolved_stubs = []

    for block in blocks:
        if block['type'] == 'issue':
            if block['resolved']:
                resolved_stubs.append(make_stub(block))
            else:
                for line in block['lines']:
                    lines.append(line)
        elif block['type'] == 'separator':
            lines.append('\n---\n\n')
        elif block['type'] == 'preamble':
            # Skip old timestamp lines
            for line in block['lines']:
                if line.startswith('*Last updated:'):
                    continue
                # Skip the duplicate title/timestamp that appears on some files
                if line.startswith('# Black Land Project') and any('# Black Land Project' in l for l in lines):
                    continue
                lines.append(line)

    # Append resolved stubs section at the end
    if resolved_stubs:
        lines.append('\n---\n\n')
        lines.append('## Resolved Issues Index\n\n')
        lines.append('*Full details in 05A_RESOLVED_ISSUES.md — not loaded into analysis conversations.*\n\n')
        for stub in sorted(resolved_stubs, key=lambda s: int(re.search(r'ISSUE-(\d+)', s).group(1))):
            lines.append(stub)
            lines.append('\n')

    return ''.join(lines)


def build_resolved_file(blocks, today):
    """Build the content of 05A_RESOLVED_ISSUES.md."""
    lines = []
    lines.append(f"*Last updated: {today} — Split from 05_OPEN_ISSUES.md*\n")
    lines.append("# Black Land Project — Resolved Issues Archive\n\n")
    lines.append("*This file contains fully resolved issues preserved for the historical record. ")
    lines.append("Do NOT upload this file to analysis conversations — it is reference only.*\n\n")

    for block in blocks:
        if block['type'] == 'issue' and block['resolved']:
            lines.append('---\n\n')
            for line in block['lines']:
                lines.append(line)
            lines.append('\n')

    return ''.join(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Split resolved issues into archive file")
    parser.add_argument("--dir", default=".", help="Directory containing tracking files")
    parser.add_argument("--dry-run", action="store_true", help="Show stats without modifying files")
    args = parser.parse_args()

    source = Path(args.dir) / "05_OPEN_ISSUES.md"
    if not source.exists():
        print(f"ERROR: {source} not found", file=sys.stderr)
        sys.exit(1)

    today = datetime.now().strftime("%Y-%m-%d")
    blocks = parse_file(source)

    # Count
    issue_blocks = [b for b in blocks if b['type'] == 'issue']
    resolved = [b for b in issue_blocks if b['resolved']]
    open_issues = [b for b in issue_blocks if not b['resolved']]

    print(f"Total issues found: {len(issue_blocks)}")
    print(f"  Open/active:  {len(open_issues)}")
    print(f"  Resolved:     {len(resolved)}")
    print()

    for b in resolved:
        print(f"  → RESOLVED: ISSUE-{b['issue_num']:02d}: {b['title']}")
    print()

    open_content = build_open_file(blocks, today)
    resolved_content = build_resolved_file(blocks, today)

    open_lines = open_content.count('\n')
    resolved_lines = resolved_content.count('\n')
    original_lines = sum(len(b['lines']) for b in blocks)

    print(f"Original file:    {original_lines} lines, {source.stat().st_size:,} bytes")
    print(f"New open file:    {open_lines} lines, {len(open_content.encode('utf-8')):,} bytes")
    print(f"New resolved file: {resolved_lines} lines, {len(resolved_content.encode('utf-8')):,} bytes")
    print(f"Reduction in open file: {source.stat().st_size - len(open_content.encode('utf-8')):,} bytes")

    if args.dry_run:
        print("\nDry run complete. No files modified.")
        return

    # Write files
    open_path = Path(args.dir) / "05_OPEN_ISSUES.md"
    resolved_path = Path(args.dir) / "05A_RESOLVED_ISSUES.md"

    open_path.write_text(open_content, encoding='utf-8')
    resolved_path.write_text(resolved_content, encoding='utf-8')

    print(f"\n✓ Written: {open_path}")
    print(f"✓ Written: {resolved_path}")
    print(f"\nReview with: git diff")
    print(f"Then commit: git add -A && git commit -m 'split resolved issues to 05A'")


if __name__ == "__main__":
    main()
