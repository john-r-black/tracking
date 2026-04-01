#!/usr/bin/env python3
"""
split_issues.py — Split 05_OPEN_ISSUES.md into three files:
  - 05_OPEN_ISSUES.md       (active issues)
  - 05A_RESOLVED_ISSUES.md  (resolved/closed — reference only)
  - 05B_DEFERRED_ISSUES.md  (not pursuing — reference only)

Usage:
    python3 split_issues.py [--dir .] [--dry-run]
    python3 split_issues.py --defer 2,4,6 --resolve 25,27,28 [--dir .] [--dry-run]

The --defer and --resolve flags change issue statuses before splitting.
Without flags, the script splits based on existing statuses.
"""

import re
import sys
from pathlib import Path
from datetime import datetime

RESOLVED_STATUSES = ["RESOLVED", "PERMANENTLY CLOSED"]
DEFERRED_STATUSES = ["DEFERRED"]


def is_issue_header(line):
    m = re.match(r'^(?:\*\*|### )ISSUE-(\d+)', line.strip())
    return int(m.group(1)) if m else None


def is_separator(line):
    return line.strip() == '---'


def get_status_line_index(lines):
    for i, line in enumerate(lines):
        if '**Status**' in line:
            return i
    return None


def get_status_text(lines):
    idx = get_status_line_index(lines)
    return lines[idx] if idx is not None else None


def classify_status(status_line):
    if not status_line:
        return 'open'
    if "PARTIALLY RESOLVED" in status_line or "SUBSTANTIALLY RESOLVED" in status_line:
        return 'open'
    for s in RESOLVED_STATUSES:
        if s in status_line:
            return 'resolved'
    for s in DEFERRED_STATUSES:
        if s in status_line:
            return 'deferred'
    return 'open'


def get_issue_title(header_line):
    title = header_line.strip()
    title = title.replace('### ', '').replace('**', '')
    title = re.sub(r'^ISSUE-\d+:\s*', '', title)
    title = re.sub(r'\s*—\s*RESOLVED.*$', '', title)
    title = re.sub(r'\s*—\s*PERMANENTLY CLOSED.*$', '', title)
    title = re.sub(r'\s*—\s*DEFERRED.*$', '', title)
    return title.strip()


def is_existing_stub(block):
    if block['type'] != 'issue':
        return False
    text = ''.join(block['lines']).strip()
    return ('(see 05A_RESOLVED_ISSUES.md)' in text or
            '(see 05B_DEFERRED_ISSUES.md)' in text)


def parse_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        all_lines = f.readlines()

    blocks = []
    current = {'type': 'preamble', 'lines': [], 'issue_num': None, 'category': 'open', 'title': None}

    for line in all_lines:
        issue_num = is_issue_header(line)
        if issue_num:
            if current['lines']:
                blocks.append(current)
            current = {
                'type': 'issue',
                'lines': [line],
                'issue_num': issue_num,
                'category': 'open',
                'title': get_issue_title(line),
            }
        elif is_separator(line):
            if current['lines']:
                blocks.append(current)
            blocks.append({'type': 'separator', 'lines': [line],
                           'issue_num': None, 'category': 'open', 'title': None})
            current = {'type': 'preamble', 'lines': [],
                       'issue_num': None, 'category': 'open', 'title': None}
        else:
            current['lines'].append(line)

    if current['lines']:
        blocks.append(current)

    for block in blocks:
        if block['type'] == 'issue':
            status = get_status_text(block['lines'])
            block['category'] = classify_status(status)

    return blocks


def update_status(block, new_category):
    idx = get_status_line_index(block['lines'])
    if idx is None:
        return
    if new_category == 'deferred':
        block['lines'][idx] = "- **Status**: DEFERRED — moved to monitoring/not-pursuing list\n"
    elif new_category == 'resolved':
        block['lines'][idx] = "- **Status**: RESOLVED — documented; no further action required\n"
    block['category'] = new_category


def make_stub(block):
    title = block['title']
    num = block['issue_num']
    if block['category'] == 'resolved':
        return f"**ISSUE-{num}**: {title} — **RESOLVED** (see 05A_RESOLVED_ISSUES.md)\n"
    else:
        return f"**ISSUE-{num}**: {title} — **DEFERRED** (see 05B_DEFERRED_ISSUES.md)\n"


def build_open_file(blocks, today):
    lines = [f"*Last updated: {today} — Resolved issues in 05A; deferred issues in 05B*\n"]
    new_stubs = []

    for block in blocks:
        if is_existing_stub(block):
            for line in block['lines']:
                lines.append(line)
            continue

        if block['type'] == 'issue':
            if block['category'] == 'open':
                for line in block['lines']:
                    lines.append(line)
            else:
                new_stubs.append(make_stub(block))
        elif block['type'] == 'separator':
            lines.append('\n---\n\n')
        elif block['type'] == 'preamble':
            for line in block['lines']:
                if line.startswith('*Last updated:'):
                    continue
                lines.append(line)

    # Append stubs
    if new_stubs:
        lines.append('\n---\n\n')
        lines.append('## Resolved & Deferred Issues Index\n\n')
        lines.append('*Full details in 05A (resolved) and 05B (deferred) — not loaded into analysis conversations.*\n\n')
        new_stubs.sort(key=lambda s: int(re.search(r'ISSUE-(\d+)', s).group(1)))
        for stub in new_stubs:
            lines.append(stub)
            lines.append('\n')

    return ''.join(lines)


