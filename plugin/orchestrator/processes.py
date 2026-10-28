"""Read-only owner identity/child checks for an idle legacy bridge handoff."""
import json
import os
import pathlib
import subprocess
from .errors import BridgeError


def _windows_alive(pid):
    import ctypes
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.restype=ctypes.c_void_p
    api.CloseHandle.argtypes=[ctypes.c_void_p]
    api.GetExitCodeProcess.argtypes=[ctypes.c_void_p,ctypes.POINTER(ctypes.c_ulong)]
    handle=api.OpenProcess(0x1000,False,int(pid))
    if not handle:
        if ctypes.get_last_error()==87:return False
        raise OSError('Process liveness cannot be verified')
    try:
        code=ctypes.c_ulong()
        if not api.GetExitCodeProcess(handle,ctypes.byref(code)):raise OSError('Process liveness query failed')
        return code.value==259
    finally:api.CloseHandle(handle)


def owner_snapshot(pid):
    """Never stop a process. Refuse unavailable or ambiguous inspection."""
    pid=int(pid)
    try:
        if os.name=='nt':
            script=(f"$handoffOwner=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}' -ErrorAction Stop; "
                    f"$handoffChildren=@(Get-CimInstance Win32_Process -Filter 'ParentProcessId={pid}' -ErrorAction Stop); "
                    "@{identity=if($handoffOwner){$handoffOwner.CreationDate.ToUniversalTime().ToString('o')}else{$null}; "
                    "children=@($handoffChildren | ForEach-Object {@{pid=$_.ProcessId;image=$_.ExecutablePath}})} | ConvertTo-Json -Compress -Depth 4")
            result=subprocess.run(['powershell.exe','-NoProfile','-NonInteractive','-Command',script],stdin=subprocess.DEVNULL,capture_output=True,text=True,timeout=15,
                                  creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
            if result.returncode:raise ValueError('Process query failed')
            data=json.loads(result.stdout)
            identity=data['identity'];children=data['children']
            if not isinstance(identity,str) or not identity or not isinstance(children,list):raise ValueError('Owner unavailable')
            if not _windows_alive(pid):raise ValueError('Owner exited')
            import ctypes
            directory=ctypes.create_unicode_buffer(32768)
            length=ctypes.WinDLL('kernel32',use_last_error=True).GetSystemDirectoryW(directory,len(directory))
            if not length or length>=len(directory):raise ValueError('System directory unavailable')
            console=os.path.normcase(str(pathlib.Path(directory.value)/'conhost.exe'))
            active=[]
            for child in children:
                child_pid=int(child['pid'])
                if not _windows_alive(child_pid):continue
                # A bridge's console host can outlive its App Server. Only the
                # exact OS system image is exempt; application children block.
                if child.get('image') and os.path.normcase(child['image'])==console:continue
                active.append(child_pid)
            return {'pid':pid,'identity':identity,'children':active}
        proc=pathlib.Path('/proc')
        def info(path):
            value=(path/'stat').read_text();fields=value[value.rfind(')')+2:].split()
            return fields[0],int(fields[1]),fields[19]
        if not proc.is_dir():raise ValueError('This platform has no supported process inspector')
        state,parent,start=info(proc/str(pid))
        if state=='Z':raise ValueError('Owner exited')
        children=[]
        for path in proc.iterdir():
            if not path.name.isdecimal():continue
            try:state,parent,child_start=info(path)
            except FileNotFoundError:continue
            if parent==pid and state!='Z':children.append(int(path.name))
        if info(proc/str(pid))[2]!=start:raise ValueError('Owner identity changed')
        return {'pid':pid,'identity':start,'children':children}
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        raise BridgeError('BRIDGE_PROCESS_UNVERIFIED','Cannot verify the original bridge process identity/children. Keep its current lease; no automatic restart or process termination was attempted.') from exc


def owner_released(expected):
    current=owner_snapshot(expected['pid'])
    if current['identity']!=expected['identity']:
        raise BridgeError('BRIDGE_PROCESS_UNVERIFIED','The original bridge PID was reused or its identity changed. No handoff was applied.')
    if current['children']:
        raise BridgeError('BRIDGE_RELEASE_REQUIRED','The original bridge still has child processes. Complete its own bridge_release successfully and retry; another connection release is insufficient.',{'child_pids':current['children']})
    return current
