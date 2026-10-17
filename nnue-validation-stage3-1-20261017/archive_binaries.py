"""Archive exact measured EXE/PDB bytes locally, without executing or rebuilding."""
import shutil
import validate as v


def main():
    v.check_plan()
    archived={}
    for label,path in v.BINARIES.items():
        destination=v.ROOT/'artifacts/exact-binaries'/label
        destination.mkdir(parents=True,exist_ok=True)
        for source in [path,path.with_suffix('.pdb')]:
            target=destination/source.name
            digest=v.common.sha(source)
            if target.exists():
                assert v.common.sha(target)==digest
            else:
                shutil.copy2(source,target)
            assert v.common.sha(target)==digest
            archived[target.relative_to(v.REPO).as_posix()]=dict(sha256=digest,measured_original=source.relative_to(v.REPO).as_posix())
    v.save('archived-binaries.json',archived)
    print('Archived four original EXE/PDB files byte-for-byte; originals untouched')


if __name__=='__main__':
    main()
