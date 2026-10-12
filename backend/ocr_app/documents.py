"""CPU decoding/layout, with optional local certificate-photo orientation."""
from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field
from html import escape
from uuid import uuid4

import fitz
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from .image_admission import ImageAdmissionError, validate_image

register_heif_opener()
MAX_PIXELS = 40_000_000
MAX_PAGES = 100
MAX_BYTES = 100 * 1024 * 1024


class DocumentError(ValueError):
    def __init__(self, code: str = 'DECODE_FAILED'):
        self.code = code
        super().__init__(code)


@dataclass
class Page:
    index: int
    image: Image.Image
    evidence: list[dict] = field(default_factory=list)
    ocr_boxes: list[tuple[int, int, int, int]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    image_preprocessing: dict | None = None


def png_bytes(image: Image.Image) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format='PNG')
    return stream.getvalue()


def normalized_box(box, size) -> list[float]:
    width, height = size
    return [round(box[0] / width, 6), round(box[1] / height, 6),
            round(box[2] / width, 6), round(box[3] / height, 6)]


def _pdf(data: bytes):
    pdf = fitz.open(stream=data, filetype='pdf')
    if pdf.needs_pass:
        pdf.close()
        raise DocumentError('PDF_ENCRYPTED')
    if not 1 <= len(pdf) <= MAX_PAGES:
        pdf.close()
        raise DocumentError('DOCUMENT_LIMIT')
    return pdf


def validate_document(data: bytes, *, check=lambda: None) -> str:
    """Decode in memory; content screening only covers existing PDF text.

    Image content cannot be classified without recognition. MIME is determined
    from the decoder, never the upload filename. No files are written here.
    """
    if not data or len(data) > MAX_BYTES:
        raise DocumentError('DOCUMENT_LIMIT' if data else 'DECODE_FAILED')
    try:
        if data.lstrip().startswith(b'%PDF-'):
            with _pdf(data) as pdf:
                for page in pdf:
                    check()
                    if page.rect.is_empty or page.rect.width * page.rect.height * 4 > MAX_PIXELS:
                        raise DocumentError('DOCUMENT_LIMIT')
                    text = page.get_text()
                    if re.search(r'\b(?:CVV2?|CVC2?|CID)\s*[:：]?\s*\d{3,4}\b', text, re.I):
                        raise DocumentError('SENSITIVE_AUTH_DATA')
            return 'application/pdf'
        with Image.open(io.BytesIO(data)) as image:
            mime = validate_image(image, MAX_PIXELS)
            image.load()
            return mime
    except ImageAdmissionError as exc:
        raise DocumentError(exc.code) from exc
    except DocumentError:
        raise
    except (OSError, ValueError, RuntimeError, Image.DecompressionBombError) as exc:
        raise DocumentError() from exc


def reliable_text(text: str) -> bool:
    # Recognize one known decorative list glyph only at a line's list position.
    # Keep the original evidence unchanged, and do not whitelist arbitrary PUA.
    scoring_text = re.sub(r'(?m)^([ \t]*)\uf076(?=\s*\S)', r'\1•', text)
    compact = ''.join(scoring_text.split())
    if len(compact) < 8 or '\ufffd' in text or '(cid:' in text:
        return False
    printable = sum(c.isprintable() and not '\ue000' <= c <= '\uf8ff' for c in compact)
    return printable / len(compact) >= .98 and sum(c.isalnum() for c in compact) >= 5


def _evidence(text, index, bbox, method='pdf_text'):
    return dict(text=text, page=index, region_id=str(uuid4()),
                extraction_method=method, bbox=bbox)


def _header_columns(cells):
    aliases = {'sequence': {'序号'},
               'name': {'项目', '项目名称', '检验项目', '检测项目', '检查项目', '中文名称'},
               'result': {'结果', '检测结果', '检验结果', '检查结果', '测定值'}}
    normalized = [re.sub(r'\s+', '', cell or '').strip(':：') for cell in cells]
    matches = {key: [i for i, cell in enumerate(normalized) if cell in names]
               for key, names in aliases.items()}
    return {key: indices[0] for key, indices in matches.items()} if all(len(v) == 1 for v in matches.values()) else None


def _table_snapshot(table):
    # PyMuPDF's next find_tables call can replace its page-global extraction data.
    # Snapshot every original table before attempting a second detection strategy.
    return dict(bbox=tuple(table.bbox), rows=table.extract(),
                cells=[list(row.cells) for row in table.rows], recovery='native_lines')


