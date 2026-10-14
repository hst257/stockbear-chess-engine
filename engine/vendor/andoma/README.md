# Piece-square table attribution

The numeric tables in [../../src/pst.hpp](../../src/pst.hpp) are adapted from
Andrew Healey's [Andoma evaluate.py](https://github.com/healeycodes/andoma/blob/main/evaluate.py),
available under the [MIT license](LICENSE), copyright 2020 Andrew Healey.
Source and license were checked on 2026-10-14. No Andoma search code is included.

The tables originate in Tomasz Michniewski's
[Simplified Evaluation Function](https://chessprogramming.org/Simplified_Evaluation_Function).
We normalized every table to rank 1 first, including the asymmetric knight and
queen rows, and corrected two king entries against that original reference:
middlegame a4 is -20; endgame a1 is -50. All entries are positional centipawns;
the engine's existing material values remain separate.

ChessLab adds rank mirroring for Black and a 0–24 material-phase interpolation
of the two king tables. Other pieces retain one table in all phases.
