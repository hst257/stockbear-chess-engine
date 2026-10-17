"""Established opening lines, selected before any candidate game outcomes."""
import random
import chess
from tools.nnue_showdown import FAMILIES
from tools.final_nnue_showdown import LINES

EXTRA = (
    ('Vienna', 'e4 e5 Nc3 Nf6 Bc4 Nc6 d3 Bc5 Nf3 d6'),
    ("King's Gambit Accepted", 'e4 e5 f4 exf4 Nf3 g5 h4 g4 Ne5 Nf6'),
    ('Four Knights', 'e4 e5 Nf3 Nc6 Nc3 Nf6 Bb5 Bb4 O-O O-O'),
    ('Philidor', 'e4 e5 Nf3 d6 d4 Nf6 Nc3 Nbd7 Bc4 Be7 O-O O-O'),
    ('Scandinavian Modern', 'e4 d5 exd5 Nf6 d4 Nxd5 c4 Nb6 Nf3 g6'),
    ('Alekhine', 'e4 Nf6 e5 Nd5 d4 d6 Nf3 Bg4 Be2 e6'),
    ('Modern', 'e4 g6 d4 Bg7 Nc3 d6 f4 a6 Nf3 b5'),
    ('Sicilian Closed', 'e4 c5 Nc3 Nc6 g3 g6 Bg2 Bg7 d3 d6'),
    ('Sicilian Dragon', 'e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 g6 Be3 Bg7'),
    ('Sicilian Sveshnikov', 'e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 Nf6 Nc3 e5 Ndb5 d6'),
    ('Dutch', 'd4 f5 g3 Nf6 Bg2 g6 Nf3 Bg7 O-O O-O'),
    ('Benoni', 'd4 Nf6 c4 c5 d5 e6 Nc3 exd5 cxd5 d6 e4 g6'),
    ('Benko', 'd4 Nf6 c4 c5 d5 b5 cxb5 a6 bxa6 Bxa6 Nc3 d6'),
    ('Trompowsky', 'd4 Nf6 Bg5 Ne4 Bf4 d5 e3 c5 Bd3 Nf6'),
    ('Bird', 'f4 d5 Nf3 g6 e3 Bg7 Be2 Nf6 O-O O-O'),
    ('English Symmetrical', 'c4 c5 Nc3 Nc6 g3 g6 Bg2 Bg7 Nf3 Nf6'),
)


def make():
    rows=[]
    for source, lines in [('Existing architecture showdown FAMILIES', FAMILIES),
                          ('Existing final showdown LINES', LINES),
                          ('Additional hand-constructed established opening sequences', EXTRA)]:
        for name, san in lines:
            board=chess.Board()
            for token in san.split():
                board.push_san(token)
            assert board.is_valid() and not board.is_game_over(claim_draw=True), name
            group=next((prefix for prefix in ['Sicilian','French','Caro-Kann','Scandinavian','English'] if name.startswith(prefix)),name)
            rows.append(dict(description=name, family=name, family_group=group, san=san,
                             moves=[m.uci() for m in board.move_stack], fen=board.fen(),
                             source=source, construction='Named established line; no engine, model, strength or evaluation filtering'))
    assert len(rows)==len({r['fen'] for r in rows})==40
    random.Random(2026101780).shuffle(rows)
    return [dict(id=f'O{i+1:02}',**r) for i,r in enumerate(rows)]
