from pathlib import Path

import chess
import pygame
import pytest

from app.application import Application
from app.board_renderer import ASSET_DIR, BoardGeometry
from app.game import Game
from app.ui.sidebar import Sidebar


@pytest.fixture
def app():
    application = Application()
    application.draw()
    yield application
    application.close()


def click(app, position):
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=position))
    app.draw()


def square_click(app, square):
    click(app, app.geometry.square_rect(square).center)


@pytest.mark.parametrize("flipped", [False, True])
def test_every_square_maps_in_both_orientations(flipped) -> None:
    geometry = BoardGeometry(pygame.Rect(40, 116, 512, 512), flipped)
    for square in chess.SQUARES:
        assert geometry.square_at(geometry.square_rect(square).center) == square
    assert geometry.square_at((39, 116)) is None
    assert geometry.square_at((552, 116)) is None
    assert geometry.square_at((40, 628)) is None
    assert geometry.square_at((40, 116)) == (chess.H1 if flipped else chess.A8)


def test_mouse_moves_undo_flip_and_restart(app) -> None:
    square_click(app, chess.E2)
    square_click(app, chess.E4)
    assert [r.san for r in app.game.records] == ["e4"]
    before = app.game.board.fen()
    click(app, app.sidebar.buttons(app.sidebar_rect)["flip"].center)
    assert app.flipped and app.game.board.fen() == before
    square_click(app, chess.E7)
    square_click(app, chess.E5)
    assert len(app.game.records) == 2
    click(app, app.sidebar.buttons(app.sidebar_rect)["undo"].center)
    assert app.game.board.fen() == before
    assert app.inputs.selected is None
    click(app, app.sidebar.buttons(app.sidebar_rect)["new"].center)
    assert app.game.board.fen() == chess.STARTING_FEN
    assert not app.flipped


def test_disabled_claim_and_undo_buttons_do_not_change_game(app) -> None:
    for name in ("claim", "undo"):
        click(app, app.sidebar.buttons(app.sidebar_rect)[name].center)
    assert app.game.board.fen() == chess.STARTING_FEN
    assert not app.claim_dialog


def test_outside_click_and_escape_clear_selection(app) -> None:
    square_click(app, chess.D2)
    click(app, (10, 10))
    assert app.inputs.selected is None
    square_click(app, chess.D2)
    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    assert app.inputs.selected is None


def test_promotion_dialog_mouse_choice_and_keyboard_cancel(app) -> None:
    app.game = Game("7k/P7/8/8/8/8/8/7K w - - 0 1")
    app.inputs.game = app.game
    square_click(app, chess.A7)
    square_click(app, chess.A8)
    assert chess.QUEEN in app.modal_targets
    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    assert app.game.board.piece_at(chess.A7) is not None
    square_click(app, chess.A7)
    square_click(app, chess.A8)
    click(app, app.modal_targets[chess.ROOK].center)
    assert app.game.board.piece_at(chess.A8) == chess.Piece(chess.ROOK, chess.WHITE)


def test_draw_claim_dialog_mouse_selection_and_undo(app) -> None:
    app.game = Game("7k/8/8/8/8/8/R7/7K w - - 100 51")
    app.inputs.game = app.game
    before = app.game.board.fen()
    click(app, app.sidebar.buttons(app.sidebar_rect)["claim"].center)
    assert app.claim_dialog
    claim = app.game.draw_claims[0]
    click(app, app.modal_targets[claim].center)
    assert app.game.outcome.termination == chess.Termination.FIFTY_MOVES
    assert not app.claim_dialog
    assert app.game.board.fen() == before
    app.action("undo")
    assert app.game.outcome is None
    assert app.game.board.fen() == before


def test_history_scroll_and_black_start_numbering(app) -> None:
    for uci in ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5", "d2d3", "d7d6",
                "b1c3", "g8f6", "c1e3", "c8e6", "c4b3", "c5b6", "d1d2", "d8d7"]:
        assert app.game.play(chess.Move.from_uci(uci))
    app.draw()
    assert app.sidebar.scroll > 0
    app.sidebar.scroll_by(-999)
    assert app.sidebar.scroll == 0
    app.sidebar.scroll_by(999)
    assert app.sidebar.scroll == 8 - app.sidebar._visible_rows
    game = Game("7k/8/8/8/8/8/R7/7K b - - 0 25")
    assert game.play(chess.Move.from_uci("h8g8"))
    assert Sidebar.history_rows(game) == [(25, "", "Kg8")]


def test_history_mousewheel_and_new_move_follow_latest(app, monkeypatch) -> None:
    moves = ["e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "f8c5", "d2d3", "d7d6",
             "b1c3", "g8f6", "c1e3", "c8e6", "c4b3", "c5b6", "d1d2", "d8d7"]
    for uci in moves:
        assert app.game.play(chess.Move.from_uci(uci))
    app.draw()
    monkeypatch.setattr(pygame.mouse, "get_pos",
                        lambda: app.sidebar.history_rect(app.sidebar_rect).center)
    app.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=99))
    assert app.sidebar.scroll == 0
    assert app.game.play(chess.Move.from_uci("a2a3"))
    app.draw()
    assert app.sidebar.scroll == 9 - app.sidebar._visible_rows


