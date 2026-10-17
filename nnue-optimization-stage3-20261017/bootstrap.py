"""Recover reference receipts from existing commits for a new local reproduction."""
import subprocess
import experiment as p

assert not (p.ROOT/'plan.json').exists(), 'Never bootstrap a frozen workspace'
folder=p.ART/'references';folder.mkdir(parents=True,exist_ok=True)
sources={
    'preservation-before.json':'cac90341104200dcf7d7a5547b5c9eb768f39202:nnue-optimization-stage2-1-20261017/preservation-before.json',
    'NNUE_STAGE2_1_OPTIMIZATION_REPORT.md':'cac90341104200dcf7d7a5547b5c9eb768f39202:NNUE_STAGE2_1_OPTIMIZATION_REPORT.md',
    'NNUE_STAGE2_OPTIMIZATION_REPORT.md':'004281cb8a24357e61229c8945d8d4aababc4a4c:NNUE_STAGE2_OPTIMIZATION_REPORT.md'}
for name,reference in sources.items():
    (folder/name).write_bytes(subprocess.check_output(['git','show',reference],cwd=p.REPO))
print('Recovered reference receipts; preserved local binaries/model/toolchain remain prerequisites')
