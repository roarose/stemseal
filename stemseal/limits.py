# -*- coding: utf-8 -*-
"""stemseal - limits on the runner process.

Every runner starts under these limits, and they are in place before it reads its request, so a cell never runs
outside them. If they cannot be applied, the runner is ended before it is sent anything.

    wall time   the caller's timeout (5 s per call; ground-truth batches get more), then the process is ended
    CPU time    the same number of seconds
    memory      256 MB (Windows, Linux; macOS does not enforce it, so there only time limits apply)
    processes   the runner only, no child processes
    file size   0 bytes written (Linux, macOS)
    open files  16 (Linux, macOS)
    core dumps  none
    priority    below normal (Windows), nice +10 (Linux, macOS)

Environment variables can only lower a limit: STEMSEAL_MEM_MB. Raising one needs a code change.
Standard library only."""
import math, os, subprocess, sys

MEM_MB = 256
NOFILE = 16
NICE = 10
MEMORY_ENFORCED = sys.platform != "darwin"

class LimitError(Exception):
    """The limits could not be applied; nothing was run."""

class Timeout(Exception):
    """The process ran past its time and was ended, with anything it started."""

def _lower_only(name, default):
    try: v = int(os.environ.get(name, ""))
    except ValueError: return default
    return v if 0 < v < default else default

def mem_mb(): return _lower_only("STEMSEAL_MEM_MB", MEM_MB)

def run(cmd, data, timeout, cwd=None, env=None):
    """Start cmd under the limits, write data to its stdin, and return (returncode, stdout, stderr).
    Raises Timeout after `timeout` seconds, LimitError if the limits could not be applied."""
    cpu = max(1, int(math.ceil(timeout)))
    if os.name == "nt": return _run_windows(cmd, data, timeout, cpu, cwd, env)
    return _run_posix(cmd, data, timeout, cpu, cwd, env)

# ---------------------------------------------------------------- Linux, macOS
def _posix_limits(cpu):
    """The function the child runs between fork and exec. Any failure stops the exec."""
    import resource
    mem = mem_mb() * 1024 * 1024
    def cap(which, value):
        soft, hard = resource.getrlimit(which)
        v = value if hard == resource.RLIM_INFINITY else min(value, hard)
        resource.setrlimit(which, (v, v))
    def apply():
        cap(resource.RLIMIT_CPU, cpu)
        if MEMORY_ENFORCED: cap(resource.RLIMIT_AS, mem)
        cap(resource.RLIMIT_NPROC, 1)
        cap(resource.RLIMIT_FSIZE, 0)
        cap(resource.RLIMIT_NOFILE, NOFILE)
        cap(resource.RLIMIT_CORE, 0)
        os.nice(NICE)
    return apply

def _run_posix(cmd, data, timeout, cpu, cwd, env):
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env,
                             preexec_fn=_posix_limits(cpu), start_new_session=True)
    except subprocess.SubprocessError as e:
        raise LimitError(str(e))
    try:
        out, err = p.communicate(data, timeout=timeout)
    except subprocess.TimeoutExpired:
        try: os.killpg(p.pid, 9)          # its own process group: anything it started ends with it
        except OSError: pass
        p.kill(); p.communicate()
        raise Timeout()
    return p.returncode, out, err

# ---------------------------------------------------------------- Windows (Job Object)
_K32 = None
def _kernel32():
    global _K32
    if _K32 is None:
        import ctypes
        from ctypes import wintypes
        k = ctypes.WinDLL("kernel32", use_last_error=True)
        k.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]; k.CreateJobObjectW.restype = wintypes.HANDLE
        k.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]; k.SetInformationJobObject.restype = wintypes.BOOL
        k.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]; k.AssignProcessToJobObject.restype = wintypes.BOOL
        k.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]; k.TerminateJobObject.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]; k.CloseHandle.restype = wintypes.BOOL
        _K32 = k
    return _K32

# JOBOBJECT_EXTENDED_LIMIT_INFORMATION flags and classes (winnt.h)
_LIMIT_PROCESS_TIME = 0x2
_LIMIT_ACTIVE_PROCESS = 0x8
_LIMIT_PROCESS_MEMORY = 0x100
_LIMIT_JOB_MEMORY = 0x200
_LIMIT_DIE_ON_UNHANDLED_EXCEPTION = 0x400
_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
_EXTENDED_LIMIT_INFORMATION = 9
_BASIC_UI_RESTRICTIONS = 4
_UILIMIT_ALL = 0xFF                 # handles, clipboard read/write, system parameters, display settings, global atoms, desktop, exit windows
_CREATE_NO_WINDOW = 0x08000000
_BELOW_NORMAL_PRIORITY_CLASS = 0x4000

def _job(cpu):
    """A new unnamed job with the limits set, or LimitError."""
    import ctypes
    from ctypes import wintypes
    class BASIC(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64), ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t), ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]
    class IO(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in ("ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                                                   "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]
    class EXTENDED(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
    class UI(ctypes.Structure):
        _fields_ = [("UIRestrictionsClass", wintypes.DWORD)]
    k = _kernel32()
    job = k.CreateJobObjectW(None, None)
    if not job: raise LimitError("job %d" % ctypes.get_last_error())
    info = EXTENDED()
    info.BasicLimitInformation.LimitFlags = (_LIMIT_PROCESS_TIME | _LIMIT_ACTIVE_PROCESS | _LIMIT_PROCESS_MEMORY | _LIMIT_JOB_MEMORY
                                             | _LIMIT_DIE_ON_UNHANDLED_EXCEPTION | _LIMIT_KILL_ON_JOB_CLOSE)
    info.BasicLimitInformation.PerProcessUserTimeLimit = cpu * 10000000        # 100 ns units
    info.BasicLimitInformation.ActiveProcessLimit = 1
    info.ProcessMemoryLimit = info.JobMemoryLimit = mem_mb() * 1024 * 1024
    ui = UI(_UILIMIT_ALL)
    if not (k.SetInformationJobObject(job, _EXTENDED_LIMIT_INFORMATION, ctypes.byref(info), ctypes.sizeof(info))
            and k.SetInformationJobObject(job, _BASIC_UI_RESTRICTIONS, ctypes.byref(ui), ctypes.sizeof(ui))):
        e = ctypes.get_last_error(); k.CloseHandle(job)
        raise LimitError("limits %d" % e)
    return job

def _assign(job, proc):
    return bool(_kernel32().AssignProcessToJobObject(job, int(proc._handle)))

def _run_windows(cmd, data, timeout, cpu, cwd, env):
    try: job = _job(cpu)
    except LimitError: raise
    except Exception as e: raise LimitError(type(e).__name__)
    k = _kernel32()
    try:
        p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=cwd, env=env,
                             creationflags=_CREATE_NO_WINDOW | _BELOW_NORMAL_PRIORITY_CLASS)
        # the runner waits for its request, so it has no cell before this point
        try: ok = _assign(job, p)
        except Exception: ok = False
        if not ok:
            p.kill(); p.communicate()
            raise LimitError("assign")
        try:
            out, err = p.communicate(data, timeout=timeout)
        except subprocess.TimeoutExpired:
            k.TerminateJobObject(job, 1)
            p.kill(); p.communicate()
            raise Timeout()
        return p.returncode, out, err
    finally:
        k.CloseHandle(job)          # KILL_ON_JOB_CLOSE: nothing in the job outlives this call