def _recover_header_body(page, table, neighbors):
    """Recover only an observed medical header with no ruled body.

    No reference values, page numbers, expected row count, or expected first
    sequence number influence recovery. Fail closed for ambiguous columns/rows.
    """
    if len(table['rows']) != 1:
        return table, None
    columns = _header_columns(table['rows'][0])
    if columns is None:
        headings = {re.sub(r'\s+', '', value or '') for value in table['rows'][0]}
        if '序号' in headings and headings & {'项目', '项目名称', '检验项目', '检测项目', '检查项目',
                                             '结果', '检测结果', '检验结果', '检查结果'}:
            return table, '原生表头字段缺失或重复，未猜测表体列映射。'
        return table, None
    cells = table['cells'][0]
    if len(cells) != len(table['rows'][0]) or any(cell is None for cell in cells):
        return table, '原生表头存在合并或缺失列界，未猜测表体列位置。'
    if any(abs(left[2] - right[0]) > 1 for left, right in zip(cells, cells[1:])):
        return table, '原生表头列界不连续，未恢复表体。'
    bounds = [cell[0] for cell in cells] + [cells[-1][2]]
    if any(a >= b for a, b in zip(bounds, bounds[1:])):
        return table, '原生表头列界有歧义，未恢复表体。'
    x0, top, x1, header_bottom = table['bbox']
    # Clip before the next vertically adjacent table whose horizontal extent
    # overlaps this one. Side-by-side tables remain independent.
    following = [other['bbox'][1] for other in neighbors if other is not table
                 and other['bbox'][1] >= header_bottom
                 and min(x1, other['bbox'][2]) > max(x0, other['bbox'][0])]
    bottom = min(following, default=page.rect.height) - 1
    if bottom <= header_bottom:
        return table, '原生表体边界不可确定。'
    found = page.find_tables(clip=(x0, top, x1, bottom), vertical_strategy='explicit',
                             vertical_lines=bounds, horizontal_strategy='text', min_words_horizontal=1)
    selected = []
    words = page.get_text('words')
    for candidate in found.tables:
        rows = candidate.extract()
        for row, geometry in zip(rows, candidate.rows):
            row_cells = list(geometry.cells)
            if len(row) != len(cells):
                # Text-derived horizontal edges sometimes end inside the outer
                # header columns. Keep their observed line band, and complete
                # only the already-known column extents using positioned words.
                present = [cell for cell in row_cells if cell is not None]
                if not present:
                    continue
                y0, y1 = min(c[1] for c in present), max(c[3] for c in present)
                row_cells = [(left, y0, right, y1) for left, right in zip(bounds, bounds[1:])]
                row = [' '.join(w[4] for w in sorted(words, key=lambda w: w[0])
                                if left <= (w[0]+w[2])/2 < right and y0 <= (w[1]+w[3])/2 < y1)
                       for left, _, right, _ in row_cells]
            ordinal = re.sub(r'\s+', '', row[columns['sequence']] or '')
            if not re.fullmatch(r'\d+', ordinal):
                continue
            if not row[columns['name']] or not row[columns['result']] or any(cell is None for cell in row_cells):
                return table, '原生表体存在缺列或合并行，保留文字证据待复核。'
            selected.append((int(ordinal), row, row_cells))
    if not selected:
        return table, '原生表头已识别，但没有可靠恢复出带序号的数据行。'
    ordinals = [entry[0] for entry in selected]
    if ordinals[0] < 1 or any(right != left + 1 for left, right in zip(ordinals, ordinals[1:])):
        return table, '原生表体序号重复、倒序或断档，未自动接受恢复结果。'
    rows = table['rows'] + [entry[1] for entry in selected]
    geometry = table['cells'] + [entry[2] for entry in selected]
    full_box = fitz.Rect(table['bbox'])
    for row in geometry:
        for cell in row:
            full_box |= fitz.Rect(cell)
    return dict(bbox=tuple(full_box), rows=rows, cells=geometry, recovery='header_guided_text'), None


def _split_header_continuation(page, table, previous):
    """Join the observed adjacent-page 风险 / 等级 split, only at equal columns."""
    if previous is None or len(table['rows']) != 1 or table['bbox'][1] > page.rect.height * .25:
        return None
    prior = previous['table']
    labels = [re.sub(r'\s+', '', value or '') for value in table['rows'][0]]
    old_labels = [re.sub(r'\s+', '', value or '') for value in prior['rows'][0]]
    if len(labels) != len(old_labels) or labels != [''] * (len(labels) - 1) + ['等级']:
        return None
    if abs(page.rect.width - previous['size'][0]) > 1 or abs(page.rect.height - previous['size'][1]) > 1:
        return None
    if any(cell is None for cell in table['cells'][0] + prior['cells'][0]):
        return None
    if any(abs(a[0] - b[0]) > 1 or abs(a[2] - b[2]) > 1
           for a, b in zip(table['cells'][0], prior['cells'][0])):
        return None
    return dict(table, rows=[prior['rows'][0][:-1] + ['风险等级']])


