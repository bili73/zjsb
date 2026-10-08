"""Report frozen diagnostics without exposing private reference or predicted values."""
import argparse
from collections import defaultdict
import csv
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from ocr_app.storage import Storage
from compare_schema_extraction import digest, save


def report(out):
    protocol = json.loads((out / 'protocol.json').read_text())
    session = json.loads((out / 'session.json').read_text())
    with (out / 'requests.csv').open(encoding='utf-8-sig', newline='') as stream:
        requests = list(csv.DictReader(stream))
    with (out / 'summary.csv').open(encoding='utf-8-sig', newline='') as stream:
        summary = list(csv.DictReader(stream))
    storage = Storage(out / 'private/data')
    encrypted = (out / 'private/fixture.enc').read_bytes()
    fixture = storage.unpack(encrypted)
    hashes_ok = digest(encrypted) == protocol['fixture_sha256'] and all(
        digest(storage.read(s['image_ref'])) == s['input_sha256'] for s in fixture['samples'])
    repeated = defaultdict(list)
    for row in requests:
        repeated[(row['sample_id'], row['method'])].append(
            json.loads(storage.read(row['prediction_ref']))['values'])
    changed = [dict(sample_id=sample, method=method) for (sample, method), values in repeated.items()
               if len(values) != protocol['repeats'] or any(v != values[0] for v in values[1:])]
    # Only sample IDs leave this grouping; personal values never enter the report.
    groups = defaultdict(list)
    for sample in fixture['samples']:
        if sample['doc_type'] == 'BANK_CARD':
            continue
        refs = sample['reference']
        parts = [refs.get(k, {}).get('value') for k in ['name', 'certificate_no']]
        if all(parts):
            groups[digest(json.dumps(parts, ensure_ascii=False).encode())].append(sample['id'])
    formal = [r for r in requests if r['termination_reason'] != 'derived']
    audit = dict(status='passed' if hashes_ok and session['status'] == 'finished' and
                 all(m.get('owned_process_exited') for m in session['models']) else 'failed',
                 hashes_valid=hashes_ok, formal_requests=len(formal), planned_formal_requests=56,
                 termination_counts={k: sum(r['termination_reason'] == k for r in formal)
                                     for k in sorted({r['termination_reason'] for r in formal})},
                 repeat_value_changes=changed,
                 possible_same_document_groups=[ids for ids in groups.values() if len(ids) > 1],
                 confidence_calibrated=False, production_fusion_adopted=False)
    save(out / 'validation.json', audit)
    lines = ['# 卡证双模型诊断', '',
             f"状态：{session['status']}；正式 GPU 调用 {len(formal)}/56；输入 4 张学历证书图片、3 张银行卡正面图片，每条路径重复 2 次。", '',
             '学历每轮有 39 个确定存在字段、4 个确定不存在字段、6 个无法确定字段。两轮分母为 78/8/12。银行卡每轮只评卡号，两轮分母为 6。参考由 Agent 核图，尚未独立人工双标。图片输入数不等于独立人员/证书数。', '',
             '规则路径评的是字段映射准确率，不能视为全文字符准确率。JSON 合同失败使该请求字段记为缺失，失败仍保留在分母。不存在字段的误填单列；无法确定字段不计分。', '']
    for kind, title in [('CERTIFICATES', '学历字段'), ('BANK_CARD', '银行卡号')]:
        lines += [f'## {title}', '', '| 路径 | 正确/存在字段 | 准确率 | 缺失 | 错值 | 不存在字段误填 | 平均请求秒 |',
                  '|---|---:|---:|---:|---:|---:|---:|']
        for row in summary:
            if row['doc_type'] == kind:
                lines.append(f"| {row['method']} | {row['correct']}/{row['present_fields']} | "
                             f"{float(row['field_accuracy']):.2%} | {row['missing']} | {row['wrong']} | "
                             f"{row['false_positives']}/{row['absent_fields']} | {float(row['mean_request_seconds']):.3f} |")
        lines += ['']
    lines += ['## 计时与资源边界', '',
              '单路径请求包含 IPC、识别及字段解析；合并和提示词联合路径包含完整 Paddle 与 GLM 请求的串行总成本。加载及合成预热单列，模型环境的文件缓存未清除，不能把首轮和后续加载差异当成模型速度提升。', '',
              '| 模型 | checkpoint | 加载及预热请求秒 | revision | 退出确认 |', '|---|---|---:|---|---|']
    for model in session['models']:
        loading = model['loading']
        lines.append(f"| {model['model']} | {loading.get('checkpoint', model['model'])} | "
                     f"{model['load_request_seconds']:.3f} | {loading['revision']} | {model['owned_process_exited']} |")
    lines += ['', '显存为单模型 PyTorch allocator 峰值；进程 RAM 为单模型采样 RSS，联合路径取两阶段最大值，并非同时驻留两个模型的总内存。硬件为 RTX 3060 12 GB、主机约 32 GB，不能据此承诺 16 GB 人资电脑可用。', '',
              '## 解读', '',
              'v1、v2、新版 Paddle 实验使用各自冻结协议。v2 是在观察 v1 后修改提示词的同样本探索；直接 GLM 与提示词联合路径在每轮使用同一基础模板。跨轮变化可能来自模板、模型或适配环境，不能全部归因于双模型。', '',
              '一致输出只表示两个候选相同，不表示它们一定正确。agreement_only 必须同时看覆盖率，所有字段 confidence 仍为空且需要人工审核。merge_preview 的冲突标记用于复核，不自动裁决真值。生产尚未采用这些融合路径。', '',
              f"冻结输入校验：{hashes_ok}；重复值变化组：{len(changed)}；可能同一证书的多图组：{audit['possible_same_document_groups']}。", '',
              '绘图数据：[请求](requests.csv)、[字段](fields.csv)、[汇总](summary.csv)。私有图片、参考和预测以 AES-GCM 保存，密钥由当前 Windows 用户 DPAPI 保护。公开 CSV 不含姓名、卡号、证书号或原文。', '',
              '系统休眠/重启窗口检查见 timing-audit.json（若存在）；没有匹配事件不证明没有其他卡顿。']
    (out / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(audit, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('run_dir', type=Path)
    report(parser.parse_args().run_dir)
