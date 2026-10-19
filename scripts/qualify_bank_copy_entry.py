"""Replay encrypted bank OCR predictions, without model calls or production access.

The source image, preprocessing and every inference input hash must match the
historical baseline. This qualifies business requirements, not new OCR accuracy.
"""
import argparse
import base64
import copy
import csv
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from probe_current_pipeline import read_only_storage
from ocr_app.pipeline import process_document
from ocr_app.exporting import required_export_blockers
from ocr_app.storage import Storage


def digest(data):
    return hashlib.sha256(data).hexdigest()


def replay(folder, cohort):
    old = read_only_storage(folder / 'private/data')
    encrypted = folder / 'private/results.enc'
    original_hash = digest(encrypted.read_bytes())
    records = old.unpack(encrypted.read_bytes())
    rows, results = [], []
    for index, record in enumerate(records, 1):
        source = Path(record['source'])
        source_hash = digest(source.read_bytes())
        assert source_hash == record['metrics']['input_sha256']
        ordinary = cohort == 'original' and index > 1
        kind = 'BANK_CARD' if ordinary else 'BANK_CARD_COPY'
        predictions = {(a['model'], a['task'], a['input_sha256']): a['prediction'] for a in record['attempts']}
        used, attempts = [], []

        def recognize(model, image, task, timeout, **extra):
            key = model, task, digest(base64.b64decode(image))
            assert key in predictions, 'INPUT_CHANGED: frozen prediction cannot be reused'
            used.append(key)
            return copy.deepcopy(predictions[key])

        started = time.monotonic()
        result = process_document(source.read_bytes(), kind, recognize=recognize,
            progress=lambda *a: None, save_page=lambda *a: 'frozen-page', record_attempt=attempts.append,
            cancelled=lambda: False, deadline=started + 180)
        assert result['doc_type'] == kind
        assert [a['input_sha256'] for a in attempts] == [a['input_sha256'] for a in record['attempts']]
        before = {f['key']: f.get('value') for f in record['result']['fields']}
        after = {f['key']: f.get('value') for f in result['fields']}
        assert before == after, 'FIELD_VALUES_CHANGED'
        blockers = required_export_blockers(result)
        row = dict(sample=f'{cohort}-{index:02}', doc_type=kind, input_sha256=source_hash,
                   values_unchanged=True, frozen_calls=len(used), new_model_calls=0,
                   missing_required=','.join(b['field'] for b in blockers if b['code'] == 'MISSING'),
                   export_blocked=bool(blockers), replay_seconds=round(time.monotonic() - started, 3))
        rows.append(row)
        results.append(dict(metrics=row, result=result, attempts=attempts))
        assert digest(source.read_bytes()) == source_hash
    assert digest(encrypted.read_bytes()) == original_hash
    return rows, results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scans-baseline', type=Path, required=True)
    parser.add_argument('--cards-baseline', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    vault = Storage(args.out / 'private/data')
    rows, results = [], []
    for folder, cohort in [(args.scans_baseline, 'new'), (args.cards_baseline, 'original')]:
        group, private = replay(folder, cohort)
        rows.extend(group); results.extend(private)
        (args.out / 'private/results.enc').write_bytes(vault.pack(results))
    with (args.out / 'cases.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    summary = dict(mode='frozen_prediction_replay', cases=len(rows), new_model_calls=0,
                   identical_field_cases=sum(r['values_unchanged'] for r in rows), inputs_unchanged=True,
                   ordinary_cases=sum(r['doc_type'] == 'BANK_CARD' for r in rows),
                   photocopy_cases=sum(r['doc_type'] == 'BANK_CARD_COPY' for r in rows))
    (args.out / 'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    lines = ['# 银行卡入口拆分：真实样本冻结回放', '',
        '使用既有6张扫描件和4张旧银行卡照片；原图与全部OCR输入哈希匹配后，复用原有加密模型输出。',
        '本次无新增模型推理，不是新的准确率或推理速度实测。结果、原文及来源仅加密保存，源文件和旧证据未修改。', '',
        '| 样本 | 类型 | 字段值与旧结果一致 | 缺少默认必填 | 导出被阻止 |', '|---|---|---|---|---|']
    for row in rows:
        lines.append(f'| {row["sample"]} | {row["doc_type"]} | 是 | {row["missing_required"] or "—"} | {"是" if row["export_blocked"] else "否"} |')
    lines.extend(['', '普通卡3张保留原入口；6张新扫描件及旧模糊复印件按新复印件类型回放，不迁移历史任务。',
        '原识别错误、空值及卡面/手写号码冲突全部保留；四项齐全也不证明值正确，仍需核对原件。',
        '新复印件缺姓名/支行会按新规则阻止导出；旧BANK_CARD任务仍按原类型及管理员设置处理。',
        '仅回放共享识别流程及必填门禁；独立HTTP/网页测试另验证人工保存、类型保留、配置隔离及Excel。'])
    (args.out / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