def test_intended_claim_dialog_scroll_cancel_and_commit(app) -> None:
    app.game = Game("7k/8/8/8/8/8/R7/7K w - - 99 51")
    app.inputs.game = app.game
    before = app.game.board.fen()
    app.action("claim")
    app.draw()
    assert len(app.game.draw_claims) > 5
    app.handle_event(pygame.event.Event(pygame.MOUSEWHEEL, y=-99))
    app.draw()
    assert app.claim_scroll == len(app.game.draw_claims) - 5
    click(app, app.modal_targets["cancel"].center)
    assert not app.claim_dialog and app.game.outcome is None
    app.action("claim")
    app.draw()
    claim = app.game.draw_claims[0]
    assert claim.intended_move is not None
    click(app, app.modal_targets[claim].center)
    assert app.game.outcome is not None
    assert app.game.board.fen() == before
    assert app.game.records == []


@pytest.mark.parametrize("key,kind", [(pygame.K_q, chess.QUEEN), (pygame.K_r, chess.ROOK),
                                     (pygame.K_b, chess.BISHOP), (pygame.K_n, chess.KNIGHT)])
def test_promotion_keyboard_shortcuts_and_modal_blocks_game_commands(app, key, kind) -> None:
    app.game = Game("7k/P7/8/8/8/8/8/7K w - - 0 1")
    app.inputs.game = app.game
    square_click(app, chess.A7)
    square_click(app, chess.A8)
    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_f))
    assert not app.flipped
    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))
    assert app.game.board.piece_at(chess.A8) == chess.Piece(kind, chess.WHITE)


def test_keyboard_controls(app) -> None:
    square_click(app, chess.E2)
    square_click(app, chess.E4)
    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_f))
    assert app.flipped
    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_u))
    assert app.game.board.fen() == chess.STARTING_FEN
    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_n))
    assert not app.flipped


def test_assets_missing_produce_a_useful_startup_error(monkeypatch, capsys) -> None:
    from app import board_renderer, main
    monkeypatch.setattr(board_renderer, "ASSET_DIR", ASSET_DIR / "missing")
    monkeypatch.setattr("sys.argv", ["chesslab", "--smoke-test", "1"])
    assert main.main() == 1
    assert "app/assets/pieces" in capsys.readouterr().err


@pytest.mark.parametrize("size", [(960, 680), (1100, 760), (1440, 1000), (500, 400)])
def test_resizing_preserves_game_and_keeps_controls_inside_window(app, size) -> None:
    square_click(app, chess.E2)
    before = app.game.board.fen()
    app.handle_event(pygame.event.Event(pygame.VIDEORESIZE, size=size))
    app.draw()
    assert app.game.board.fen() == before
    assert app.geometry.rect.width % 8 == 0
    assert app.surface.get_rect().contains(app.sidebar_rect)
    assert app.surface.get_rect().contains(app.geometry.rect)
    for rect in app.sidebar.buttons(app.sidebar_rect).values():
        assert app.sidebar_rect.contains(rect)


@pytest.mark.parametrize("scenario", ["initial", "selection", "checkmate", "promotion", "draw", "flipped"])
def test_render_scenarios_use_local_assets_and_produce_frames(app, tmp_path: Path, scenario) -> None:
    if scenario == "selection":
        square_click(app, chess.E2)
    elif scenario == "checkmate":
        for uci in ("f2f3", "e7e5", "g2g4", "d8h4"):
            assert app.game.play(chess.Move.from_uci(uci))
    elif scenario == "promotion":
        app.game = Game("7k/P7/8/8/8/8/8/7K w - - 0 1")
        app.inputs.game = app.game
        square_click(app, chess.A7)
        square_click(app, chess.A8)
    elif scenario == "draw":
        app.game = Game("7k/8/8/8/8/8/R7/7K w - - 99 51")
        app.inputs.game = app.game
        app.action("claim")
    elif scenario == "flipped":
        app.action("flip")
    app.draw()
    path = tmp_path / f"{scenario}.png"
    pygame.image.save(app.surface, path)
    assert path.stat().st_size > 5000
    assert len(list(ASSET_DIR.glob("*.png"))) == 12
    assert all(image.get_size() == (256, 256) for image in app.pieces.originals.values())
    assert all(image.get_bounding_rect().height > 160 for image in app.pieces.originals.values())


def test_event_loop_processes_posted_moves_and_quit(app) -> None:
    for square in (chess.E2, chess.E4):
        pygame.event.post(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1,
                                            pos=app.geometry.square_rect(square).center))
    app.run(frames=2)
    assert app.game.records[-1].san == "e4"
    pygame.event.post(pygame.event.Event(pygame.QUIT))
    app.run(frames=2)
    assert not app.running