def decode_pages(data: bytes, check=lambda: None, *, preprocessing=None):
    """Yield corrected full pages; reliable text and uncovered image regions.

    A PDF's text heuristic is deliberately conservative, not a probability.
    Raster image boxes with a substantial text overlay are still sent to OCR:
    a small text label never proves the underlying image was transcribed.
    A supplied preprocessing dictionary enables certificate/card-photo preparation
    and reuses its first decision on pass two. PDFs never consume that option.
    """
    check()
    mime = validate_document(data, check=check)
    check()
    if mime != 'application/pdf':
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
        decision = None
        if preprocessing is not None:
            from .image_preprocessing import prepare_image, apply_correction
            if 'decision' in preprocessing:
                decision = preprocessing['decision']
                image = apply_correction(image, decision)
            else:
                image, decision = prepare_image(image, check, doc_type=preprocessing.get('doc_type'))
                preprocessing['decision'] = decision
            check()
        yield Page(1, image, ocr_boxes=[(0, 0, *image.size)], image_preprocessing=decision)
        return
    with _pdf(data) as pdf:
        continuation = None
        for index, page in enumerate(pdf, 1):
            previous, continuation = continuation, None
            continuation_used = False
            check()
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
            result = Page(index, image)
            if image.convert('L').getextrema()[0] >= 250:
                if previous:
                    result.limitations.append(previous['limitation'])
                yield result
                continue
            blocks = page.get_text('blocks')
            text_blocks = [block for block in blocks if len(block) < 7 or block[6] == 0]
            valid = [block for block in text_blocks if reliable_text(block[4])]
            # Bboxes returned by text/image extraction are unrotated PDF coordinates.
            def box_of(rect):
                rect = fitz.Rect(rect) * page.rotation_matrix
                rect &= page.rect
                return (max(0, math.floor(rect.x0 * 2)), max(0, math.floor(rect.y0 * 2)),
                        min(image.width, math.ceil(rect.x1 * 2)), min(image.height, math.ceil(rect.y1 * 2)))
            for block in valid:
                box = box_of(block[:4])
                if box[2] > box[0] and box[3] > box[1]:
                    result.evidence.append(_evidence(block[4], index, normalized_box(box, image.size)))
            bad = [block for block in text_blocks if block not in valid and block[4].strip()]
            # Short isolated text (e.g. one table cell) is reliable in a reliable page.
            whole_text = page.get_text()
            if reliable_text(whole_text) and not any('\ufffd' in b[4] or '(cid:' in b[4] for b in bad):
                for block in bad:
                    box = box_of(block[:4])
                    result.evidence.append(_evidence(block[4], index, normalized_box(box, image.size)))
                bad = []
            if not result.evidence:
                result.warnings.append('PDF_NO_TEXT_LAYER' if not whole_text.strip() else 'PDF_TEXT_UNRELIABLE')
                result.ocr_boxes = [(0, 0, *image.size)]
            else:
                for block in bad:
                    box = box_of(block[:4])
                    if box[2] > box[0] and box[3] > box[1]:
                        result.ocr_boxes.append(box)
                if bad:
                    result.warnings.append('PDF_TEXT_UNRELIABLE')
                image_boxes = [box_of(info['bbox']) for info in page.get_image_info()]
                for box in image_boxes:
                    if box[2] - box[0] >= 32 and box[3] - box[1] >= 32:
                        if box not in result.ocr_boxes:
                            result.ocr_boxes.append(box)
                # Native table extraction preserves columns; never use text order to guess them.
                try:
                    tables = [_table_snapshot(table) for table in page.find_tables().tables]
                    for table in tables:
                        inherited = _split_header_continuation(page, table, previous)
                        try:
                            recovered, limitation = _recover_header_body(page, inherited or table, tables)
                        except Exception:
                            recovered, limitation = table, '原生表体补充恢复失败，保留原线框表格和文字证据。'
                        if inherited is not None:
                            continuation_used = True
                            if len(recovered['rows']) > 1:
                                recovered['recovery'] = 'split_header_continuation'
                        # Only defer a known partial header on the immediately following page.
                        # A failed/unmatched continuation still reports a limitation.
                        if (limitation and len(table['rows']) == 1 and _header_columns(table['rows'][0])
                                and re.sub(r'\s+', '', table['rows'][0][-1] or '') == '风险'
                                and table['bbox'][1] > page.rect.height * .8 and index < len(pdf)):
                            continuation = dict(table=table, size=(page.rect.width, page.rect.height),
                                                limitation=limitation, page=index,
                                                bbox=normalized_box(box_of(table['bbox']), image.size))
                            limitation = None
                        if limitation:
                            result.limitations.append(limitation)
                        rows = recovered['rows']
                        html = '<table>' + ''.join('<tr>' + ''.join('<td>' + escape(cell or '') + '</td>'
                               for cell in row) + '</tr>' for row in rows) + '</table>'
                        block = _evidence(html, index, normalized_box(box_of(recovered['bbox']), image.size))
                        block['table_recovery'] = recovered['recovery']
                        if recovered['recovery'] == 'split_header_continuation':
                            block['table_header_source'] = dict(page=previous['page'], bbox=previous['bbox'],
                                                                text=previous['table']['rows'][0])
                        block['table_rows'] = []
                        for row_index, cells in enumerate(recovered['cells']):
                            present = [fitz.Rect(cell) for cell in cells if cell is not None]
                            row_box = fitz.Rect(present[0]) if present else None
                            for cell in present[1:]:
                                row_box |= cell
                            block['table_rows'].append(dict(
                                bbox=normalized_box(box_of(row_box), image.size) if row_box else None,
                                cell_bboxes=[normalized_box(box_of(cell), image.size) if cell else None for cell in cells],
                                is_header=row_index == 0 and _header_columns(rows[0]) is not None))
                        result.evidence.append(block)
                except Exception:
                    result.limitations.append('PDF原生表格布局提取不可用，保留文字证据供人工核对。')
            if previous and not continuation_used:
                result.limitations.append(previous['limitation'])
            check()
            yield result


