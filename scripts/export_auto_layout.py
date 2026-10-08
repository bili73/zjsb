"""Export frozen-field automatic-layout evidence; never discard failed regions."""
import argparse
import csv
import hashlib
import json
from pathlib import Path

from export_two_model_retest import MODELS, norm, read, sha, write_csv


def summarize(pages, model, variant, cohort):
    chosen = [p for p in pages if p['model'] == model and p['variant'] == variant
              and (cohort == 'all' or p['cohort'] == cohort)]
    total = sum(int(p['field_total']) for p in chosen)
    correct = sum(int(p['field_correct']) for p in chosen)
    return dict(model=model, variant=variant, cohort=cohort, parents=len(chosen),
                field_correct=correct, field_total=total,
                field_accuracy=correct / total if total else None,
                complete_parents=sum(int(p['complete_no_limit_or_repetition']) for p in chosen),
                ocr_request_s=sum(float(p['request_s']) for p in chosen),
                layout_preparation_s=(sum(float(p.get('layout_preparation_s', 0)) for p in chosen)
                                      if variant == 'automatic' else None),
                timing_scope='cached image requests; auto layout preparation separate; manual crop cost unmeasured')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-dir', type=Path, required=True)
    args = ap.parse_args()
    base = args.run_dir.resolve()
    protocol = read(base / 'protocol.json')
    previous = Path(protocol['reference_run'])
    assert sha(base / 'references.json') == protocol['reference_sha256']
    refs = read(base / 'references.json')['samples']
    manifest = read(base / 'inputs/manifest.json')
    layout = {p['parent_id']: p for p in read(base / 'layout/parents.json')}
    sessions = {m: read(base / m / 'session.json') for m in MODELS}
    assert all(s['status'] == 'finished' for s in sessions.values())
    windows = sorted((s['started_at'], s['finished_at']) for s in sessions.values())
    assert windows[0][1] <= windows[1][0], 'OCR model sessions overlap'
    pages, fields, runs, resources = [], [], [], []
    for model in MODELS:
        review_file = base / 'reviews' / (model + '-automatic.json')
        reviews = read(review_file)['variants']['automatic']
        assert set(reviews) == set(layout), 'Review coverage differs from frozen parents'
        for sid, parent in layout.items():
            review = reviews[sid]
            reference = refs[sid]
            assert review['complete_reviewed']
            assert set(review['fields']) == set(reference['fields']), sid
            regions = [r for r in manifest if r['parent_id'] == sid]
            names = {r['id'] + '.txt' for r in regions if (base / model / (r['id'] + '.txt')).exists()}
            assert set(review['output_sha256']) == names, (sid, 'Output review coverage')
            for name, digest in review['output_sha256'].items():
                assert sha(base / model / name).lower() == digest.lower(), name
            current = []
            for region in regions:
                rid = region['id']
                metrics = read(base / model / (rid + '.metrics.json'))
                assert sha(Path(region['image'])) == region['input_sha256'] == metrics['input_sha256']
                output = base / model / (rid + '.txt')
                # Runner hashes decoded text; review hashes original bytes (Windows CRLF).
                if output.exists():
                    assert hashlib.sha256(output.read_text(encoding='utf-8').encode()).hexdigest() == metrics['output_sha256']
                else:
                    assert metrics['status'] == 'error', (rid, 'Successful output missing')
                row = dict(model=model, parent_id=sid, region_id=rid,
                           cohort=parent['cohort'], task=region['task'],
                           **{k: metrics.get(k) for k in [
                               'status', 'termination_reason', 'seconds', 'request_wall_seconds',
                               'output_tokens', 'peak_reserved_gib', 'process_rss_peak_gib',
                               'host_used_peak_gib', 'host_available_min_gib']},
                           input_sha256=region['input_sha256'],
                           metrics_file=str(Path(model) / (rid + '.metrics.json')))
                runs.append(row)
                current.append(row)
            correct = 0
            for field, expected in reference['fields'].items():
                predicted = review['fields'][field]
                exact = int(predicted is not None and norm(predicted, reference['normalization']) == norm(expected, reference['normalization']))
                correct += exact
                fields.append(dict(model=model, variant='automatic', parent_id=sid,
                                   cohort=parent['cohort'], field=field, reference_value=expected,
                                   predicted_value=predicted, exact_match=exact,
                                   review_file=review_file.relative_to(base).as_posix(),
                                   reference_status='provisional_not_human_double_reviewed'))
            total = len(reference['fields'])
            pages.append(dict(model=model, variant='automatic', parent_id=sid,
                              cohort=parent['cohort'], regions=len(regions), field_correct=correct,
                              field_total=total, field_accuracy=correct / total if total else None,
                              complete_no_limit_or_repetition=int(all(r['status'] == 'ok' and r['termination_reason'] == 'eos' for r in current)
                                                                 and not review['degenerate_repetition']),
                              request_s=sum(r['request_wall_seconds'] for r in current),
                              layout_preparation_s=parent['preparation_seconds'],
                              notes=review['notes']))
        session = sessions[model]
        warmup = read(base / model / ('warmup-' + manifest[0]['id'] + '.metrics.json'))
        measured = [r for r in runs if r['model'] == model]
        resources.append(dict(model=model, load_s=session['load_seconds'],
                              warmup_s=warmup['request_wall_seconds'], session_wall_s=session['session_wall_seconds'],
                              rss_peak_gib=max([session['load_memory']['process_rss_peak_gib'], warmup['process_rss_peak_gib']] + [r['process_rss_peak_gib'] for r in measured]),
                              gpu_reserved_peak_gib=max([session['load_peak_reserved_gib'], warmup['peak_reserved_gib']] + [r['peak_reserved_gib'] for r in measured]),
                              model_revision=session['revision'],
                              measurement_scope='single resident; does not measure dual residency'))
    with (previous / 'data/pages.csv').open(encoding='utf-8-sig', newline='') as f:
        for row in csv.DictReader(f):
            if row['parent_id'] in layout and row['variant'] in {'baseline', 'enhanced'}:
                assert int(row['field_total']) == len(refs[row['parent_id']]['fields'])
                pages.append({**row, 'cohort': layout[row['parent_id']]['cohort']})
    summary = [summarize(pages, model, variant, cohort)
               for cohort in ['difficult', 'control', 'all']
               for variant in ['baseline', 'enhanced', 'automatic'] for model in MODELS
               if variant != 'enhanced' or cohort == 'difficult']
    layout_session = read(base / 'layout/session.json')
    result = dict(summary=summary, pages=pages, fields=fields, runs=runs, resources=resources,
                  layout=list(layout.values()), layout_session=layout_session,
                  audit=dict(input_and_output_hashes='verified', review_coverage='complete',
                             serial_sessions='verified', warmups_excluded=True,
                             power_events='see timing-audit.json',
                             exporter_sha256=sha(Path(__file__))))
    target = base / 'data'
    target.mkdir(exist_ok=True)
    for name in ['summary', 'pages', 'fields', 'runs', 'resources']:
        write_csv(target / (name + '.csv'), result[name])
    (target / 'benchmark.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(dict(summary=summary, resources=resources, layout_session=layout_session), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
