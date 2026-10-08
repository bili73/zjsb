"""Real lightweight Windows process tests; no OCR imports or dependencies."""

import ctypes as C
from ctypes import wintypes as W
import json
import os
from pathlib import Path
import queue
import sys
import tempfile
import threading
import unittest

from backend.ocr_app.winjob import JobError, JobProcess

ROOT = Path(__file__).resolve().parents[1]


def python(code):
    return [sys.executable, "-u", "-X", "utf8", "-c", code]


@unittest.skipUnless(os.name == "nt", "Windows Job Objects required")
class JobProcessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kernel = C.WinDLL("kernel32", use_last_error=True)
        cls.kernel.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
        cls.kernel.OpenProcess.restype = W.HANDLE
        cls.kernel.WaitForSingleObject.argtypes = [W.HANDLE, W.DWORD]
        cls.kernel.WaitForSingleObject.restype = W.DWORD
        cls.kernel.CloseHandle.argtypes = [W.HANDLE]
        cls.kernel.CloseHandle.restype = W.BOOL
        cls.kernel.GetCurrentProcess.restype = W.HANDLE
        cls.kernel.GetProcessHandleCount.argtypes = [W.HANDLE, C.POINTER(W.DWORD)]
        cls.kernel.GetProcessHandleCount.restype = W.BOOL
        cls.kernel.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
        cls.kernel.TerminateProcess.restype = W.BOOL

    def launch(self, code, **kwargs):
        process = JobProcess(python(code), **kwargs)
        self.addCleanup(process.close)
        return process

    def line(self, stream):
        result = queue.Queue()
        def read():
            try:
                result.put(stream.readline())
            except BaseException as error:
                result.put(error)
        thread = threading.Thread(target=read, daemon=True)
        thread.start()
        value = result.get(timeout=10)
        if isinstance(value, BaseException):
            raise value
        self.assertTrue(value, "child unexpectedly closed stdout")
        thread.join(timeout=1)
        return value.rstrip("\r\n")

    def process_handle(self, pid, terminate=False):
        handle = self.kernel.OpenProcess(0x00100000 | int(terminate), False, pid)
        self.assertTrue(handle, f"OpenProcess({pid}) failed: {C.get_last_error()}")
        self.addCleanup(self.kernel.CloseHandle, handle)
        return handle

    def assert_exited(self, handle):
        self.assertEqual(self.kernel.WaitForSingleObject(handle, 5000), 0)

    @staticmethod
    def tree_code():
        return """import os,sys,subprocess,json,time
p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(300)'],
    stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
    creationflags=subprocess.CREATE_NO_WINDOW)
print(json.dumps([os.getpid(),p.pid]),flush=True)
time.sleep(300)
"""

    def test_unicode_stdio_arguments_cwd_and_environment(self):
        with tempfile.TemporaryDirectory(prefix="ocr-winjob-") as directory:
            env = {**os.environ, "WINJOB_TEST_VALUE": "环境✓"}
            code = """import sys,os,json
print(json.dumps([os.getcwd(),os.environ['WINJOB_TEST_VALUE'],sys.argv[1:]],ensure_ascii=False),flush=True)
line=sys.stdin.readline().rstrip('\\n')
print('收到:'+line,flush=True)
print('错误流✓',file=sys.stderr,flush=True)
"""
            args = python(code) + ["参数 空格", 'quote"slash\\', ""]
            with JobProcess(args, cwd=directory, env=env) as p:
                values = json.loads(self.line(p.stdout))
                self.assertEqual(Path(values[0]), Path(directory))
                self.assertEqual(values[1:], ["环境✓", args[-3:]])
                self.assertIsNone(p.poll())
                p.stdin.write("中文回传✓\n")  # line-buffered; no explicit flush
                self.assertEqual(self.line(p.stdout), "收到:中文回传✓")
                self.assertEqual(self.line(p.stderr), "错误流✓")
                self.assertEqual(p.wait(5), 0)
                self.assertEqual(p.poll(), 0)
            p.close()
            self.assertTrue(p.stdin.closed and p.stdout.closed and p.stderr.closed)

    def test_timeout_and_exit_code_259_is_not_running(self):
        p = self.launch("import sys; sys.stdin.readline(); sys.exit(259)")
        with self.assertRaises(TimeoutError):
            p.wait(0.02)
        p.stdin.write("exit\n")
        self.assertEqual(p.wait(5), 259)
        self.assertEqual(p.poll(), 259)

    def test_kill_tree_does_not_kill_another_owned_process(self):
        target = self.launch(self.tree_code())
        pids = json.loads(self.line(target.stdout))
        handles = [self.process_handle(pid) for pid in pids]
        survivor = self.launch("import time; print('alive',flush=True); time.sleep(300)")
        self.assertEqual(self.line(survivor.stdout), "alive")
        target.kill_tree()
        for handle in handles:
            self.assert_exited(handle)
        self.assertIsNotNone(target.poll())
        self.assertIsNone(survivor.poll())

    def test_close_reaps_descendant_after_direct_process_exits(self):
        code = self.tree_code().replace("time.sleep(300)\n", "sys.stdin.readline()\n")
        p = self.launch(code)
        pids = json.loads(self.line(p.stdout))
        grandchild = self.process_handle(pids[1])
        p.stdin.write("exit\n")
        self.assertEqual(p.wait(5), 0)
        self.assertEqual(self.kernel.WaitForSingleObject(grandchild, 0), 0x102)
        p.close()
        self.assert_exited(grandchild)

    def assert_owner_cleanup(self, external_kill):
        # The outer Job stays open throughout. Only the abruptly exiting owner
        # holds the inner Job handle; no Python finally/atexit cleanup runs.
        code = f"""import os,sys
from backend.ocr_app.winjob import JobProcess
child=JobProcess({python(self.tree_code())!r})
print(child.stdout.readline(),end='',flush=True)
sys.stdin.readline()
os._exit(31)
"""
        owner = self.launch(code, cwd=ROOT)
        pids = json.loads(self.line(owner.stdout))
        handles = [self.process_handle(pid) for pid in pids]
        if external_kill:
            handle = self.process_handle(owner.pid, terminate=True)
            self.assertTrue(self.kernel.TerminateProcess(handle, 31))
        else:
            owner.stdin.write("crash\n")
        self.assertEqual(owner.wait(5), 31)
        for handle in handles:
            self.assert_exited(handle)

    def test_abrupt_owner_exit_reaps_nested_job_descendants(self):
        self.assert_owner_cleanup(external_kill=False)

    def test_external_owner_kill_reaps_nested_job_descendants(self):
        self.assert_owner_cleanup(external_kill=True)

    def test_close_while_another_thread_waits(self):
        p = self.launch("import time; print('ready',flush=True); time.sleep(300)")
        self.assertEqual(self.line(p.stdout), "ready")
        result = queue.Queue()
        entered = threading.Event()
        def wait():
            entered.set()
            try:
                result.put(p.wait(5))
            except BaseException as error:
                result.put(error)
        thread = threading.Thread(target=wait, daemon=True)
        thread.start()
        self.assertTrue(entered.wait(1))
        p.close()
        value = result.get(timeout=6)
        self.assertEqual(value, 1)
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())

    def test_spawn_failure_closes_native_handles(self):
        def count():
            value = W.DWORD()
            self.assertTrue(self.kernel.GetProcessHandleCount(self.kernel.GetCurrentProcess(), C.byref(value)))
            return value.value
        with tempfile.TemporaryDirectory(prefix="ocr-winjob-") as directory:
            missing = str(Path(directory) / "missing.exe")
            with self.assertRaises(JobError):
                JobProcess([missing])
            before = count()
            for _ in range(20):
                with self.assertRaises(JobError):
                    JobProcess([missing])
            self.assertEqual(count(), before)


if __name__ == "__main__":
    unittest.main()
