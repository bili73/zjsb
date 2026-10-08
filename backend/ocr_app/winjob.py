"""Windows 10+ process trees, atomically assigned to kill-on-close Jobs.

The owner must keep this object alive and call close(). If the owner process
exits, Windows closes its non-inherited Job handle and kills the owned tree.
Reader threads belong to the caller; child programs must emit UTF-8.

Decision: .agents/notes/implemented/architecture/2026-09-29-local-dual-model-lifecycle.md
WinAPI: https://learn.microsoft.com/windows/win32/procthread/job-objects
https://learn.microsoft.com/windows/win32/api/processthreadsapi/nf-processthreadsapi-updateprocthreadattribute
"""

import ctypes as C
from ctypes import wintypes as W
import io
import math
import os
from pathlib import Path
import shutil
import subprocess
import threading
import time


class JobError(OSError):
    """A WinAPI operation failed; winerror identifies the native failure."""


class _SecurityAttributes(C.Structure):
    _fields_ = [("nLength", W.DWORD), ("lpSecurityDescriptor", W.LPVOID),
                ("bInheritHandle", W.BOOL)]


class _StartupInfo(C.Structure):
    _fields_ = [("cb", W.DWORD), ("lpReserved", W.LPWSTR),
                ("lpDesktop", W.LPWSTR), ("lpTitle", W.LPWSTR)] + [
        (name, W.DWORD) for name in (
            "dwX", "dwY", "dwXSize", "dwYSize", "dwXCountChars",
            "dwYCountChars", "dwFillAttribute", "dwFlags")
    ] + [("wShowWindow", W.WORD), ("cbReserved2", W.WORD),
         ("lpReserved2", C.POINTER(W.BYTE)), ("hStdInput", W.HANDLE),
         ("hStdOutput", W.HANDLE), ("hStdError", W.HANDLE)]


class _StartupInfoEx(C.Structure):
    _fields_ = [("StartupInfo", _StartupInfo), ("lpAttributeList", W.LPVOID)]


class _ProcessInformation(C.Structure):
    _fields_ = [("hProcess", W.HANDLE), ("hThread", W.HANDLE),
                ("dwProcessId", W.DWORD), ("dwThreadId", W.DWORD)]


class _BasicLimits(C.Structure):
    _fields_ = [("PerProcessUserTimeLimit", C.c_longlong),
                ("PerJobUserTimeLimit", C.c_longlong), ("LimitFlags", W.DWORD),
                ("MinimumWorkingSetSize", C.c_size_t),
                ("MaximumWorkingSetSize", C.c_size_t),
                ("ActiveProcessLimit", W.DWORD), ("Affinity", C.c_size_t),
                ("PriorityClass", W.DWORD), ("SchedulingClass", W.DWORD)]