def split_regions(image: Image.Image, box: tuple, medical: bool) -> list[tuple]:
    """Split long medical content only in observed horizontal white bands.

    Regions partition the entire original box, including margins. If a safe
    boundary is absent, retain the whole region rather than cut through text.
    """
    x0, y0, x1, y1 = box
    width, height = x1 - x0, y1 - y0
    if not medical or height < 1200:
        return [box]
    preview = image.crop(box).convert('L')
    preview.thumbnail((256, 12000))
    scale = height / preview.height
    pixels = preview.load()
    runs, start, ink_bands, in_ink = [], None, 0, False
    for y in range(preview.height):
        white = sum(pixels[x, y] >= 242 for x in range(preview.width)) / preview.width >= .997
        if not white and not in_ink:
            ink_bands += 1
        in_ink = not white
        if white and start is None:
            start = y
        if not white and start is not None:
            if (y - start) * scale >= 12:
                runs.append(round((start + y) * scale / 2))
            start = None
    dense = ink_bands >= 35
    if not dense and height <= max(1600, width * 1.6):
        return [box]
    target = max(650, int(width * (.75 if dense else 1.3)))
    cuts, cursor = [0], 0
    while height - cursor > target * 1.4:
        choices = [cut for cut in runs if cursor + target * .55 <= cut <= cursor + target * 1.35]
        if not choices:
            break
        cursor = min(choices, key=lambda cut: abs(cut - (cursor + target)))
        cuts.append(cursor)
    cuts.append(height)
    return [(x0, y0 + top, x1, y0 + bottom) for top, bottom in zip(cuts, cuts[1:])]


def region_task(image: Image.Image, box: tuple, medical: bool) -> str:
    """Only clear ruled tables select table recognition; uncertain layouts use OCR."""
    if not medical:
        return 'ocr'
    preview = image.crop(box).convert('L')
    preview.thumbnail((400, 600))
    pixels = preview.load()
    def bands(flags):
        previous, count = False, 0
        for flag in flags:
            count += bool(flag and not previous)
            previous = flag
        return count
    horizontal = bands(sum(pixels[x, y] < 150 for x in range(preview.width)) / preview.width > .65
                       for y in range(preview.height))
    vertical = bands(sum(pixels[x, y] < 150 for y in range(preview.height)) / preview.height > .45
                     for x in range(preview.width))
    return 'table' if horizontal >= 3 and vertical >= 2 else 'ocr'
