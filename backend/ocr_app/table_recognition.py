"""Photo-table qualification helpers. No model loading or application state."""
from html.parser import HTMLParser
import math
import re

from .table_format import table_html

MAX_ROWS, MAX_COLUMNS, MAX_CELLS = 1000, 200, 10000


class _TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tables, self.rows = [], None
        self.row = self.cell = None

    def handle_starttag(self, tag, attrs):
        if tag == 'table':
            if self.rows is not None:
                raise ValueError('TABLE_NESTED')
            self.rows = []
        elif tag == 'tr' and self.rows is not None:
            if self.row is not None:
                raise ValueError('TABLE_UNCLOSED_ROW')
            self.row = []
        elif tag in {'td', 'th'} and self.rows is not None:
            if self.row is None or self.cell is not None:
                raise ValueError('TABLE_INVALID_CELL')
            attrs = dict(attrs)
            spans = [int(attrs.get(key, '1')) for key in ('rowspan', 'colspan')]
            if not 1 <= spans[0] <= MAX_ROWS or not 1 <= spans[1] <= MAX_COLUMNS:
                raise ValueError('TABLE_INVALID_SPAN')
            self.cell = dict(text='', rowspan=spans[0], colspan=spans[1], header=tag == 'th')
        elif tag == 'br' and self.cell is not None:
            self.cell['text'] += '\n'

    def handle_endtag(self, tag):
        if tag in {'td', 'th'} and self.rows is not None:
            if self.cell is None or self.row is None:
                raise ValueError('TABLE_INVALID_CELL')
            self.row.append(self.cell)
            self.cell = None
        elif tag == 'tr' and self.rows is not None:
            if self.cell is not None or self.row is None:
                raise ValueError('TABLE_UNCLOSED_CELL')
            self.rows.append(self.row)
            self.row = None
        elif tag == 'table':
            if self.rows is None or self.row is not None or self.cell is not None:
                raise ValueError('TABLE_UNCLOSED_ROW')
            self.tables.append(self.rows)
            self.rows = None

    def handle_data(self, data):
        if self.cell is not None:
            self.cell['text'] += data


def decode_table_output(raw):
    """Preserve each grid and explicit spans; never render OCR HTML in a browser."""
    if not isinstance(raw, str) or len(raw) > 2_000_000:
        raise ValueError('TABLE_OUTPUT_LIMIT')
    raw = re.sub(r'^```(?:html)?\s*|\s*```$', '', raw.strip())
    parser = _TableParser()
    parser.feed(table_html(raw))
    parser.close()
    if parser.rows is not None or not parser.tables:
        raise ValueError('TABLE_INCOMPLETE')
    tables = []
    for source in parser.tables:
        occupied, values, merges, widths = set(), {}, [], []
        header_rows = 0
        for r, row in enumerate(source):
            if r >= MAX_ROWS:
                raise ValueError('TABLE_GRID_LIMIT')
            if r == header_rows and row and all(cell['header'] for cell in row):
                header_rows += 1
            c = 0
            for cell in row:
                while (r, c) in occupied:
                    c += 1
                height, width = cell['rowspan'], cell['colspan']
                if r + height > len(source) or c + width > MAX_COLUMNS:
                    raise ValueError('TABLE_INVALID_SPAN')
                positions = {(y, x) for y in range(r, r + height) for x in range(c, c + width)}
                if positions & occupied:
                    raise ValueError('TABLE_OVERLAPPING_SPAN')
                occupied.update(positions)
                if len(occupied) > MAX_CELLS:
                    raise ValueError('TABLE_GRID_LIMIT')
                values[r, c] = cell['text'].strip()
                if height > 1 or width > 1:
                    merges.append(dict(row=r, column=c, rowspan=height, colspan=width))
                c += width
            widths.append(max((x + 1 for y, x in occupied if y == r), default=0))
        width = max(widths, default=0)
        if not width or len(source) * width > MAX_CELLS:
            raise ValueError('TABLE_GRID_LIMIT')
        tables.append(dict(rows=[[values.get((r, c), '') for c in range(width)] for r in range(len(source))],
                           merges=merges, header_rows=header_rows or None,
                           has_header_tags=any(cell['header'] for row in source for cell in row),
                           warnings=['TABLE_RAGGED_ROWS'] if len(set(widths)) > 1 else []))
    return tables


