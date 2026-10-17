"""Build isolated analysis harnesses with the frozen baseline compiler flags."""
import json
from pathlib import Path
import run_profile as p

config=json.loads((p.ROOT/'build-micro.json').read_text())
flags=config['flags']
base=flags[:flags.index(str(p.REPO/'engine/tests/benchmark_nnue.cpp'))]
# Use only the copied original sources; generated headers are the same model.
base=[str(p.ART/'source') if s==str(p.REPO/'engine/src') else s for s in base]
out=p.ART/'components.exe'
args=config['compiler']+base+[str(p.ROOT/'components.cpp'),str(p.ART/'source/nnue.cpp'),'-o',str(out)]
p.command(args,p.ART/'components-build.log')
p.save('build-components.json',{'command':args,'sha256':p.common.sha(out)})
# Zig's bundled COFF linker rejects GNU -Map. Debug symbols leave optimization
# flags unchanged; parity and sampling observer checks are measured separately.
out=p.ART/'mapped.exe'
args=config['compiler']+base+['-g']+[str(p.ART/'source'/name) for name in ('main.cpp','search.cpp','evaluation.cpp','nnue.cpp','nnue_v3.cpp')]+['-o',str(out)]
p.command(args,p.ART/'mapped-build.log')
p.save('build-mapped.json',{'command':args,'sha256':p.common.sha(out)})
# Zig writes a PDB rather than a COFF symbol table. Windows DbgHelp resolves
# local symbols directly; old 32-bit MinGW nm cannot read this x64 executable.
p.save('symbol-support.json',{'format':'PDB','pdb_sha256':p.common.sha(out.with_suffix('.pdb')),'resolver':'Windows DbgHelp, local paths only','gnu_map':'installed Zig rejects -Map','mingw_nm':'installed 32-bit nm cannot read x64 PE'})
# Disassembly of the frozen flags, not an alternative optimization experiment.
args=config['compiler']+base+['-S',str(p.ART/'source/nnue.cpp'),'-o',str(p.ART/'nnue.s')]
p.command(args,p.ART/'assembly-build.log')
print('Isolated component harness, mapped engine and assembly ready',flush=True)
