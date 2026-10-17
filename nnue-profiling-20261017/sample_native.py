"""Bounded Windows instruction-pointer sampler, only for our own child engine.

No injected code, drivers, process-wide profiler, call-stack or hardware counters.
Every successful thread suspension is paired with ResumeThread in finally.
"""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor
import collections
import ctypes as c
from ctypes import wintypes as w
import json
import random
import time
import run_profile as p

k=c.WinDLL('kernel32',use_last_error=True)
class ThreadEntry(c.Structure):
    _fields_=[('size',w.DWORD),('usage',w.DWORD),('tid',w.DWORD),('pid',w.DWORD),('base',w.LONG),('delta',w.LONG),('flags',w.DWORD)]
class ModuleEntry(c.Structure):
    _fields_=[('size',w.DWORD),('id',w.DWORD),('pid',w.DWORD),('global_usage',w.DWORD),('process_usage',w.DWORD),('base',c.c_void_p),('bytes',w.DWORD),('module',c.c_void_p),('name',w.WCHAR*256),('path',w.WCHAR*260)]
def api(name,args,result):
    fn=getattr(k,name);fn.argtypes=args;fn.restype=result;return fn
snapshot=api('CreateToolhelp32Snapshot',[w.DWORD,w.DWORD],w.HANDLE)
close=api('CloseHandle',[w.HANDLE],w.BOOL)
thread_first=api('Thread32First',[w.HANDLE,c.POINTER(ThreadEntry)],w.BOOL)
thread_next=api('Thread32Next',[w.HANDLE,c.POINTER(ThreadEntry)],w.BOOL)
module_first=api('Module32FirstW',[w.HANDLE,c.POINTER(ModuleEntry)],w.BOOL)
module_next=api('Module32NextW',[w.HANDLE,c.POINTER(ModuleEntry)],w.BOOL)
open_thread=api('OpenThread',[w.DWORD,w.BOOL,w.DWORD],w.HANDLE)
open_process=api('OpenProcess',[w.DWORD,w.BOOL,w.DWORD],w.HANDLE)
affinity=api('SetProcessAffinityMask',[w.HANDLE,c.c_size_t],w.BOOL)
thread_times=api('GetThreadTimes',[w.HANDLE]+[c.POINTER(w.FILETIME)]*4,w.BOOL)
suspend=api('SuspendThread',[w.HANDLE],w.DWORD)
resume=api('ResumeThread',[w.HANDLE],w.DWORD)
context=api('GetThreadContext',[w.HANDLE,c.c_void_p],w.BOOL)

def cpu_time(handle):
    values=[w.FILETIME() for _ in range(4)]
    if not thread_times(handle,*[c.byref(v) for v in values]):raise c.WinError(c.get_last_error())
    return sum((v.dwHighDateTime<<32)+v.dwLowDateTime for v in values[2:])

def target_threads(pid):
    h=snapshot(4,0);entry=ThreadEntry();entry.size=c.sizeof(entry);handles=[]
    try:
        okay=thread_first(h,c.byref(entry))
        while okay:
            if entry.pid==pid:
                handle=open_thread(0x0002|0x0008|0x0040,False,entry.tid)
                if handle:handles.append((entry.tid,handle))
            okay=thread_next(h,c.byref(entry))
    finally:close(h)
    return handles

def modules(pid):
    h=snapshot(0x8|0x10,pid);entry=ModuleEntry();entry.size=c.sizeof(entry);out=[]
    try:
        okay=module_first(h,c.byref(entry))
        while okay:
            out.append({'name':entry.name,'base':entry.base,'bytes':entry.bytes})
            okay=module_next(h,c.byref(entry))
    finally:close(h)
    return out