def infer_header_rows(table):
    """Suggest a supported boundary without changing the matrix or inventing confidence."""
    rows, merges = table['rows'], table['merges']
    unknown = (None, None)
    if not rows or table.get('warnings'):
        return unknown
    def crosses(boundary):
        return any(m['row'] < boundary < m['row'] + m['rowspan'] for m in merges)
    explicit = table.get('header_rows')
    if explicit:
        possible_title = any(m['row'] == 0 and m['colspan'] == len(rows[0]) for m in merges)
        return (explicit, 'model_tags') if explicit < len(rows) and not crosses(explicit) and not possible_title else unknown
    # Mixed row labels (<th> in body rows) are not whole-row column headers.
    if table.get('has_header_tags') or len(rows) < 3 or len(rows[0]) < 2:
        return unknown

    def kind(value):
        value = value.strip()
        if re.fullmatch(r'[+\-−]?\d+(?:,\d{3})*(?:\.\d+)?[%％]?', value):
            return 'number'
        if re.fullmatch(r'\d{4}[-/.年]\d{1,2}[-/.月]\d{1,2}日?', value):
            return 'date'
        return 'text' if any(c.isalpha() for c in value) else None

    def data_columns(body):
        columns = {}
        for c in range(len(rows[0])):
            types = {kind(row[c]) for row in body}
            if len(types) == 1 and types <= {'number', 'date'}:
                columns[c] = next(iter(types))
        return columns

    def sequence(body):
        values = [row[0].strip() for row in body]
        return (all(re.fullmatch(r'\d{1,6}', v) for v in values)
                and all(int(b) == int(a) + 1 for a, b in zip(values, values[1:])))

    # Years may also be headings. Require 1,2,3 AND another typed column.
    if (not merges and rows[0][0].strip().lstrip('0') == '1' and sequence(rows[:3])
            and len(data_columns(rows[:3])) >= 2 and all(any(kind(v) == 'text' for v in row) for row in rows[:3])):
        return 0, 'data_rows'

    # Resolve covered labels only in a scratch grid to compare leaf columns.
    labels = [row[:] for row in rows]
    for m in merges:
        for r in range(m['row'], m['row'] + m['rowspan']):
            for c in range(m['column'], m['column'] + m['colspan']):
                labels[r][c] = rows[m['row']][m['column']]
    candidates = []
    for count in range(1, len(rows) - 1):
        if crosses(count):
            continue
        header_merges = [m for m in merges if m['row'] < count]
        # A full-width heading might be the document title, not a header level.
        if any(m['colspan'] == len(rows[0]) for m in header_merges):
            continue
        if any(not any(kind(v) == 'text' for v in row) for row in rows[:count]):
            continue
        # Every extra header level must connect to the preceding hierarchy.
        if any(not any(
                m['row'] < r < m['row'] + m['rowspan'] or
                m['row'] + m['rowspan'] == r and m['colspan'] > 1 and
                sum(bool(v.strip()) for v in rows[r][m['column']:m['column'] + m['colspan']]) >= 2
                for m in header_merges) for r in range(1, count)):
            continue
        body = rows[count:count + 3]
        typed = data_columns(body)
        transitions = [c for c in typed if kind(labels[count - 1][c]) == 'text']
        leaf_labels = sum(kind(v) == 'text' for v in labels[count - 1])
        if (len(transitions) >= 2 or
                0 in transitions and sequence(body) and leaf_labels >= 2):
            candidates.append(count)
    return (candidates[0], 'structure') if len(candidates) == 1 else unknown


