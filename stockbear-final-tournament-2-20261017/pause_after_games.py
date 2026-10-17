"""One-shot user-requested pause at a saved completed-game boundary."""
import json
import os
from pathlib import Path
import sys
import time
import tournament as t


def main():
    target=int(sys.argv[1])
    assert 1<=target<80
    destination=t.ROOT/'games'/f'G{target:03}.json'
    t.save('pause-request.json',dict(requested_utc=t.core.utc(),completed_when_requested=65,
        requested_additional_games=2,target_completed_games=target,reason='User requested pause because usage limit is near',
        watcher_pid=os.getpid(),automatic_resume=False))
    while not destination.exists():
        time.sleep(.01)
    # Final game JSON is the commit marker written after legal replay and PGN.
    (t.ROOT/'STOP_REQUESTED').write_text(f'User requested stop after {target} completed games\n',encoding='utf-8')
    row=t.core.load(destination)
    assert row['complete']
    t.save('pause-boundary.json',dict(passed=True,target_completed_games=target,flag_written_utc=t.core.utc(),
        last_completed_game=row['game']['id'],last_result=row['result'],automatic_resume=False))
    print(f'Pause flag saved after {target} completed games',flush=True)


if __name__=='__main__':
    main()
