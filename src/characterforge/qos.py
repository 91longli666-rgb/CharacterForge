"""Temporary process-only Windows scheduling hint for local interactive inference.

No system power plan, priority class, CPU affinity, service or registry edits.
Microsoft: https://learn.microsoft.com/en-us/windows/win32/api/processthreadsapi/nf-processthreadsapi-setprocessinformation
"""
import os
def interactive_process_qos():
    if os.environ.get('CF_INTERACTIVE_QOS')=='0':return {'applied':False,'reason':'disabled_by_environment'}
    if os.name!='nt':return {'applied':False,'reason':'not_windows'}
    try:
        import ctypes
        from ctypes import wintypes as w
        class Power(ctypes.Structure):
            _fields_=[('ac',w.BYTE),('flag',w.BYTE),('percent',w.BYTE),('reserved',w.BYTE),('life',w.DWORD),('full',w.DWORD)]
        class Throttle(ctypes.Structure):
            _fields_=[('version',w.ULONG),('control',w.ULONG),('state',w.ULONG)]
        kernel=ctypes.WinDLL('kernel32',use_last_error=True)
        kernel.GetCurrentProcess.restype=w.HANDLE
        kernel.GetSystemPowerStatus.argtypes=[ctypes.POINTER(Power)]
        kernel.SetProcessInformation.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
        kernel.GetProcessInformation.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
        power=Power()
        if not kernel.GetSystemPowerStatus(ctypes.byref(power)) or power.ac!=1:return {'applied':False,'reason':'battery_or_power_unknown'}
        handle=kernel.GetCurrentProcess();state=Throttle(1,1,0)
        if not kernel.SetProcessInformation(handle,4,ctypes.byref(state),ctypes.sizeof(state)):raise OSError(ctypes.get_last_error(),'SetProcessInformation')
        observed=Throttle(1,0,0)
        if not kernel.GetProcessInformation(handle,4,ctypes.byref(observed),ctypes.sizeof(observed)):raise OSError(ctypes.get_last_error(),'GetProcessInformation')
        return {'applied':observed.control&1==1 and observed.state&1==0,'policy':'interactive_on_ac','control':observed.control,'state':observed.state,'scope':'this process until exit'}
    except Exception as error:return {'applied':False,'reason':type(error).__name__+': '+str(error)[:100]}
