"""Local application entry point; closing this process reclaims the worker Job tree."""
import argparse
import ctypes
import json
import msvcrt
import os
from pathlib import Path
import threading
import time
import uuid
import webbrowser

from .config import ROOT, RuntimeConfig
from .diagnostics import init_diagnostics, DEFAULT_ROOT


def main():
    diagnostic = init_diagnostics(DEFAULT_ROOT, 'launcher')
    diagnostic.event('bootstrap_started')
    os.environ['OCR_DIAGNOSTICS_ROOT'] = str(DEFAULT_ROOT)
    os.environ['OCR_DIAGNOSTICS_SESSION'] = diagnostic.session_id
    try:
        return launch(diagnostic)
    except SystemExit as error:
        if error.code:
            diagnostic.exception('bootstrap_failed', error)
        raise
    except Exception as error:
        error_id = diagnostic.exception('launcher_failed', error)
        print(f'程序启动失败。错误编号：{error_id}。请运行 collect-diagnostics.cmd 收集日志。', flush=True)
        raise SystemExit(1) from None
    finally:
        diagnostic.close()


def launch(diagnostic):
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=('dual_resident',), help='Production always keeps both models resident')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    parser.add_argument('--model-batch-size', type=int, choices=(1, 2), default=2)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('port must be between 1024 and 65535')
    runtime_root = ROOT / '.runtime'
    runtime_root.mkdir(exist_ok=True)
    preference = runtime_root / 'settings.json'
    mode = 'dual_resident'
    # Shared with offline experiment runners. Process exit releases this Windows byte lock.
    (ROOT / 'output').mkdir(exist_ok=True)
    with (ROOT / 'output/two-model-retest-gpu.lock').open('a+b') as lease:
        if lease.tell() == 0:
            lease.write(b'1')
            lease.flush()
        lease.seek(0)
        try:
            msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            parser.exit(2, 'OCR runtime or benchmark already owns the GPU execution channel.\n')
        temporary = preference.with_suffix('.tmp')
        temporary.write_text(json.dumps({'mode': mode}), encoding='utf-8')
        temporary.replace(preference)
        session = runtime_root / (time.strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8])
        from .api import create_app
        from .client import RuntimeClient
        from .business import Business
        import uvicorn
        business = Business(runtime_root / 'data', diagnostic)
        business.prepare()
        runtime = RuntimeClient(RuntimeConfig(session, mode, data_root=business.root,
                                              model_batch_size=args.model_batch_size))
        app = create_app(runtime, ROOT / 'frontend/dist', session, business=business, logger=diagnostic)
        server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=args.port, access_log=False,
                                             proxy_headers=False, log_level='warning'))
        if not args.no_browser and (ROOT / 'frontend/dist/index.html').is_file():
            def open_when_serving():
                for _ in range(150):
                    if server.started:
                        webbrowser.open(f'http://127.0.0.1:{args.port}/')
                        return
                    if server.should_exit:
                        return
                    time.sleep(.1)
            threading.Thread(target=open_when_serving, daemon=True).start()
        print(f'Local OCR: http://127.0.0.1:{args.port}/  mode={mode}', flush=True)
        print('Close this launcher window or press Ctrl+C to exit. Closing the browser tab does not stop OCR.', flush=True)
        print('使用账号密码登录工作台；管理员可在账号管理中创建账号。诊断日志：运行 collect-diagnostics.cmd。', flush=True)
        # Avoid sleep corrupting active startup/probe timing; restored on normal process exit.
        sleep_guard = ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
        try:
            server.run()
        finally:
            runtime.close()
            if sleep_guard:
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


if __name__ == '__main__':
    main()