def locate_table_candidates(image, check=lambda: None):
    """Rank line-connected rectangles. Counts are hints, never output dimensions."""
    import cv2
    import numpy as np
    cv2.setNumThreads(1)
    check()
    probe = image.convert('RGB')
    probe.thumbnail((1600, 1600))
    gray = cv2.cvtColor(np.asarray(probe), cv2.COLOR_RGB2GRAY)
    binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                   cv2.THRESH_BINARY_INV, 31, 12)
    horizontal = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((1, max(15, probe.width // 50)), np.uint8))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, np.ones((max(12, probe.height // 65), 1), np.uint8))
    joined = cv2.morphologyEx(horizontal | vertical, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    contours = cv2.findContours(joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)[0]
    sx, sy = image.width / probe.width, image.height / probe.height
    candidates = []
    for contour in sorted(contours, key=cv2.contourArea, reverse=True)[:30]:
        check()
        x, y, w, h = cv2.boundingRect(contour)
        if w < probe.width * .2 or h < probe.height * .05 or w * h < probe.width * probe.height * .035:
            continue
        area = float(cv2.contourArea(contour))
        if area / (w * h) < .65:
            continue
        junction = (horizontal[y:y+h, x:x+w] & vertical[y:y+h, x:x+w])
        count = cv2.connectedComponents(junction)[0] - 1
        if count < 6:
            continue
        hull = cv2.convexHull(contour)
        polygon = cv2.approxPolyDP(hull, .025 * cv2.arcLength(hull, True), True).reshape(-1, 2)
        quad = None
        if len(polygon) == 4 and cv2.isContourConvex(polygon) and cv2.contourArea(polygon) / area > .85:
            points = sorted(polygon.tolist(), key=lambda p: p[1])
            top = sorted(points[:2]); bottom = sorted(points[2:])
            ordered = [top[0], top[1], bottom[1], bottom[0]]
            if min(math.dist(ordered[i], ordered[(i+1) % 4]) for i in range(4)) > 30:
                quad = [[px*sx, py*sy] for px, py in ordered]
        box = [max(0, (x-4)*sx), max(0, (y-4)*sy), min(image.width, (x+w+4)*sx), min(image.height, (y+h+4)*sy)]
        candidates.append(dict(box=box, quad=quad, junctions=count,
                               score=float(count * math.sqrt(area / (probe.width * probe.height)))))
    return sorted(candidates, key=lambda item: item['score'], reverse=True)[:6]


def candidate_image(image, candidate):
    """Bounded perspective correction; keep source quad for inverse mapping."""
    import cv2
    import numpy as np
    from PIL import Image
    quad = candidate.get('quad')
    if not quad:
        return image.crop(tuple(round(v) for v in candidate['box'])), None
    width = math.ceil(max(math.dist(quad[0], quad[1]), math.dist(quad[3], quad[2])))
    height = math.ceil(max(math.dist(quad[0], quad[3]), math.dist(quad[1], quad[2])))
    if width * height > 40_000_000 or not min(width, height):
        raise ValueError('TABLE_REGION_LIMIT')
    # A small white border keeps edge glyphs away from the crop boundary.
    matrix = cv2.getPerspectiveTransform(np.float32(quad), np.float32([[4,4],[width+3,4],[width+3,height+3],[4,height+3]]))
    pixels = cv2.warpPerspective(np.asarray(image.convert('RGB')), matrix, (width+8, height+8), borderValue=(255,255,255))
    return Image.fromarray(pixels), matrix.tolist()


def nearby_text(image, candidates, check=lambda: None):
    """Existing CPU OCR supplies source-bound text; none is assumed to be a title."""
    import numpy as np
    from .document_classification import _engine
    check()
    result = _engine()(np.asarray(image.convert('RGB')))
    check()
    snippets = []
    if result.boxes is None or result.txts is None:
        return snippets
    for polygon, text in zip(result.boxes, result.txts):
        points = np.asarray(polygon)
        box = [float(points[:,0].min()), float(points[:,1].min()), float(points[:,0].max()), float(points[:,1].max())]
        snippets.append(dict(text=str(text), box=box))
    return snippets


def grid_dimensions_hint(image):
    """Only count long continuous dividers; missing/merged lines remain uncertain."""
    import cv2
    import numpy as np
    gray=cv2.cvtColor(np.asarray(image.convert('RGB')),cv2.COLOR_RGB2GRAY)
    binary=cv2.adaptiveThreshold(gray,255,cv2.ADAPTIVE_THRESH_GAUSSIAN_C,cv2.THRESH_BINARY_INV,31,12)
    counts=[]
    for axis,length in [(1,image.width),(0,image.height)]:
        kernel=np.ones((1,max(10,round(length*.7))),np.uint8) if axis==1 else np.ones((max(10,round(length*.7)),1),np.uint8)
        lines=cv2.morphologyEx(binary,cv2.MORPH_OPEN,kernel)
        positions=np.flatnonzero(np.count_nonzero(lines,axis=axis)>length*.75)
        counts.append(int(1+np.sum(np.diff(positions)>3)) if len(positions) else 0)
    return [max(0,n-1) for n in counts]


def validate_table_grid(table):
    """Validate saved data before accepting edits or allocating an Excel grid."""
    if not isinstance(table, dict):
        raise ValueError('TABLE_INVALID_GRID')
    rows, merges = table.get('rows'), table.get('merges')
    if (not isinstance(rows, list) or not 1 <= len(rows) <= MAX_ROWS
            or not isinstance(rows[0], list) or not 1 <= len(rows[0]) <= MAX_COLUMNS
            or len(rows) * len(rows[0]) > MAX_CELLS or not isinstance(merges, list)):
        raise ValueError('TABLE_GRID_LIMIT')
    width = len(rows[0])
    total = 0
    for row in rows:
        if not isinstance(row, list) or len(row) != width:
            raise ValueError('TABLE_RAGGED_ROWS')
        for value in row:
            if not isinstance(value, str) or len(value) > 32767 or re.search(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', value):
                raise ValueError('TABLE_INVALID_TEXT')
            total += len(value)
    if total > 1_000_000 or len(merges) > MAX_CELLS:
        raise ValueError('TABLE_OUTPUT_LIMIT')
    occupied = set()
    for merge in merges:
        if not isinstance(merge, dict) or set(merge) != {'row', 'column', 'rowspan', 'colspan'} or any(type(v) is not int for v in merge.values()):
            raise ValueError('TABLE_INVALID_SPAN')
        r, c, h, w = (merge[k] for k in ('row','column','rowspan','colspan'))
        if r < 0 or c < 0 or h < 1 or w < 1 or h*w == 1 or r+h > len(rows) or c+w > width:
            raise ValueError('TABLE_INVALID_SPAN')
        for y in range(r,r+h):
            for x in range(c,c+w):
                if (y,x) in occupied or (y,x) != (r,c) and rows[y][x] != '':
                    raise ValueError('TABLE_OVERLAPPING_SPAN')
                occupied.add((y,x))
    title, headers = table.get('title'), table.get('header_rows')
    if not isinstance(title, str) or len(title) > 200 or re.search(r'[\x00-\x1f]', title):
        raise ValueError('TABLE_INVALID_TITLE')
    if headers is not None and (type(headers) is not int or not 0 <= headers <= len(rows)):
        raise ValueError('TABLE_INVALID_HEADER')
    if type(table.get('partial_acknowledged', False)) is not bool:
        raise ValueError('TABLE_INVALID_ACKNOWLEDGEMENT')


def effective_tables(result):
    """Read-time export view; never turn OCR defaults into a human review."""
    from copy import deepcopy
    if 'reviewed_tables' in result:
        return deepcopy(result['reviewed_tables'])
    tables = deepcopy(result.get('tables', []))
    for table in tables:
        if not table.get('title'):
            titles = {candidate['text'].strip() for candidate in table.get('title_candidates', [])
                      if candidate['text'].strip()}
            table['title'] = next(iter(titles)) if len(titles) == 1 else ''
        if table.get('header_rows') is None:
            count = table.get('header_suggestion')
            supported = (not table.get('incomplete')
                         and table.get('header_suggestion_source') in {'model_tags', 'structure', 'data_rows'}
                         and type(count) is int and 0 <= count < len(table.get('rows', [])))
            table['header_rows'] = count if supported else None
        # Partial-output acceptance can only come from a saved human edit.
        table['partial_acknowledged'] = False
    return tables


def table_blockers(result):
    tables = effective_tables(result)
    if not tables:
        return [dict(field='tables', code='MISSING')]
    if not isinstance(tables, list) or len(tables) != 1:
        return [dict(field='tables', code='INVALID_TABLE')]
    problems = []
    for i, table in enumerate(tables):
        try:
            validate_table_grid(table)
        except ValueError:
            problems.append(dict(field=f'tables[{i}]', code='INVALID_TABLE'))
            continue
        for key, valid in [('title',bool(table['title'].strip())), ('header_rows',table['header_rows'] is not None)]:
            if not valid:
                problems.append(dict(field=f'tables[{i}].{key}', code='MISSING'))
        original = next((t for t in result.get('tables',[]) if t['table_id']==table.get('table_id')),None)
        if not original or original.get('incomplete') and not table.get('partial_acknowledged'):
            problems.append(dict(field=f'tables[{i}]', code='INCOMPLETE_OUTPUT'))
    return problems


def apply_table_review(original, body, actor):
    from copy import deepcopy
    from .review import invalid, optional_reason, REQUEST_KEYS
    if not isinstance(body,dict) or set(body)-REQUEST_KEYS:
        invalid('复核包含未知参数')
    optional_reason(body.get('note'))
    # Other document payloads may be empty defaults, but can never edit a table.
    if any(value for key,value in body.items() if key not in {'run_id','expected_revision','tables','note'}):
        invalid('表格任务只接受表格草稿')
    patches = body.get('tables')
    if not isinstance(patches,list) or len(patches) != 1:
        invalid('请选择并保存一个表格主体')
    source = {t['table_id']:t for t in original.get('tables',[])}
    allowed = {'table_id','title','header_rows','rows','merges','partial_acknowledged'}
    for patch in patches:
        if not isinstance(patch,dict) or set(patch) != allowed or not isinstance(patch.get('table_id'),str) or patch['table_id'] not in source:
            invalid('表格不属于当前任务，或包含不可修改的来源信息')
        try:
            validate_table_grid(patch)
        except ValueError:
            invalid('表格数据、表头或合并范围无效，请检查是否覆盖了已有内容')
    result = deepcopy(original)
    result['reviewed_tables'] = deepcopy(patches)
    result['table_reviewed_by'] = actor
    pending = table_blockers(result)
    result['review_issues'] = original.get('review_issues',[]) if pending else []
    result['status'] = result['state'] = 'NEED_REVIEW' if pending else 'COMPLETED'
    return result
