from collections import deque
import time

import chess
import pygame
import pytest

from app.application import Application
from app.engine_client import DEFAULT_ENGINE, EngineMessage, EngineSettings, SearchStats
from app.game import Game


class FakeEngine:
    """Only controls completion timing; real UCI/search have separate tests."""
    path = DEFAULT_ENGINE

    def __init__(self):
        self.busy = False
        self.token = 0
        self.messages = deque()
        self.calls = []

    def cancel(self):
        self.busy = False
        self.token += 1

    def close(self):
        self.cancel()

    def stop(self):
        self.stopped = True

    def start(self, board, revision, settings, kind):
        self.token += 1
        self.busy = True
        self.calls.append((board.copy(stack=True), revision, settings, kind))
        return self.token

    def poll(self):
        messages = list(self.messages)
        self.messages.clear()
        if any(message.finished for message in messages):
            self.busy = False
        return messages

    def finish(self, app, move="e7e5", error=""):
        move = chess.Move.from_uci(move)
        stats = SearchStats("Alpha-beta", 3, 3, 586, .01, move, "e5", "+0.00", True)
        self.messages.append(EngineMessage(app._request_token, app.game.revision, "play",
                                           (stats,), error))


@pytest.fixture
def app():
    instance = Application(settings=EngineSettings(enabled=True), engine_client=FakeEngine())
    instance.draw()
    yield instance
    instance.close()


def click(app, target):
    app.handle_event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1, pos=target))
    app.draw()


def human_e4(app):
    for square in (chess.E2, chess.E4):
        click(app, app.geometry.square_rect(square).center)
    app.update_engine()


def test_human_move_starts_search_and_only_legal_reply_is_applied(app):
    human_e4(app)
    assert app.engine.busy
    snapshot, revision, settings, kind = app.engine.calls[-1]
    assert snapshot.fen() == app.game.board.fen()
    assert len(snapshot.move_stack) == 1 and kind == "play"
    click(app, app.geometry.square_rect(chess.E7).center)
    assert app.inputs.selected is None
    app.engine.finish(app)
    app.update_engine()
    assert [r.san for r in app.game.records] == ["e4", "e5"]
    assert not app.engine.busy


def test_reset_and_newer_search_reject_stale_reply(app):
    human_e4(app)
    old_token, old_revision = app._request_token, app.game.revision
    app.action("new")
    app.engine.messages.append(EngineMessage(old_token, old_revision, "play"))
    app.update_engine()
    assert app.game.board.fen() == chess.STARTING_FEN
    assert not app.game.records


def test_undo_cancels_pending_search_and_completed_turn(app):
    human_e4(app)
    app.action("undo")
    app.update_engine()
    assert app.game.board.fen() == chess.STARTING_FEN
    assert not app.engine.busy
    human_e4(app)
    app.engine.finish(app)
    app.update_engine()
    app.action("undo")
    assert app.game.board.fen() == chess.STARTING_FEN
    assert app.game.records == []


def test_illegal_reply_and_process_failure_leave_game_unchanged(app):
    human_e4(app)
    before = app.game.board.fen()
    app.engine.finish(app, "e7e4")
    app.update_engine()
    assert app.game.board.fen() == before and app.engine_error
    call_count = len(app.engine.calls)
    app.update_engine()
    assert len(app.engine.calls) == call_count  # No automatic retry loop.
    app.action("new")
    human_e4(app)
    app.engine.finish(app, error="Engine exited unexpectedly")
    app.update_engine()
    assert "unexpectedly" in app.engine_error
    assert len(app.game.records) == 1


def test_engine_claims_eligible_draw_and_undo_returns_to_human(app):
    game = Game()
    for uci in ("g1f3", "g8f6", "f3g1", "f6g8", "g1f3", "g8f6", "f3g1"):
        assert game.play(chess.Move.from_uci(uci))
    app.game = game
    app.inputs.game = game
    app.update_engine()
    assert game.claimed_draw is not None
    assert not app.engine.calls
    app.action("undo")
    assert game.outcome is None and game.board.turn == chess.WHITE