def symbols(data):
    """Use installed Windows DbgHelp and the matching local PDB, no servers."""
    dbg=c.WinDLL('dbghelp',use_last_error=True)
    class Symbol(c.Structure):
        _fields_=[('SizeOfStruct',w.ULONG),('TypeIndex',w.ULONG),('Reserved',c.c_uint64*2),('Index',w.ULONG),('Size',w.ULONG),('ModBase',c.c_uint64),('Flags',w.ULONG),('Value',c.c_uint64),('Address',c.c_uint64),('Register',w.ULONG),('Scope',w.ULONG),('Tag',w.ULONG),('NameLen',w.ULONG),('MaxNameLen',w.ULONG),('Name',c.c_char*2048)]
    class Line(c.Structure):
        _fields_=[('SizeOfStruct',w.DWORD),('Key',c.c_void_p),('LineNumber',w.DWORD),('FileName',c.c_char_p),('Address',c.c_uint64)]
    get_current=api('GetCurrentProcess',[],w.HANDLE);process=get_current()
    dbg.SymSetOptions.argtypes=[w.DWORD];dbg.SymSetOptions(0x4|0x2|0x200|0x80000|0x400)
    dbg.SymInitialize.argtypes=[w.HANDLE,c.c_char_p,w.BOOL];dbg.SymInitialize.restype=w.BOOL
    dbg.SymLoadModuleExW.argtypes=[w.HANDLE,w.HANDLE,w.LPCWSTR,w.LPCWSTR,c.c_uint64,w.DWORD,c.c_void_p,w.DWORD];dbg.SymLoadModuleExW.restype=c.c_uint64
    dbg.SymFromAddr.argtypes=[w.HANDLE,c.c_uint64,c.POINTER(c.c_uint64),c.POINTER(Symbol)];dbg.SymFromAddr.restype=w.BOOL
    dbg.SymGetLineFromAddr64.argtypes=[w.HANDLE,c.c_uint64,c.POINTER(w.DWORD),c.POINTER(Line)];dbg.SymGetLineFromAddr64.restype=w.BOOL
    dbg.SymCleanup.argtypes=[w.HANDLE]
    if not dbg.SymInitialize(process,str(p.ART).encode(),False):raise c.WinError(c.get_last_error())
    try:
        module=next(m for m in data['modules'] if m['name'].lower()=='mapped.exe')
        loaded=dbg.SymLoadModuleExW(process,None,str(p.ART/'mapped.exe'),None,module['base'],module['bytes'],None,0)
        if not loaded:raise c.WinError(c.get_last_error())
        out={}
        for address in {a for r in data['records'] for a in r['rip_counts']}:
            ip=int(address,16);info=Symbol();info.SizeOfStruct=88;info.MaxNameLen=2048;displacement=c.c_uint64()
            if dbg.SymFromAddr(process,ip,c.byref(displacement),c.byref(info)):
                out[address]={'symbol':info.Name.decode(errors='replace'),'displacement':displacement.value,'symbol_address':info.Address,'symbol_size':info.Size}
                line=Line();line.SizeOfStruct=c.sizeof(line);delta=w.DWORD()
                if dbg.SymGetLineFromAddr64(process,ip,c.byref(delta),c.byref(line)):
                    out[address].update(file=line.FileName.decode(errors='replace'),line=line.LineNumber)
            else:
                owner=next((m['name'] for m in data['modules'] if m['base']<=ip<m['base']+m['bytes']),'unknown')
                out[address]={'symbol':owner+'!unresolved','error':c.get_last_error()}
        p.save('native-symbols.json',out)
    finally:dbg.SymCleanup(process)

def run():
    p.pin(4)  # Sampling Python uses CPU2; child search is pinned explicitly to CPU0.
    rows=p.common.load(p.ROOT/'positions.json')
    chosen=[r for r in rows if r['id'] in ('opening','quiet_middlegame','tactical','piece_endgame')]
    data={'method':'Windows x64 CONTROL-context RIP samples on own CPU-active child thread; randomized 2–4ms intervals. Exclusive instruction pointers only; inlining and suspension bias retained. No hardware counters.','records':[],'symbols':'artifacts/mapped.pdb'}
    with p.open_engine(p.ART/'mapped.exe') as player, ThreadPoolExecutor(max_workers=1) as pool:
        player.configure(dict(p.common.load(p.ROOT/'config.json')['options'],Evaluator='nnue'))
        pid=player.transport.get_pid()
        process=open_process(0x0200,False,pid)
        try:
            if not affinity(process,1):raise c.WinError(c.get_last_error())
        finally:close(process)
        data['modules']=modules(pid)
        for repeat in range(3):
            for index,row in enumerate(chosen):
                for sampled in ((False,True) if (repeat+index)%2==0 else (True,False)):
                    future=pool.submit(p.checked_capture,player,row,'time',1500)
                    addresses=collections.Counter();failures=0;latencies=[]
                    if sampled:
                        time.sleep(.15)
                        handles=target_threads(pid)
                        try:
                            before={tid:cpu_time(h) for tid,h in handles};time.sleep(.05)
                            tid,handle=max(handles,key=lambda item:cpu_time(item[1])-before[item[0]])
                            buffer=c.create_string_buffer(1232+16)
                            address=(c.addressof(buffer)+15)&~15
                            rng=random.Random(20261017+repeat+index)
                            while not future.done():
                                c.memset(address,0,1232);c.c_uint32.from_address(address+48).value=0x100001
                                start=time.perf_counter_ns()
                                previous=suspend(handle)
                                if previous!=0xffffffff:
                                    try:
                                        if context(handle,address):addresses[c.c_uint64.from_address(address+248).value]+=1
                                        else:failures+=1
                                    finally:
                                        if resume(handle)==0xffffffff:raise c.WinError(c.get_last_error())
                                else:failures+=1
                                latencies.append(time.perf_counter_ns()-start)
                                time.sleep(rng.uniform(.002,.004))
                        finally:
                            for _,h in handles:close(h)
                    record=future.result(timeout=10)
                    data['records'].append(dict(record,repeat=repeat,sampled=sampled,rip_counts={hex(a):n for a,n in addresses.items()},failed_samples=failures,suspension_ns=latencies))
                    p.save('native-samples.json',data)
                print('Native samples',repeat,row['id'],flush=True)
    symbols(data)

if __name__=='__main__':run()
