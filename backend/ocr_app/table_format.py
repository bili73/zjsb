"""Lossless OTSL grid decoding for Paddle's six structural tokens.

Token semantics: PaddleX paddleocr_vl/uilts.py (Apache-2.0).
Unlike upstream width repair, no recognized cell is truncated.
"""
import html
import re

TAG = re.compile(r'<(fcel|ecel|lcel|ucel|xcel|nl)>')


def table_html(text):
    """Return existing text or decoded HTML; reject inconsistent OTSL topology."""
    stripped = text.strip()
    if not re.match(r'^<(?:fcel|ecel)>', stripped):
        return text
    matches = list(TAG.finditer(stripped))
    rows, row = [], []
    for index, match in enumerate(matches):
        tag = match[1]
        content = stripped[match.end():matches[index + 1].start() if index + 1 < len(matches) else len(stripped)].strip()
        if tag == 'nl':
            if content:
                raise ValueError('OTSL_NON_CELL_TEXT')
            if row:
                rows.append(row)
                row = []
        else:
            if tag != 'fcel' and content:
                raise ValueError('OTSL_NON_CELL_TEXT')
            row.append((tag, content))
    if row:
        rows.append(row)
    width = max((len(r) for r in rows), default=0)
    if not width or len(rows) > 1000 or width > 200 or len(rows) * width > 10000:
        raise ValueError('OTSL_GRID_LIMIT')
    grid = [[None] * width for _ in rows]
    cells = {}
    for r, tokens in enumerate(rows):
        for c in range(width):
            tag, value = tokens[c] if c < len(tokens) else ('ecel', '')
            if tag in {'fcel', 'ecel'}:
                owner = (r, c)
                cells[owner] = dict(text=value, positions=[])
            elif tag == 'lcel':
                owner = grid[r][c - 1] if c else None
            elif tag == 'ucel':
                owner = grid[r - 1][c] if r else None
            else:
                left = grid[r][c - 1] if c else None
                above = grid[r - 1][c] if r else None
                owner = left if left == above else None
            if owner is None:
                raise ValueError('OTSL_ORPHAN_SPAN')
            grid[r][c] = owner
            cells[owner]['positions'].append((r, c))
    rendered = [[] for _ in rows]
    for (r, c), cell in cells.items():
        height = max(p[0] for p in cell['positions']) - r + 1
        length = max(p[1] for p in cell['positions']) - c + 1
        if len(cell['positions']) != height * length or any(grid[i][j] != (r, c)
                for i in range(r, r + height) for j in range(c, c + length)):
            raise ValueError('OTSL_NON_RECTANGULAR_SPAN')
        attrs = (f' rowspan="{height}"' if height > 1 else '') + (f' colspan="{length}"' if length > 1 else '')
        rendered[r].append(f'<td{attrs}>{html.escape(cell["text"])}</td>')
    return '<table>' + ''.join('<tr>' + ''.join(r) + '</tr>' for r in rendered) + '</table>'
