"""Real, private-runtime acceptance on a synthetic input; one probe owns the GPU lease."""
import argparse
import ctypes
from ctypes import wintypes
import json
import math
import msvcrt
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from ocr_app.client import RuntimeClient
from ocr_app.config import RuntimeConfig
import psutil


_kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL


class OwnedProcesses:
    """Keep non-inherited synchronization handles while owned processes are alive.

    A terminated process may still have a visible PID while handles are open;
    only the process handle's signaled state is used for exit acceptance.
    """

    def __init__(self):
        self.items = {}
        self.errors = []
        self.lock = threading.Lock()

    def remember(self, process, role='descendant'):
        with self.lock:
            birth = process.create_time()
            key = (process.pid, birth)
            if key in self.items:
                if role != 'descendant':
                    self.items[key]['role'] = role
                return
            handle = _kernel32.OpenProcess(0x00100000, False, process.pid)  # SYNCHRONIZE
            if not handle:
                code = ctypes.get_last_error()
                if code == 87:  # Already gone before OpenProcess; no live object to retain.
                    return
                raise ctypes.WinError(code)
            try:
                # Do not attach a reused PID to the previously observed process.
                if psutil.Process(process.pid).create_time() != birth:
                    return
                self.items[key] = dict(pid=process.pid, create_time=birth, role=role, handle=handle)
                handle = None
            finally:
                if handle:
                    _kernel32.CloseHandle(handle)

    def wait_all(self, timeout=5.0):
        started = time.monotonic()
        deadline = started + timeout
        rows = []
        with self.lock:
            for item in self.items.values():
                milliseconds = max(0, math.ceil((deadline - time.monotonic()) * 1000))
                code = _kernel32.WaitForSingleObject(item['handle'], milliseconds)
                row = {key: value for key, value in item.items() if key != 'handle'}
                row.update(signaled=code == 0, wait_result=int(code))
                if code not in (0, 258):
                    row['winerror'] = ctypes.get_last_error()
                rows.append(row)
        return rows, time.monotonic() - started

    def close(self):
        with self.lock:
            for item in self.items.values():
                if not _kernel32.CloseHandle(item['handle']):
                    self.errors.append(dict(type='CloseHandleError', pid=item['pid'],
                                            winerror=ctypes.get_last_error()))
            self.items.clear()