def test_setup_selects_human_black_and_starts_engine_opening(app):
    app.action("setup")
    app.draw()
    for name in ("black", "minimax", "more", "start"):
        click(app, app.modal_targets[name].center)
    assert app.settings == EngineSettings(True, chess.BLACK, False, 4)
    assert app.flipped and app.game.board.turn == chess.WHITE
    app.update_engine()
    assert app.engine.busy


def test_diagnostics_compares_without_playing_and_new_position_cancels(app):
    app.action("diagnostics")
    app.draw()
    click(app, app.modal_targets["compare"].center)
    assert app.engine.calls[-1][-1] == "compare"
    app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_ESCAPE))
    assert app.game.play(chess.Move.from_uci("e2e4"))
    app.update_engine()
    assert app.engine.calls[-1][-1] == "play"
    assert len(app.game.records) == 1


def test_terminal_position_does_not_start_engine(app):
    app.game = Game("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1")
    app.inputs.game = app.game
    app.update_engine()
    assert not app.engine.calls


def test_live_progress_never_plays_a_move_or_finishes_request(app):
    human_e4(app)
    token = app._request_token
    before = app.game.board.fen()
    row = SearchStats("Alpha-beta", 3, 1, 21, .001, chess.Move.from_uci("e7e5"), "e5", "+0.00", False)
    app.engine.messages.append(EngineMessage(token, app.game.revision, "play", (row,), finished=False))
    app.update_engine()
    assert app.game.board.fen() == before
    assert app._request_token == token and app.engine.busy
    assert app.search_rows[-1].depth == 1
    app.engine.finish(app)
    app.update_engine()
    assert len(app.game.records) == 2


def test_deepening_can_be_toggled_without_resetting_position(app):
    assert app.game.play(chess.Move.from_uci("e2e4"))
    before = app.game.board.fen()
    app.action("diagnostics")
    app.draw()
    click(app, app.modal_targets["toggle_deepening"].center)
    assert not app.settings.iterative_deepening
    assert app.game.board.fen() == before
    click(app, app.modal_targets["compare"].center)
    assert not app.engine.calls[-1][2].iterative_deepening
    click(app, app.modal_targets["cancel_search"].center)
    assert app.engine.stopped and app.engine.busy


def test_ordering_can_be_toggled_for_comparison_without_resetting_position(app):
    assert app.game.play(chess.Move.from_uci("e2e4"))
    before = app.game.board.fen()
    app.action("diagnostics")
    app.draw()
    click(app, app.modal_targets["toggle_ordering"].center)
    assert not app.settings.move_ordering and not app.search_rows
    assert app.game.board.fen() == before
    click(app, app.modal_targets["compare"].center)
    assert not app.engine.calls[-1][2].move_ordering
    # Settings stay fixed for both algorithms while a comparison is running.
    click(app, app.modal_targets["toggle_ordering"].center)
    assert not app.settings.move_ordering


def test_setup_applies_original_ordering_to_engine_game(app):
    app.action("setup")
    app.draw()
    for name in ("toggle_ordering", "start"):
        click(app, app.modal_targets[name].center)
    assert not app.settings.move_ordering
    human_e4(app)
    assert not app.engine.calls[-1][2].move_ordering


def test_pst_toggle_preserves_board_and_is_locked_during_comparison(app):
    assert app.game.play(chess.Move.from_uci("e2e4"))
    before = app.game.board.fen()
    app.action("diagnostics")
    app.draw()
    click(app, app.modal_targets["toggle_pst"].center)
    assert not app.settings.use_pst and not app.search_rows
    assert app.game.board.fen() == before
    click(app, app.modal_targets["compare"].center)
    assert not app.engine.calls[-1][2].use_pst
    click(app, app.modal_targets["toggle_pst"].center)
    assert not app.settings.use_pst


def test_setup_selects_both_evaluation_modes(app):
    for expected in (False, True):
        app.action("setup")
        app.draw()
        click(app, app.modal_targets["toggle_pst"].center)
        click(app, app.modal_targets["start"].center)
        assert app.settings.use_pst == expected
        human_e4(app)
        assert app.engine.calls[-1][2].use_pst == expected


