"""Score a completed photo-table probe against separately frozen private labels."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import sys
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'backend'))
from ocr_app.storage import Storage


def normalized(value):
    return ''.join(unicodedata.normalize('NFKC', value).split())


def score_tables(tables, sample):
    # Gold is used only by this scorer, never by the image preprocessing/probe.
    reference, kinds = sample['rows'], sample['categories']
    def header_matches(table):
        return max((sum(normalized(v) == normalized(reference[0][c]) for c, v in enumerate(row[:len(reference[0])])) for row in table['rows']), default=0)
    chosen = max(range(len(tables)), key=lambda index: header_matches(tables[index])) if tables else None
    predicted = tables[chosen]['rows'] if chosen is not None else []
    counts, differences = Counter(), []
    for r, row in enumerate(reference):
        for c, expected in enumerate(row):
            kind = kinds[r][c]
            counts[kind+'_total'] += 1
            if expected is None:
                continue
            actual = predicted[r][c] if r < len(predicted) and c < len(predicted[r]) else None
            correct = actual is not None and normalized(actual) == normalized(expected)
            counts[kind+'_correct'] += correct
            if not correct:
                differences.append(dict(row=r, column=c, expected=expected, actual=actual, category=kind))
    return dict(shape_correct=len(predicted) == len(reference) and all(len(r) == len(reference[0]) for r in predicted),
                reference_rows=len(reference), reference_columns=len(reference[0]),
                predicted_rows=len(predicted), predicted_columns=max(map(len, predicted), default=0),
                selected_grid=chosen, counts=dict(counts), differences=differences)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--probe', required=True, type=Path)
    parser.add_argument('--reference', required=True, type=Path)
    args = parser.parse_args()
    source = Storage(args.probe/'private/data')
    references = Storage(args.reference/'private/data')
    encrypted = (args.reference/'private/reference.enc').read_bytes()
    protocol = json.loads((args.reference/'protocol.json').read_text(encoding='utf-8'))
    if hashlib.sha256(encrypted).hexdigest() != protocol['reference_sha256']:
        raise ValueError('REFERENCE_CHANGED')
    reference = references.unpack(encrypted)
    labels = {sample['input_sha256']:sample for sample in reference['samples']}
    scores, private = [], []
    for result in source.unpack((args.probe/'private/results.enc').read_bytes()):
        metric = result['metrics']
        label = labels[metric['input_sha256']]
        scored = score_tables(result['tables'], label)
        counts = scored['counts']
        row = {key:metric[key] for key in ('sample','variant','model','call_seconds','preparation_seconds','termination','error_code')}
        row.update({key:scored[key] for key in ('shape_correct','reference_rows','reference_columns','predicted_rows','predicted_columns')})
        for kind in ('printed','handwritten_legible','blank','handwritten_unresolved','printed_unresolved'):
            row[kind+'_total'] = counts.get(kind+'_total',0)
            row[kind+'_correct'] = counts.get(kind+'_correct',0) if not kind.endswith('_unresolved') else None
        row.update(crossed_out_rows=len(label['crossed_out_rows']), outside_record=label['outside_record'])
        scores.append(row)
        private.append(dict(sample=metric['sample'], variant=metric['variant'], **scored))
    (args.probe/'private/scored.enc').write_bytes(source.pack(private))
    with (args.probe/'scores.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(scores[0]));writer.writeheader();writer.writerows(scores)
    summary=dict(reference_sha256=protocol['reference_sha256'],label_source=reference['label_source'],variants={})
    for variant in sorted({row['variant'] for row in scores}):
        selected=[row for row in scores if row['variant']==variant]
        total=sum(row['printed_total'] for row in selected);correct=sum(row['printed_correct'] for row in selected)
        summary['variants'][variant]=dict(calls=len(selected),structure_matches=sum(row['shape_correct'] for row in selected),
            printed_cells=total,printed_correct=correct,printed_accuracy=correct/total if total else None,
            handwritten_legible_cells=sum(row['handwritten_legible_total'] for row in selected),
            handwritten_legible_correct=sum(row['handwritten_legible_correct'] for row in selected),
            unresolved_cells=sum(row['handwritten_unresolved_total']+row['printed_unresolved_total'] for row in selected),
            mean_call_seconds=sum(row['call_seconds'] for row in selected)/len(selected),
            abnormal_terminations=sum(row['termination']!='eos' or bool(row['error_code']) for row in selected))
    summary['limitations']='Four photos of one form family; agent-only provisional labels. Strict row/column scoring retains failed and truncated calls. Blanks and unresolved text are excluded from printed accuracy. Table-exterior recall, human-correction UX, end-to-end task latency, Mac and concurrency are not measured here.'
    (args.probe/'scores.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