def build_archive(blocks, today, category, title, description):
    lines = [f"*Last updated: {today} — Split from 05_OPEN_ISSUES.md*\n"]
    lines.append(f"# Black Land Project — {title}\n\n")
    lines.append(f"*{description}*\n\n")

    issues = sorted(
        [b for b in blocks if b['type'] == 'issue' and b['category'] == category and not is_existing_stub(b)],
        key=lambda b: b['issue_num']
    )

    for block in issues:
        lines.append('---\n\n')
        for line in block['lines']:
            lines.append(line)
        lines.append('\n')

    return ''.join(lines)


def merge_archive(existing_path, new_content, today):
    if not existing_path.exists():
        return new_content

    existing = existing_path.read_text(encoding='utf-8')

    existing_nums = set()
    for m in re.finditer(r'(?:^|\n)(?:\*\*|### )ISSUE-(\d+)', existing):
        existing_nums.add(int(m.group(1)))

    # Extract new issues not already in archive
    new_issues = []
    current_lines = []
    current_num = None
    in_issue = False

    for line in new_content.split('\n'):
        num_match = re.match(r'^(?:\*\*|### )ISSUE-(\d+)', line.strip())
        if num_match:
            if in_issue and current_num and current_num not in existing_nums:
                new_issues.append((current_num, '\n'.join(current_lines)))
            current_lines = [line]
            current_num = int(num_match.group(1))
            in_issue = True
        elif line.strip() == '---' and in_issue:
            if current_num and current_num not in existing_nums:
                new_issues.append((current_num, '\n'.join(current_lines)))
            current_lines = []
            in_issue = False
            current_num = None
        elif in_issue:
            current_lines.append(line)

    if in_issue and current_num and current_num not in existing_nums:
        new_issues.append((current_num, '\n'.join(current_lines)))

    if not new_issues:
        # Just update timestamp
        return re.sub(r'^\*Last updated:.*?\*',
                      f'*Last updated: {today} — Updated*', existing, count=1)

    result = re.sub(r'^\*Last updated:.*?\*',
                    f'*Last updated: {today} — Updated*', existing, count=1)

    for num, text in sorted(new_issues, key=lambda x: x[0]):
        result += f'\n---\n\n{text}\n'

    return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Split issues into open/resolved/deferred")
    parser.add_argument("--dir", default=".", help="Directory containing tracking files")
    parser.add_argument("--dry-run", action="store_true", help="Show stats without modifying")
    parser.add_argument("--defer", type=str, default="",
                        help="Comma-separated issue numbers to defer (e.g., 2,4,6)")
    parser.add_argument("--resolve", type=str, default="",
                        help="Comma-separated issue numbers to resolve (e.g., 25,27)")
    args = parser.parse_args()

    source = Path(args.dir) / "05_OPEN_ISSUES.md"
    if not source.exists():
        print(f"ERROR: {source} not found", file=sys.stderr)
        sys.exit(1)

    today = datetime.now().strftime("%Y-%m-%d")
    blocks = parse_file(source)

    defer_nums = set(int(x) for x in args.defer.split(',') if x.strip()) if args.defer else set()
    resolve_nums = set(int(x) for x in args.resolve.split(',') if x.strip()) if args.resolve else set()

    for block in blocks:
        if block['type'] == 'issue' and not is_existing_stub(block):
            if block['issue_num'] in defer_nums:
                update_status(block, 'deferred')
            elif block['issue_num'] in resolve_nums:
                update_status(block, 'resolved')

    issue_blocks = [b for b in blocks if b['type'] == 'issue' and not is_existing_stub(b)]
    resolved = [b for b in issue_blocks if b['category'] == 'resolved']
    deferred = [b for b in issue_blocks if b['category'] == 'deferred']
    active = [b for b in issue_blocks if b['category'] == 'open']

    print(f"Issues: {len(active)} active, {len(resolved)} resolved, {len(deferred)} deferred")
    print()

    if resolved:
        print("  RESOLVED:")
        for b in sorted(resolved, key=lambda x: x['issue_num']):
            print(f"    → ISSUE-{b['issue_num']:02d}: {b['title']}")
    if deferred:
        print("  DEFERRED:")
        for b in sorted(deferred, key=lambda x: x['issue_num']):
            print(f"    → ISSUE-{b['issue_num']:02d}: {b['title']}")
    print()

    open_content = build_open_file(blocks, today)
    resolved_content = build_archive(blocks, today, 'resolved',
        'Resolved Issues Archive',
        'Fully resolved issues preserved for the record. Do NOT upload to analysis conversations.')
    deferred_content = build_archive(blocks, today, 'deferred',
        'Deferred Issues',
        'Issues that are technically open but not being actively pursued. Do NOT upload to analysis conversations.')

    resolved_path = Path(args.dir) / "05A_RESOLVED_ISSUES.md"
    deferred_path = Path(args.dir) / "05B_DEFERRED_ISSUES.md"

    resolved_content = merge_archive(resolved_path, resolved_content, today)
    deferred_content = merge_archive(deferred_path, deferred_content, today)

    open_bytes = len(open_content.encode('utf-8'))
    original_bytes = source.stat().st_size

    print(f"05 original:     {original_bytes:,} bytes")
    print(f"05 after split:  {open_bytes:,} bytes")
    print(f"Reduction:       {original_bytes - open_bytes:,} bytes ({(original_bytes - open_bytes) / original_bytes * 100:.0f}%)")

    if args.dry_run:
        print("\nDry run. No files modified.")
        return

    source.write_text(open_content, encoding='utf-8')
    resolved_path.write_text(resolved_content, encoding='utf-8')
    deferred_path.write_text(deferred_content, encoding='utf-8')

    print(f"\n✓ {source}")
    print(f"✓ {resolved_path}")
    print(f"✓ {deferred_path}")


if __name__ == "__main__":
    main()
