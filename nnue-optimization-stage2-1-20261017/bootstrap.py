"""Restore frozen Stage 2 reference inputs into a new experiment directory."""
import shutil
import subprocess
import experiment as p

assert not (p.ROOT/'plan.json').exists(), 'Do not bootstrap an existing frozen experiment'
references=p.ART/'references';references.mkdir(parents=True,exist_ok=True)
for name in ['search-sort.json','analysis-sort.json','build-sort-engine.json','sort.patch',
             'sort-updater-assembly.txt','baseline-updater-assembly.txt','preservation-before.json']:
    data=subprocess.check_output(['git','show','004281cb8a24357e61229c8945d8d4aababc4a4c:nnue-optimization-stage2-20261017/'+name],cwd=p.REPO)
    (references/name).write_bytes(data)
(references/'NNUE_STAGE2_OPTIMIZATION_REPORT.md').write_bytes(subprocess.check_output(
    ['git','show','004281cb8a24357e61229c8945d8d4aababc4a4c:NNUE_STAGE2_OPTIMIZATION_REPORT.md'],cwd=p.REPO))
shutil.copytree(p.REPO/'nnue-optimization-stage2-20261017/artifacts/sort-source',p.ART/'stage2-source')
print('Restored reference inputs; original binary/model/toolchain prerequisites remain required')