class _IoCounters(C.Structure):
    _fields_ = [(name, C.c_ulonglong) for name in (
        "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
        "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]


class _ExtendedLimits(C.Structure):
    _fields_ = [("BasicLimitInformation", _BasicLimits), ("IoInfo", _IoCounters),
                ("ProcessMemoryLimit", C.c_size_t), ("JobMemoryLimit", C.c_size_t),
                ("PeakProcessMemoryUsed", C.c_size_t),
                ("PeakJobMemoryUsed", C.c_size_t)]


class _Accounting(C.Structure):
    _fields_ = [(name, C.c_longlong) for name in (
        "TotalUserTime", "TotalKernelTime", "ThisPeriodTotalUserTime",
        "ThisPeriodTotalKernelTime")
    ] + [(name, W.DWORD) for name in (
        "TotalPageFaultCount", "TotalProcesses", "ActiveProcesses",
        "TotalTerminatedProcesses")]


if os.name == "nt":
    import msvcrt

    _kernel = C.WinDLL("kernel32", use_last_error=True)

    def _api(name, result, *args):
        fn = getattr(_kernel, name)
        fn.restype, fn.argtypes = result, list(args)
        return fn

    _create_job = _api("CreateJobObjectW", W.HANDLE, W.LPVOID, W.LPCWSTR)
    _set_job = _api("SetInformationJobObject", W.BOOL, W.HANDLE, C.c_int,
                    W.LPVOID, W.DWORD)
    _query_job = _api("QueryInformationJobObject", W.BOOL, W.HANDLE, C.c_int,
                      W.LPVOID, W.DWORD, W.LPVOID)
    _terminate_job = _api("TerminateJobObject", W.BOOL, W.HANDLE, W.UINT)
    _close_handle = _api("CloseHandle", W.BOOL, W.HANDLE)
    _create_pipe = _api("CreatePipe", W.BOOL, C.POINTER(W.HANDLE),
                        C.POINTER(W.HANDLE), C.POINTER(_SecurityAttributes), W.DWORD)
    _set_handle = _api("SetHandleInformation", W.BOOL, W.HANDLE, W.DWORD, W.DWORD)
    _init_attributes = _api("InitializeProcThreadAttributeList", W.BOOL,
                            W.LPVOID, W.DWORD, W.DWORD, C.POINTER(C.c_size_t))
    _update_attribute = _api("UpdateProcThreadAttribute", W.BOOL, W.LPVOID,
                             W.DWORD, C.c_size_t, W.LPVOID, C.c_size_t,
                             W.LPVOID, W.LPVOID)
    _delete_attributes = _api("DeleteProcThreadAttributeList", None, W.LPVOID)
    _create_process = _api("CreateProcessW", W.BOOL, W.LPCWSTR, W.LPWSTR,
                           W.LPVOID, W.LPVOID, W.BOOL, W.DWORD, W.LPVOID,
                           W.LPCWSTR, C.POINTER(_StartupInfoEx),
                           C.POINTER(_ProcessInformation))
    _wait = _api("WaitForSingleObject", W.DWORD, W.HANDLE, W.DWORD)
    _exit_code = _api("GetExitCodeProcess", W.BOOL, W.HANDLE, C.POINTER(W.DWORD))
    _current_process = _api("GetCurrentProcess", W.HANDLE)
    _duplicate = _api("DuplicateHandle", W.BOOL, W.HANDLE, W.HANDLE,
                      W.HANDLE, C.POINTER(W.HANDLE), W.DWORD, W.BOOL, W.DWORD)


def _checked(result, operation):
    if not result:
        code = C.get_last_error()
        raise JobError(0, f"{operation}: {C.FormatError(code).strip()}", None, code)
    return result


class JobProcess:
    """One directly launched process and every descendant in its Job.

    env=None inherits the environment; a dict replaces it, like Popen.
    wait()/poll() concern the direct process. kill_tree() verifies the entire
    Job is empty, with a five-second cleanup deadline. close() also terminates
    descendants left behind after a normal direct-process exit, then closes
    handles and streams. Calls that mutate lifetime belong to one owner thread;
    independent reader threads and concurrent wait() are supported.
    """

    def __init__(self, args: list[str], cwd: Path | str = None, env: dict = None):
        if os.name != "nt":
            raise OSError("JobProcess requires Windows 10 or newer")
        if not args or not all(isinstance(a, str) and "\0" not in a for a in args):
            raise ValueError("args must be a nonempty list of strings without NUL")
        self._job = self._process = None
        self._returncode = None
        self._closed = False
        self._lock = threading.RLock()
        self.stdin = self.stdout = self.stderr = None
        self.pid = None
        workdir = str(Path(cwd).resolve()) if cwd is not None else None
        executable = args[0]
        if not Path(executable).is_absolute():
            if os.path.dirname(executable):
                executable = str((Path(workdir or os.getcwd()) / executable).resolve())
            else:
                executable = shutil.which(executable, path=(env or os.environ).get("PATH")) or executable
        command = C.create_unicode_buffer(subprocess.list2cmdline([executable, *args[1:]]))
        environment = None
        if env is not None:
            if any(not isinstance(k, str) or not isinstance(v, str) or not k
                   or "=" in k or "\0" in k or "\0" in v for k, v in env.items()):
                raise ValueError("env must contain valid string keys and values")
            environment = C.create_unicode_buffer(
                "\0".join(f"{k}={v}" for k, v in sorted(env.items(), key=lambda kv: kv[0].upper())) + "\0\0")
        handles = []
        attributes = None
        initialized = False
        info = _ProcessInformation()
        try:
            self._job = _checked(_create_job(None, None), "CreateJobObjectW")
            limits = _ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE; no breakaway
            _checked(_set_job(self._job, 9, C.byref(limits), C.sizeof(limits)), "SetInformationJobObject")
            security = _SecurityAttributes(C.sizeof(_SecurityAttributes), None, True)

            def pipe(parent_reads):
                read, write = W.HANDLE(), W.HANDLE()
                _checked(_create_pipe(C.byref(read), C.byref(write), C.byref(security), 0), "CreatePipe")
                handles.extend([read.value, write.value])
                parent, child = (read.value, write.value) if parent_reads else (write.value, read.value)
                _checked(_set_handle(parent, 1, 0), "SetHandleInformation")
                return parent, child

            parent_in, child_in = pipe(False)
            parent_out, child_out = pipe(True)
            parent_err, child_err = pipe(True)
            size = C.c_size_t()
            # The first call deliberately requests the required buffer size.
            _init_attributes(None, 2, 0, C.byref(size))
            if not size.value:
                _checked(False, "InitializeProcThreadAttributeList(size)")
            attributes = C.create_string_buffer(size.value)
            _checked(_init_attributes(attributes, 2, 0, C.byref(size)), "InitializeProcThreadAttributeList")
            initialized = True
            jobs = (W.HANDLE * 1)(self._job)
            inherited = (W.HANDLE * 3)(child_in, child_out, child_err)
            _checked(_update_attribute(attributes, 0, 0x2000D, jobs, C.sizeof(jobs), None, None),
                     "UpdateProcThreadAttribute(JOB_LIST)")
            _checked(_update_attribute(attributes, 0, 0x20002, inherited, C.sizeof(inherited), None, None),
                     "UpdateProcThreadAttribute(HANDLE_LIST)")
            startup = _StartupInfoEx()
            startup.StartupInfo.cb = C.sizeof(startup)
            startup.StartupInfo.dwFlags = 0x100 | 0x1  # USESTDHANDLES | USESHOWWINDOW
            startup.StartupInfo.wShowWindow = 0  # SW_HIDE
            startup.StartupInfo.hStdInput = child_in
            startup.StartupInfo.hStdOutput = child_out
            startup.StartupInfo.hStdError = child_err
            startup.lpAttributeList = C.cast(attributes, W.LPVOID)
            flags = 0x00080000 | 0x08000000 | 0x00000400  # EXTENDED_STARTUPINFO, NO_WINDOW, UNICODE_ENV
            _checked(_create_process(executable, command, None, None, True, flags,
                                     environment, workdir, C.byref(startup), C.byref(info)), "CreateProcessW")
            self._process, self.pid = info.hProcess, info.dwProcessId
            _close_handle(info.hThread)
            info.hThread = None
            for handle in (child_in, child_out, child_err):
                _close_handle(handle)
                handles.remove(handle)

            def stream(handle, mode):
                flags = os.O_BINARY | (os.O_WRONLY if mode == "w" else os.O_RDONLY)
                fd = msvcrt.open_osfhandle(handle, flags)
                handles.remove(handle)  # fd owns the handle after open_osfhandle succeeds
                try:
                    os.set_inheritable(fd, False)
                    return io.open(fd, mode, buffering=1, encoding="utf-8", newline="\n" if mode == "w" else None)
                except BaseException:
                    os.close(fd)
                    raise

            self.stdin = stream(parent_in, "w")
            self.stdout = stream(parent_out, "r")
            self.stderr = stream(parent_err, "r")
        except BaseException:
            self.close()
            raise
        finally:
            if initialized:
                _delete_attributes(attributes)
            for handle in handles:
                _close_handle(handle)

    def poll(self) -> int | None:
        with self._lock:
            if self._returncode is not None or self._process is None:
                return self._returncode
            state = _wait(self._process, 0)
            if state == 0x102:
                return None
            if state != 0:
                _checked(False, "WaitForSingleObject")
            code = W.DWORD()
            _checked(_exit_code(self._process, C.byref(code)), "GetExitCodeProcess")
            self._returncode = code.value
            return self._returncode

    def wait(self, timeout: float | None = None) -> int:
        if timeout is not None and (not math.isfinite(timeout) or timeout < 0):
            raise ValueError("timeout must be finite and nonnegative")
        with self._lock:
            result = self.poll()
            if result is not None:
                return result
            if self._process is None:
                raise ValueError("process is closed")
            copy = W.HANDLE()
            current = _current_process()
            _checked(_duplicate(current, self._process, current, C.byref(copy), 0, False, 2), "DuplicateHandle")
        try:
            deadline = None if timeout is None else time.monotonic() + timeout
            while True:
                remaining = None if deadline is None else max(0, deadline - time.monotonic())
                millis = 0xFFFFFFFF if remaining is None else min(0xFFFFFFFE, math.ceil(remaining * 1000))
                state = _wait(copy, millis)
                if state == 0:
                    code = W.DWORD()
                    _checked(_exit_code(copy, C.byref(code)), "GetExitCodeProcess")
                    with self._lock:
                        self._returncode = code.value
                    return code.value
                if state != 0x102:
                    _checked(False, "WaitForSingleObject")
                if deadline is not None and time.monotonic() >= deadline:
                    raise TimeoutError("process did not exit within timeout")
        finally:
            _close_handle(copy)

    def kill_tree(self):
        """Empty this Job and confirm direct-process exit within one deadline."""
        with self._lock:
            if self._job is None:
                return
            deadline = time.monotonic() + 5
            _checked(_terminate_job(self._job, 1), "TerminateJobObject")
            while True:
                counts = _Accounting()
                _checked(_query_job(self._job, 1, C.byref(counts), C.sizeof(counts), None),
                         "QueryInformationJobObject")
                if not counts.ActiveProcesses:
                    break
                if time.monotonic() >= deadline:
                    raise TimeoutError("owned Job still has active processes after termination")
                time.sleep(0.01)
            # Job accounting can reach zero before the process object becomes
            # signaled. A zero-time poll followed by CloseHandle permanently
            # loses its exit code in that interval. Wait on our owned handle
            # directly (not another Python waiter), using the same deadline.
            if self._process is not None and self._returncode is None:
                remaining = max(0, deadline - time.monotonic())
                state = _wait(self._process, math.ceil(remaining * 1000))
                if state == 0x102:
                    raise TimeoutError("owned process has not completed termination")
                if state != 0:
                    _checked(False, "WaitForSingleObject(termination)")
                code = W.DWORD()
                _checked(_exit_code(self._process, C.byref(code)), "GetExitCodeProcess")
                self._returncode = code.value

    def close(self):
        """Idempotently reclaim the tree and close every owned stream/handle."""
        with self._lock:
            if self._closed:
                return
            try:
                self.kill_tree()
            finally:
                # Closing the last Job handle is also the crash-safe fallback.
                for name in ("_job", "_process"):
                    handle = getattr(self, name)
                    if handle is not None:
                        _close_handle(handle)
                        setattr(self, name, None)
                for stream in (self.stdin, self.stdout, self.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except (OSError, ValueError):
                            pass
                self._closed = True

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
