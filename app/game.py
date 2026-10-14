"""Rules and reversible game state. This module has no Pygame dependency."""

from dataclasses import dataclass

import chess


@dataclass(frozen=True)
class MoveRecord:
    move: chess.Move
    san: str
    color: chess.Color
    number: int
    captured: chess.Piece | None


@dataclass(frozen=True)
class DrawClaim:
    termination: chess.Termination
    intended_move: chess.Move | None = None

    @property
    def label(self) -> str:
        if self.termination == chess.Termination.THREEFOLD_REPETITION:
            return "Threefold repetition"
        return "Fifty-move rule"


class Game:
    """Own the board and its history; route all play through validated operations.

    The GUI reads ``board`` but must not mutate it. A future engine adapter should
    search a copy, then submit its result through ``play`` on the main thread.
    """

    def __init__(self, fen: str = chess.STARTING_FEN) -> None:
        self.board = chess.Board(fen)
        if not self.board.is_valid():
            raise ValueError("The starting position is not valid standard chess.")
        self.records: list[MoveRecord] = []
        self.claimed_draw: DrawClaim | None = None
        self.revision = 0
        self._refresh()

    def _refresh(self) -> None:
        # Claim checks replay history. Compute after mutations, never each frame.
        self.outcome = (
            chess.Outcome(self.claimed_draw.termination, None)
            if self.claimed_draw
            else self.board.outcome(claim_draw=False)
        )
        self.legal_moves = () if self.outcome else tuple(self.board.legal_moves)
        claims: list[DrawClaim] = []
        if not self.outcome:
            for termination, current, possible in (
                (chess.Termination.THREEFOLD_REPETITION,
                 self.board.is_repetition(3), self.board.can_claim_threefold_repetition),
                (chess.Termination.FIFTY_MOVES,
                 self.board.is_fifty_moves(), self.board.can_claim_fifty_moves),
            ):
                if current:
                    claims.append(DrawClaim(termination))
                elif possible():
                    candidate = self.board.copy(stack=True)
                    for move in self.legal_moves:
                        candidate.push(move)
                        valid = (candidate.is_repetition(3)
                                 if termination == chess.Termination.THREEFOLD_REPETITION
                                 else candidate.is_fifty_moves())
                        candidate.pop()
                        if valid:
                            claims.append(DrawClaim(termination, move))
        self.draw_claims = tuple(claims)

    def legal_destinations(self, square: chess.Square) -> set[chess.Square]:
        return {move.to_square for move in self.legal_moves if move.from_square == square}

    def promotion_choices(self, source: int, destination: int) -> tuple[int, ...]:
        available = {m.promotion for m in self.legal_moves
                     if m.from_square == source and m.to_square == destination}
        return tuple(p for p in (chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT)
                     if p in available)

    def play(self, move: chess.Move) -> bool:
        if self.outcome or move not in self.legal_moves:
            return False
        captured = self.board.piece_at(move.to_square)
        if self.board.is_en_passant(move):
            captured = chess.Piece(chess.PAWN, not self.board.turn)
        record = MoveRecord(move, self.board.san(move), self.board.turn,
                            self.board.fullmove_number, captured)
        self.board.push(move)
        self.records.append(record)
        self.revision += 1
        self._refresh()
        return True

    def captured_by(self, color: chess.Color) -> tuple[chess.Piece, ...]:
        return tuple(r.captured for r in self.records if r.color == color and r.captured)

    def claim_draw(self, claim: DrawClaim) -> bool:
        # Exact membership also rejects illegal/stale intended moves.
        if self.outcome or claim not in self.draw_claims:
            return False
        self.claimed_draw = claim
        self.revision += 1
        self._refresh()
        return True

    def undo(self) -> bool:
        if self.claimed_draw:
            self.claimed_draw = None
        elif self.records:
            self.board.pop()
            self.records.pop()
        else:
            return False
        self.revision += 1
        self._refresh()
        return True

    def reset(self) -> None:
        self.board.reset()
        self.records.clear()
        self.claimed_draw = None
        self.revision += 1
        self._refresh()

    @property
    def can_undo(self) -> bool:
        return bool(self.records or self.claimed_draw)

    @property
    def status(self) -> str:
        if self.outcome:
            if self.outcome.winner is not None:
                return f"{'White' if self.outcome.winner else 'Black'} wins"
            return "Draw"
        color = "White" if self.board.turn else "Black"
        return f"{color} in check" if self.board.is_check() else f"{color} to move"

    @property
    def result_reason(self) -> str:
        if not self.outcome:
            return "Move your king to safety." if self.board.is_check() else "Local two-player game"
        return {
            chess.Termination.CHECKMATE: "Checkmate",
            chess.Termination.STALEMATE: "Stalemate",
            chess.Termination.INSUFFICIENT_MATERIAL: "Insufficient material",
            chess.Termination.SEVENTYFIVE_MOVES: "Seventy-five-move rule",
            chess.Termination.FIVEFOLD_REPETITION: "Fivefold repetition",
            chess.Termination.FIFTY_MOVES: "Fifty-move rule claimed",
            chess.Termination.THREEFOLD_REPETITION: "Threefold repetition claimed",
        }.get(self.outcome.termination, "Game over")