def error_record(error):
    return dict(type=type(error).__name__, message=str(error))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['dual_resident', 'single_resident'], required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--image', type=Path, required=True)
    args = ap.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    result = dict(mode=args.mode, hardware=dict(host_ram_gib=psutil.virtual_memory().total / 2**30),
                  scope='synthetic smoke test; not document accuracy or target HR hardware validation',
                  stages=[], memory_samples=[], status='failed')
    client = None
    stop = threading.Event()
    owned = OwnedProcesses()
    started = time.monotonic()
    lease = None
    monitor = None

    def remember_tree():
        if client and client.process:
            try:
                parent = psutil.Process(client.process.pid)
                owned.remember(parent, 'runtime')
                for process in parent.children(recursive=True):
                    try:
                        owned.remember(process)
                    except psutil.NoSuchProcess:
                        pass
            except psutil.NoSuchProcess:
                pass

    def sample():
        while not stop.wait(.25):
            used = psutil.virtual_memory()
            row = dict(seconds=time.monotonic() - started,
                       host_used_gib=(used.total - used.available) / 2**30, host_available_gib=used.available / 2**30,
                       owned_sum_rss_gib=0, owned_sum_private_gib=0)
            if client and client.process:
                try:
                    parent = psutil.Process(client.process.pid)
                    for proc in [parent] + parent.children(recursive=True):
                        try:
                            memory = proc.memory_info()
                            owned.remember(proc, 'runtime' if proc.pid == parent.pid else 'descendant')
                            row['owned_sum_rss_gib'] += memory.rss / 2**30
                            row['owned_sum_private_gib'] += getattr(memory, 'private', 0) / 2**30
                        except psutil.Error:
                            pass
                        except OSError as error:
                            owned.errors.append(error_record(error))
                except psutil.Error:
                    pass
            result['memory_samples'].append(row)
    try:
        client = RuntimeClient(RuntimeConfig(out, args.mode))
        lease = (ROOT / 'output/two-model-retest-gpu.lock').open('a+b')
        lease.seek(0)
        msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
        monitor = threading.Thread(target=sample, daemon=True)
        monitor.start()
        client.start()
        remember_tree()
        while client.snapshot()['state'] == 'starting':
            if time.monotonic() - started > 260:
                raise TimeoutError('Startup did not stabilize')
            time.sleep(.1)
        result['startup_seconds'] = time.monotonic() - started
        result['startup'] = client.snapshot()
        print(json.dumps({'event': 'startup', 'seconds': result['startup_seconds'], 'runtime': result['startup']}), flush=True)
        expected = 2 if args.mode == 'dual_resident' else 1
        assert sum(s == 'ready' for s in result['startup']['models'].values()) == expected, result['startup']
        assert result['startup']['effective_mode'] == args.mode, result['startup']
        result['startup_statistics'] = client.request('statistics', wait=5)
        initial_pids = result['startup_statistics']['model_pids']
        assert len(initial_pids) == expected, initial_pids
        for model, pid in initial_pids.items():
            owned.remember(psutil.Process(pid), model)
        time.sleep(1)
        for model in ['glm_ocr', 'paddleocr_vl', 'glm_ocr']:
            before = time.monotonic()
            prediction = client.request('recognize', model=model, image=str(args.image.resolve()), max_new_tokens=96)
            stats = client.request('statistics', wait=5)
            result['stages'].append(dict(model=model, wall_seconds=time.monotonic() - before,
                                         result=prediction, statistics=stats))
            for resident, pid in stats['model_pids'].items():
                owned.remember(psutil.Process(pid), resident)
            checks = dict(synthetic_exact_match=prediction.get('text') == 'LOCAL OCR CHECK 123456',
                          eos=prediction.get('termination_reason') == 'eos',
                          expected_mode=stats['runtime']['effective_mode'] == args.mode,
                          resident_count=len(stats['model_pids']) == expected,
                          ready_count=sum(value == 'ready' for value in stats['runtime']['models'].values()) == expected)
            if args.mode == 'dual_resident':
                checks['dual_pids_reused'] = stats['model_pids'] == initial_pids
            else:
                checks['single_requested_model_only'] = set(stats['model_pids']) == {model}
                # Include previously seen models: registry removal alone cannot prove exit.
                with owned.lock:
                    active_models = [item['pid'] for item in owned.items.values()
                                     if item['role'] in ('glm_ocr', 'paddleocr_vl')
                                     and _kernel32.WaitForSingleObject(item['handle'], 0) != 0]
                checks['single_live_model_only'] = active_models == [stats['model_pids'][model]]
            result['stages'][-1]['checks'] = checks
            print(json.dumps({'event': 'recognized', 'model': model, 'text': prediction['text'],
                              'runtime': stats['runtime'], 'pids': stats['model_pids']}), flush=True)
            assert all(checks.values()), checks
        result['status'] = 'passed'
    except BaseException as error:
        result['probe_error'] = error_record(error)
        result.update(status='failed', error_type=type(error).__name__, error=str(error))
    finally:
        stop.set()
        if monitor and monitor.ident is not None:
            monitor.join(timeout=2)
            if monitor.is_alive():
                owned.errors.append(dict(type='MonitorStillRunning'))
        try:
            remember_tree()
        except Exception as error:
            owned.errors.append(error_record(error))
        cleanup = time.monotonic()
        try:
            if client:
                client.close()
        except BaseException as error:
            result['close_error'] = error_record(error)
            result['status'] = 'failed'
        result['cleanup_seconds'] = time.monotonic() - cleanup
        try:
            result['cleanup_wait_budget_seconds'] = 5.0
            result['owned_exit_checks'], result['cleanup_wait_seconds'] = owned.wait_all(5.0)
            result['remaining_owned_processes'] = [row['pid'] for row in result['owned_exit_checks']
                                                    if row['wait_result'] == 258]
            if any(not row['signaled'] for row in result['owned_exit_checks']):
                result['cleanup_error'] = dict(type='CleanupIncomplete',
                                               message='Owned process handles did not all signal before shared deadline')
                result['status'] = 'failed'
        except BaseException as error:
            result['cleanup_error'] = error_record(error)
            result['status'] = 'failed'
        finally:
            owned.close()
            if owned.errors:
                result['ownership_errors'] = owned.errors
                result['status'] = 'failed'
            result['wall_seconds'] = time.monotonic() - started
            for name in ['owned_sum_rss_gib', 'owned_sum_private_gib', 'host_used_gib']:
                result['peak_' + name] = max((r[name] for r in result['memory_samples']), default=None)
            try:
                (out / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
            finally:
                if lease:
                    lease.close()
    if result['status'] != 'passed':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