def test_tt_toggle_preserves_position_and_is_locked_during_comparison(app):
    assert app.game.play(chess.Move.from_uci("e2e4"))
    before = app.game.board.fen()
    app.action("diagnostics")
    app.draw()
    click(app, app.modal_targets["toggle_tt"].center)
    assert not app.settings.transposition_table and not app.search_rows
    assert app.game.board.fen() == before
    click(app, app.modal_targets["compare"].center)
    assert not app.engine.calls[-1][2].transposition_table
    click(app, app.modal_targets["toggle_tt"].center)
    assert not app.settings.transposition_table


def test_setup_selects_both_transposition_modes(app):
    for expected in (False, True):
        app.action("setup")
        app.draw()
        click(app, app.modal_targets["toggle_tt"].center)
        click(app, app.modal_targets["start"].center)
        assert app.settings.transposition_table == expected
        human_e4(app)
        assert app.engine.calls[-1][2].transposition_table == expected


@pytest.mark.parametrize("field,target", [("quiescence", "toggle_quiescence"),
                                          ("principal_variation_search", "toggle_pvs")])
def test_new_search_toggles_preserve_position_and_lock_during_search(app, field, target):
    assert app.game.play(chess.Move.from_uci("e2e4"))
    before = app.game.board.fen()
    app.action("diagnostics")
    app.draw()
    click(app, app.modal_targets[target].center)
    assert getattr(app.settings, field) is False and not app.search_rows
    assert app.game.board.fen() == before
    click(app, app.modal_targets["compare"].center)
    assert getattr(app.engine.calls[-1][2], field) is False
    click(app, app.modal_targets[target].center)
    assert getattr(app.settings, field) is False


def test_setup_new_search_modes_and_minimax_pvs_inactive_state(app):
    app.action("setup")
    app.draw()
    click(app, app.modal_targets["toggle_quiescence"].center)
    click(app, app.modal_targets["toggle_pvs"].center)
    click(app, app.modal_targets["minimax"].center)
    assert "toggle_pvs" not in app.modal_targets
    click(app, app.modal_targets["start"].center)
    assert not app.settings.quiescence and not app.settings.principal_variation_search
    human_e4(app)
    assert not app.engine.calls[-1][2].quiescence
    assert not app.engine.calls[-1][2].principal_variation_search


@pytest.mark.parametrize("size", [(960, 680), (1100, 760)])
def test_engine_setup_and_diagnostics_render_at_supported_sizes(app, size, tmp_path):
    app.resize(size)
    for panel in ("setup", "diagnostics"):
        app.action(panel)
        app.draw()
        assert all(app.surface.get_rect().contains(rect) for rect in app.modal_targets.values())
        pygame.image.save(app.surface, tmp_path / f"{panel}-{size[0]}.png")
        app.settings_dialog = app.diagnostics_dialog = False


def test_full_application_real_engine_reply_and_comparison(tmp_path):
    app = Application(settings=EngineSettings(enabled=True, depth=2))
    try:
        for square in (chess.E2, chess.E4):
            click(app, app.geometry.square_rect(square).center)
        end = time.monotonic() + 8
        while len(app.game.records) < 2 and time.monotonic() < end:
            app.update_engine()
            time.sleep(.01)
        assert len(app.game.records) == 2 and not app.engine_error
        app.action("diagnostics")
        app.start_search("compare")
        end = time.monotonic() + 8
        while app.engine.busy and time.monotonic() < end:
            app.update_engine()
            time.sleep(.01)
        assert len(app.search_rows) == 2
        assert all(row.complete for row in app.search_rows)
        assert app.search_rows[0].move == app.search_rows[1].move
        assert len(app.game.records) == 2
        assert app.last_play_stats.san == app.game.records[-1].san
        app.draw()
        pygame.image.save(app.surface, tmp_path / "comparison.png")
    finally:
        app.close()
