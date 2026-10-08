"""Validate and report the frozen medical comparison without publishing private values."""
import argparse
from collections import Counter, defaultdict
import csv
import json
import math
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'scripts')]
from ocr_app.storage import Storage
from ocr_app.extraction import extract_medical_items
from compare_paddle_versions import norm
from compare_schema_extraction import csv_file, digest, save


def rows(path):
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def case_group(case):
    return 'raster' if case.startswith('raster-') else case


def outcomes(group):
    counts = Counter(row['outcome'] for row in group)
    return dict(fields=len(group), correct=counts['correct'], missing=counts['missing'],
                wrong=counts['wrong'], fraction=counts['correct'] / len(group) if group else None)


def report(out):
    protocol = json.loads((out / 'protocol.json').read_text())
    session = json.loads((out / 'session.json').read_text())
    if session['status'] != 'finished':
        raise ValueError('RUN_NOT_FINISHED')
    requests, fields = rows(out / 'requests.csv'), rows(out / 'fields.csv')
    inventory, native = rows(out / 'inventory.csv'), rows(out / 'native_visual_fields.csv')
    storage = Storage(out / 'private/data')
    encrypted = (out / 'private/fixture.enc').read_bytes()
    fixture = storage.unpack(encrypted)
    samples = {sample['id']: sample for sample in fixture}
    sources = storage.unpack((out / 'private/sources.enc').read_bytes())
    checks = dict(fixture_hash=digest(encrypted) == protocol['fixture_sha256'],
                  code_hashes=all(digest((ROOT / path).read_bytes()) == sha for path, sha in protocol['sources'].items()),
                  input_hashes=all(digest(storage.read(s['image_ref'])) == s['input_sha256'] for s in fixture),
                  source_hashes=all(digest(storage.read(s['source_ref'])) == s['source_sha256'] for s in sources)
                                and [{k: s[k] for k in ['id', 'source_sha256', 'bytes', 'extension']} for s in sources] == protocol['documents'],
                  checkpoints=all(json.loads((ROOT / 'models' / k / 'download_manifest.json').read_text()) == manifest
                                  for k, manifest in protocol['checkpoints'].items()),
                  page_count=len(inventory) == protocol['pages'],
                  owned_exits=all(m.get('owned_process_exited') for m in session['models']))
    planned = Counter((checkpoint, s['id'], str(repeat)) for checkpoint in protocol['checkpoints']
                      for s in fixture for repeat in range(1, protocol['repeats'] + 1))
    checks['request_population'] = planned == Counter((r['checkpoint'], r['sample_id'], r['repeat']) for r in requests)
    expected_fields, diagnostics = [], []
    original_results = {}
    reuse_ok = True
    for row in requests:
        sample = samples[row['sample_id']]
        payload = json.loads(storage.read(row['prediction_ref']))
        result = payload['result']
        reuse_ok &= row['input_sha256'] == sample['input_sha256'] and row['task'] == sample['task']
        reuse_ok &= row['termination_reason'] == result['termination_reason']
        identity = (row['checkpoint'], row['sample_id'])
        if row['executed_inference'] == 'True':
            reuse_ok &= bool(row['request_seconds']) and not row['reused_from_sample_id']
            original_results[identity] = result
        else:
            origin = samples[row['reused_from_sample_id']]
            reuse_ok &= not row['request_seconds'] and bool(row['reuse_decode_seconds'])
            reuse_ok &= (origin['input_sha256'], origin['task']) == (sample['input_sha256'], sample['task'])
            reuse_ok &= original_results.get((row['checkpoint'], origin['id'])) == result
        items, limitations = extract_medical_items([dict(text=result['text'], page=1,
                                                        extraction_method='ocr', bbox=[0, 0, 1, 1])])
        candidates = defaultdict(set)
        for item in items:
            for key in {item['name'], item['alias']} - {None, ''}:
                candidates[norm(key)].add(item['result_raw'])
        visible_unmapped = 0
        for basis, refs in [(sample['reference_basis'], sample['reference']),
                            ('visual_provisional', sample.get('visual_reference', {}))]:
            for key, expected in refs.items():
                options = candidates.get(norm(key), set())
                predicted = next(iter(options)) if len(options) == 1 else None
                outcome = 'correct' if predicted is not None and norm(predicted) == norm(expected) else 'missing' if predicted is None else 'wrong'
                expected_fields.append((row['checkpoint'], row['sample_id'], row['repeat'], key, basis, outcome,
                                        str(predicted is not None), str(result['termination_reason'] == 'eos')))
                # Literal presence anywhere is diagnostic only, never field correctness.
                visible_unmapped += outcome == 'missing' and norm(expected) in norm(result['text'])
        diagnostics.append(dict(checkpoint=row['checkpoint'], sample_id=row['sample_id'], case=case_group(sample['case']),
                                mapped_items=len(items), limitations=len(limitations),
                                missing_reference_literal_present_anywhere=visible_unmapped))
    checks['reuse_and_costs'] = reuse_ok
    checks['field_scoring'] = Counter(expected_fields) == Counter(
        tuple(f[key] for key in ['checkpoint', 'sample_id', 'repeat', 'field', 'reference_basis', 'outcome', 'has_value', 'complete_generation'])
        for f in fields)
    checks['unique_execution_count'] = all(sum(r['checkpoint'] == checkpoint and r['executed_inference'] == 'True' for r in requests)
                                          == protocol['unique_cases'] for checkpoint in protocol['checkpoints'])
    audit = dict(status='passed' if all(checks.values()) else 'failed', checks=checks,
                 report_generator_sha256=digest(Path(__file__).read_bytes()),
                 logical_requests=len(requests), planned_logical_requests=sum(planned.values()),
                 physical_inferences=sum(r['executed_inference'] == 'True' for r in requests),
                 confidence_calibrated=False, full_report_accuracy_qualified=False)
    save(out / 'validation.json', audit)
    if audit['status'] != 'passed':
        raise ValueError('VALIDATION_FAILED')
    performance, accuracy = [], []
    for checkpoint in protocol['checkpoints']:
        measured = [r for r in requests if r['checkpoint'] == checkpoint]
        for case in ['all_unique_inputs', 'raster', 'forced_native_table', 'forced_visual_blood']:
            logical = [r for r in measured if case == 'all_unique_inputs' or case_group(r['case']) == case]
            executed = [r for r in logical if r['executed_inference'] == 'True']
            times = sorted(float(r['request_seconds']) for r in executed)
            ends = Counter(r['termination_reason'] for r in executed)
            performance.append(dict(checkpoint=checkpoint, case=case, logical_requests=len(logical),
                                    executed_inferences=len(executed), reused_requests=len(logical) - len(executed),
                                    total_executed_seconds=sum(times), mean_seconds=statistics.mean(times),
                                    median_seconds=statistics.median(times), p95_seconds=times[math.ceil(len(times) * .95) - 1],
                                    eos=ends['eos'], generation_timeout=ends['generation_timeout'],
                                    repetition_stop=ends['repetition_stop'], token_limit=ends['token_limit'],
                                    other_incomplete=sum(n for k, n in ends.items() if k not in {'eos', 'generation_timeout', 'repetition_stop', 'token_limit'}),
                                    logical_incomplete=sum(r['termination_reason'] != 'eos' for r in logical),
                                    gpu_peak_allocated_gib=max(float(r['gpu_peak_allocated_gib']) for r in executed),
                                    process_rss_peak_gib=max(float(r['process_rss_peak_gib']) for r in executed)))
        for basis in ['visual_provisional', 'native_pdf_reference']:
            for document in ['all', *[d['id'] for d in protocol['documents']]]:
                group = [f for f in fields if f['checkpoint'] == checkpoint and f['reference_basis'] == basis and
                         (document == 'all' or samples[f['sample_id']]['document_id'] == document)]
                accuracy.append(dict(checkpoint=checkpoint, document_id=document, reference_basis=basis,
                                     metric='provisional_field_accuracy' if basis == 'visual_provisional' else 'native_reference_consistency',
                                     **outcomes(group)))
    native_summary = [dict(method='native_pdf_mapper', document_id=document, reference_basis='visual_provisional',
                           **outcomes([r for r in native if document == 'all' or r['document_id'] == document]))
                      for document in ['all', *[d['id'] for d in protocol['documents']]]]
    csv_file(out / 'performance_summary.csv', performance)
    csv_file(out / 'accuracy_by_basis.csv', accuracy)
    csv_file(out / 'native_summary.csv', native_summary)
    csv_file(out / 'mapping_diagnostics.csv', diagnostics)
    lines = ['# 体检报告全目录测试', '',
             f"已完成 {len(protocol['documents'])} 份文件、{len(inventory)} 页/张的盘点；{protocol['logical_cases']} 个逻辑输入、{protocol['unique_cases']} 个图像与任务均不重复的输入。两个模型共 {len(requests)} 个逻辑请求、{audit['physical_inferences']} 次实际推理。输入及输出校验通过，两个模型进程均确认退出。", '',
             '输入为 3 份 PDF（22、22、21 页）与 1 张长照片。所有源文件、每页原生证据、分区图像、参考值、预测均保留并加密；公开数据只用 report-001 至 report-004 标识。', '',
             '## 准确率与一致率', '',
             '仅 3 张血常规页的 72 个结果字段有既有核图参考，尚未独立人工双标；本轮每个输入测一次。准确率包括缺失和错值，评的是项目名称映射后的 result_raw，不是全文字符准确率，也不覆盖完整报告、单位、范围或全部异常标志。', '',
             '| 模型 | 血常规正确/参考字段 | 暂定字段准确率 | 缺失 | 错值 | 原生表格参考一致/字段 | 一致率 |',
             '|---|---:|---:|---:|---:|---:|---:|']
    for checkpoint in protocol['checkpoints']:
        visual = next(r for r in accuracy if r['checkpoint'] == checkpoint and r['document_id'] == 'all' and r['reference_basis'] == 'visual_provisional')
        source = next(r for r in accuracy if r['checkpoint'] == checkpoint and r['document_id'] == 'all' and r['reference_basis'] == 'native_pdf_reference')
        lines.append(f"| {checkpoint} | {visual['correct']}/{visual['fields']} | {visual['fraction']:.2%} | {visual['missing']} | {visual['wrong']} | {source['correct']}/{source['fields']} | {source['fraction']:.2%} |")
    lines += ['', '9 张其他表格页的参考来自当前原生 PDF 表格提取，属于来源一致性检查，不能当成人工准确率。重复名称对应不同值的项目不计分。长照片及其他自动分区尚无完整参考，其准确率留空，不能由成功结束或映射项目数推导。', '',
              f"当前原生文字层路径共映射 {sum(int(p['native_medical_items']) for p in inventory)} 个项目，但对上述血常规 72 个参考结果，正确 {native_summary[0]['correct']}、缺失 {native_summary[0]['missing']}。这是文字层行列恢复/字段整理的缺口，与模型 OCR 错字独立；有文字层不保证获得完整项目表。", '',
              '## 时间与截断', '',
              '| 模型 / 输入范围 | 实际推理 | 平均秒 | 中位数秒 | P95 秒 | 总推理请求秒 | 正常结束 | 超时 | 重复停止 | 其他未完整 |',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for r in performance:
        lines.append(f"| {r['checkpoint']} / {r['case']} | {r['executed_inferences']} | {r['mean_seconds']:.3f} | {r['median_seconds']:.3f} | {r['p95_seconds']:.3f} | {r['total_executed_seconds']:.3f} | {r['eos']} | {r['generation_timeout']} | {r['repetition_stop']} | {r['token_limit'] + r['other_incomplete']} |")
    lines += ['', '耗时包含 IPC、推理、字段解析及计时范围内的整理；P95 为最近秩。超时/截断仍留在统计中。复用请求的 request_seconds 为空，其解析成本另列；不能将复用零成本或 deduplicated 总耗时当成当前程序的整份报告延迟。强制 OCR 的 12 张表格页与生产自动分区的 192 个区域分别记录；这些区域不是完整报告的语义覆盖证明。', '',
              f"实验墙钟 {(session['finished_at'] - session['started_at']):.3f} 秒（包括加载、预热、加密落盘等）。逐区域上限 45 秒、父进程硬上限 65 秒、最多 4096 token；本实验不是生产任务 180 秒整体时限的性能验收。", '',
              '## 加载及资源', '', '| 模型 | 加载/预热请求秒 | GPU allocated 峰值 GiB | 进程 RSS 峰值 GiB | 退出确认 |', '|---|---:|---:|---:|---|']
    for model in session['models']:
        r = next(r for r in performance if r['checkpoint'] == model['checkpoint'] and r['case'] == 'all_unique_inputs')
        lines.append(f"| {model['checkpoint']} | {model['load_request_seconds']:.3f} | {r['gpu_peak_allocated_gib']:.3f} | {max(r['process_rss_peak_gib'], model['metadata']['process_rss_peak_gib']):.3f} | {model['owned_process_exited']} |")
    lines += ['', '正式输入两版均使用 min/max pixels 147384/2822400，图片边长最多 1600；加载预热仍使用各 checkpoint 默认处理器。旧版是 Transformers 4.57.6 remote-code，1.6 是 Transformers 5.17.0 原生实现；不能把差异全部归于权重。模型始终串行、单模型驻留；GPU 指单模型 PyTorch allocated，RSS 是采样进程内存，不是双模型驻留总量。RTX 3060 12 GB、约 32 GB 主机，未验证 16 GB 人资电脑。', '',
              '## 可绘图数据与边界', '',
              '- [逐请求与终止原因](requests.csv)、[逐字段结果](fields.csv)、[分范围速度/资源](performance_summary.csv)。',
              '- [按参考来源及文件分组](accuracy_by_basis.csv)、[原生提取缺项](native_summary.csv)、[页路由盘点](inventory.csv)。',
              '- [映射诊断](mapping_diagnostics.csv)、[完整性验证](validation.json)；诊断中的原文出现次数不等于字段正确。', '',
              '同一家医院、既有样本有重叠、单轮全目录实验不能证明泛化。失败保留、未知准确率为空、confidence 未校准；本轮未实施医学分级、自动导出裁决、生产缓存或进一步 PDF 表格恢复。系统事件检查见 timing-audit.json；没有事件不证明没有其他负载或调度干扰。']
    (out / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(audit))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run_dir', type=Path)
    report(parser.parse_args().run_dir.resolve())
