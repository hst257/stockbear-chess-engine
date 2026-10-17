"""Bounded real-move interrupt/resume integration check; all games excluded."""
import copy
from pathlib import Path
import tournament as t


def main():
    original_root=t.ROOT
    original_outcome=t.outcome
    config=copy.deepcopy(t.config_check())
    opening=t.load('opening-suite.json')[0]
    game=t.load('schedule.json')[0]
    receipt_path=original_root/'smoke/harness-verification.json'
    assert not receipt_path.exists(),'Preserve existing smoke evidence'
    shadow=original_root/'smoke/resume-harness'
    shadow.mkdir(parents=True,exist_ok=True)
    config['max_searched_plies']=4
    game=dict(game,opening=0)
    env=t.load('environment.json')
    try:
        t.ROOT=shadow
        t.save('tournament-config.json',config)
        t.save('opening-suite.json',[opening])
        t.save('schedule.json',[game])
        t.save('environment.json',env)
        t.monitor.pin()
        def interrupt(board,searches,settings):
            if len(searches)==2:
                raise KeyboardInterrupt('Deliberate bounded smoke interruption after two saved legal moves')
            return original_outcome(board,searches,settings)
        t.outcome=interrupt
        try:
            t.play(game,config,[])
            raise AssertionError('Smoke interruption did not occur')
        except KeyboardInterrupt:
            pass
        partial=t.core.load(shadow/'games'/(game['id']+'.partial.json'))
        assert len(partial['searches'])==2
        prefix=copy.deepcopy(partial['searches'])
        t.outcome=original_outcome
        result=t.play(game,config,[])
        assert result['searches'][:2]==prefix and len(result['searches'])==4
        assert result['resumptions']==1 and result['termination']=='adjudicated_maximum_ply_draw'
        assert len(t.completed())==1
        t.validate_record(result)
        # No official directory/result is touched; preserve both partial and complete smoke records.
        t.core.save(receipt_path,dict(passed=True,excluded=True,real_searches=4,
            interrupted_after=2,resumed_without_replaying_saved_moves=True,
            final_checkpoint_skip_key=result['game']['id'],legal_replay_and_pgn=True,
            deliberate_safeguard_draw=True,config_sha256=result['config_sha256']))
    finally:
        t.ROOT=original_root
        t.outcome=original_outcome
    receipt=t.load('preflight.json')
    receipt['checks'].append('Actual game runner: four500ms legal searches,interrupt after2,restore exact2saved moves,no replay,explicit smoke cap draw,complete JSON/PGN validated')
    receipt['resume_harness_receipt_sha256']=t.core.sha(receipt_path)
    t.save('preflight.json',receipt)
    print('Real interrupt/resume smoke passed:4 searches,0 official games')


if __name__=='__main__':
    main()
