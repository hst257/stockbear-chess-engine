#include "search.hpp"

#include <algorithm>
#include <cmath>
#include <chrono>
#include <iostream>
#include <iterator>
#include <mutex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

namespace {

std::mutex output_mutex;

void output(const std::string& line) {
    std::lock_guard<std::mutex> lock(output_mutex);
    std::cout << line << std::endl;
}

std::string evaluation_json(const chess::Board& board, bool use_pst, const chesslab::EvaluationOptions& options) {
    const auto value = chesslab::evaluate_breakdown(board, use_pst, options);
    constexpr const char* names[] = {"pawn", "knight", "bishop", "rook", "queen", "king"};
    std::ostringstream json;
    json << "{\"use_pst\":" << (use_pst ? "true" : "false")
         << ",\"material\":" << value.material << ",\"pst\":{";
    for (int kind = 0; kind < 6; ++kind) {
        if (kind) json << ',';
        json << '"' << names[kind] << "\":" << value.pst[kind];
    }
    json << "},\"positional\":" << value.positional() << ",\"total\":" << value.total()
         << ",\"phase\":" << value.phase << ",\"advanced\":" << (value.advanced ? "true" : "false");
    if (value.advanced) {
        json << ",\"components\":{";
        for (int i = 0; i < chesslab::COMPONENT_COUNT; ++i) {
            if (i) json << ',';
            const auto c = value.components[i];
            json << '"' << chesslab::COMPONENT_NAMES[i] << "\":{\"mg\":" << c.middlegame
                 << ",\"eg\":" << c.endgame << ",\"cp\":" << chesslab::taper(c, value.phase) << '}';
        }
        json << "},\"mg\":" << value.sum.middlegame << ",\"eg\":" << value.sum.endgame
             << ",\"rounding\":" << value.rounding << ",\"scale\":" << value.scale
             << ",\"scaling\":" << value.scaling;
    }
    json << '}';
    return json.str();
}

void report_info(const chesslab::SearchResult& result, const chess::Board& position,
                 bool completed_iteration) {
    std::ostringstream info;
    info << "info";
    // Final totals after an interruption deliberately omit depth/score/PV.
    // UCI consumers retain the last completed iteration and update its totals.
    if (completed_iteration || result.depth == 0) info << " depth " << result.depth;
    info << " seldepth " << result.selective_depth << " nodes " << result.nodes
         << " time " << result.milliseconds
         << " nps " << result.nodes * 1000 / std::max<std::int64_t>(1, result.milliseconds)
         << " hashfull " << result.hashfull;
    if (completed_iteration && result.depth > 0) {
        const int relative = position.sideToMove() == chess::Color::WHITE ? result.white_score : -result.white_score;
        if (std::abs(relative) >= chesslab::MATE_SCORE - 128) {
            const int distance = (chesslab::MATE_SCORE - std::abs(relative) + 1) / 2;
            info << " score mate " << (relative >= 0 ? distance : -distance);
        } else info << " score cp " << relative;
        if (!result.pv.empty()) {
            info << " pv";
            for (const auto move : result.pv) info << ' ' << chess::uci::moveToUci(move);
        }
    }
    output(info.str());
}

std::string table_info(const chesslab::SearchResult& result) {
    return "tt probes " + std::to_string(result.tt_probes) + " hits " + std::to_string(result.tt_hits) +
           " cutoffs " + std::to_string(result.tt_cutoffs);
}

std::string search_info(const chesslab::SearchResult& result) {
    return "search qnodes " + std::to_string(result.qnodes) +
           " scouts " + std::to_string(result.pvs_scouts) +
           " researches " + std::to_string(result.pvs_researches) +
           " qcaps " + std::to_string(result.qcaps) +
           " plylimit " + std::to_string(result.ply_limit_reached ? 1 : 0);
}

std::string optimization_info(const chesslab::SearchResult& result) {
    return "optim aspiration_attempts " + std::to_string(result.aspiration_attempts) +
           " aspiration_searches " + std::to_string(result.aspiration_searches) +
           " aspiration_fail_high " + std::to_string(result.aspiration_fail_high) +
           " aspiration_fail_low " + std::to_string(result.aspiration_fail_low) +
           " aspiration_retries " + std::to_string(result.aspiration_retries) +
           " aspiration_successes " + std::to_string(result.aspiration_successes) +
           " null_attempts " + std::to_string(result.null_attempts) +
           " null_cutoffs " + std::to_string(result.null_cutoffs) +
           " lmr_attempts " + std::to_string(result.lmr_attempts) +
           " lmr_searches " + std::to_string(result.lmr_searches) +
           " lmr_researches " + std::to_string(result.lmr_researches) +
           " lmr_verifications " + std::to_string(result.lmr_verifications);
}

std::vector<std::string> words(const std::string& line) {
    std::istringstream stream(line);
    return {std::istream_iterator<std::string>(stream), std::istream_iterator<std::string>()};
}

int integer(const std::string& value, int minimum, int maximum) {
    std::size_t end = 0;
    const long long result = std::stoll(value, &end);
    if (end != value.size() || result < minimum || result > maximum) {
        throw std::invalid_argument("number out of range");
    }
    return static_cast<int>(result);
}

bool valid_fen(const std::string& fen) {
    const auto fields = words(fen);
    if (fields.size() != 6 || (fields[1] != "w" && fields[1] != "b")) return false;
    int rank = 7, file = 0, white = 0, black = 0, white_king = -1, black_king = -1;
    for (char c : fields[0]) {
        if (c == '/') {
            if (file != 8 || rank == 0) return false;
            --rank;
            file = 0;
        } else if (c >= '1' && c <= '8') file += c - '0';
        else {
            if (std::string("pnbrqkPNBRQK").find(c) == std::string::npos || file >= 8) return false;
            if ((c == 'p' || c == 'P') && (rank == 0 || rank == 7)) return false;
            if (c >= 'A' && c <= 'Z') ++white;
            else ++black;
            if (c == 'K') {
                if (white_king >= 0) return false;
                white_king = rank * 8 + file;
            }
            if (c == 'k') {
                if (black_king >= 0) return false;
                black_king = rank * 8 + file;
            }
            ++file;
        }
        if (file > 8) return false;
    }
    if (rank != 0 || file != 8 || white > 16 || black > 16 || white_king < 0 || black_king < 0) return false;
    if (std::max(std::abs(white_king / 8 - black_king / 8),
                 std::abs(white_king % 8 - black_king % 8)) <= 1) return false;
    if (fields[2] != "-") {
        std::string seen;
        for (char c : fields[2]) {
            if (std::string("KQkq").find(c) == std::string::npos || seen.find(c) != std::string::npos) return false;
            seen += c;
        }
    }
    if (fields[3] != "-" && (fields[3].size() != 2 || fields[3][0] < 'a' || fields[3][0] > 'h' ||
        fields[3][1] != (fields[1] == "w" ? '6' : '3'))) return false;
    try {
        integer(fields[4], 0, 65535);
        integer(fields[5], 1, 32767);
    } catch (const std::exception&) { return false; }
    return true;
}

chess::Board board_from_fen(const std::string& fen) {
    if (!valid_fen(fen)) throw std::invalid_argument("invalid standard-chess FEN");
    chess::Board candidate;
    if (!candidate.setFen(fen)) throw std::invalid_argument("invalid FEN");
    if (candidate.isAttacked(candidate.kingSq(~candidate.sideToMove()), candidate.sideToMove())) {
        throw std::invalid_argument("opponent king is already in check");
    }
    return candidate;
}

void apply_legal(chess::Board& board, const std::string& uci) {
    chess::Movelist moves;
    chess::movegen::legalmoves(moves, board);
    for (const auto move : moves) {
        if (chess::uci::moveToUci(move) == uci) {
            board.makeMove<true>(move);
            return;
        }
    }
    throw std::invalid_argument("illegal move " + uci);
}

class UciEngine {
public:
    ~UciEngine() { stop_search(); }

    void loop() {
        std::string line;
        while (std::getline(std::cin, line)) {
            const auto tokens = words(line);
            if (tokens.empty()) continue;
            try {
                const auto& command = tokens[0];
                if (command == "uci") {
                    output("id name ChessLab 0.10");
                    output("id author ChessLab contributors");
                    output("option name AlphaBeta type check default true");
                    output("option name IterativeDeepening type check default true");
                    output("option name MoveOrdering type check default true");
                    output("option name UsePST type check default true");
                    output("option name UseAdvancedEvaluation type check default true");
                    for (const auto name : chesslab::EVAL_OPTION_NAMES)
                        output(std::string("option name ") + name + " type check default true");
                    output("option name TranspositionTable type check default true");
                    output("option name Quiescence type check default true");
                    output("option name PVS type check default true");
                    output("option name UseAspirationWindows type check default true");
                    output("option name AspirationDelta type spin default 25 min 1 max 500");
                    output("option name UseNullMovePruning type check default true");
                    output("option name UseLMR type check default true");
                    output("option name LMRReduction type spin default 1 min 1 max 3");
                    output("option name Hash type spin default 16 min 1 max 256");
                    output("option name Depth type spin default 3 min 1 max 8");
                    output("uciok");
                } else if (command == "isready") output("readyok");
                else if (command == "setoption") set_option(tokens);
                else if (command == "position") set_position(tokens);
                else if (command == "ucinewgame") { stop_search(); board_ = chess::Board(); history_ = 0; }
                else if (command == "go") go(tokens);
                else if (command == "stop") stop_search();
                else if (command == "eval") {
                    stop_search();
                    output("info string eval " + evaluation_json(board_, use_pst_, evaluation_));
                }
                else if (command == "quit") break;
                // UCI permits unrecognized commands to be ignored.
            } catch (const std::exception& error) {
                output(std::string("info string error: ") + error.what());
            }
        }
        stop_search();
    }

private:
    chess::Board board_;
    bool alpha_beta_ = true;
    bool iterative_deepening_ = true;
    bool move_ordering_ = true;
    bool use_pst_ = true;
    chesslab::EvaluationOptions evaluation_;
    bool transposition_table_ = true;
    bool quiescence_ = true;
    bool pvs_ = true;
    bool aspiration_windows_ = true;
    int aspiration_delta_ = 25;
    bool null_move_pruning_ = true;
    bool late_move_reductions_ = true;
    int lmr_reduction_ = 1;
    int hash_megabytes_ = 16;
    std::uint64_t history_ = 0;
    int depth_ = 3;
    std::atomic<bool> stopped_{false};
    std::thread worker_;

    void stop_search() {
        stopped_.store(true, std::memory_order_relaxed);
        if (worker_.joinable()) worker_.join();
    }

    void set_option(const std::vector<std::string>& tokens) {
        stop_search();
        if (tokens.size() != 5 || tokens[1] != "name" || tokens[3] != "value") {
            throw std::invalid_argument("expected setoption name <option> value <value> (see uci for supported options)");
        }
        const auto eval_option = std::find(chesslab::EVAL_OPTION_NAMES.begin(), chesslab::EVAL_OPTION_NAMES.end(), tokens[2]);
        if (tokens[2] == "UseAdvancedEvaluation" || eval_option != chesslab::EVAL_OPTION_NAMES.end()) {
            if (tokens[4] != "true" && tokens[4] != "false") throw std::invalid_argument("check options must be true or false");
            if (tokens[2] == "UseAdvancedEvaluation") evaluation_.advanced = tokens[4] == "true";
            else evaluation_.enabled[eval_option - chesslab::EVAL_OPTION_NAMES.begin()] = tokens[4] == "true";
            return;
        }
        if (tokens[2] == "AlphaBeta" || tokens[2] == "IterativeDeepening" ||
            tokens[2] == "MoveOrdering" || tokens[2] == "UsePST" || tokens[2] == "TranspositionTable" ||
            tokens[2] == "Quiescence" || tokens[2] == "PVS" || tokens[2] == "UseAspirationWindows" ||
            tokens[2] == "UseNullMovePruning" || tokens[2] == "UseLMR") {
            if (tokens[4] != "true" && tokens[4] != "false") throw std::invalid_argument("check options must be true or false");
            if (tokens[2] == "AlphaBeta") alpha_beta_ = tokens[4] == "true";
            else if (tokens[2] == "IterativeDeepening") iterative_deepening_ = tokens[4] == "true";
            else if (tokens[2] == "MoveOrdering") move_ordering_ = tokens[4] == "true";
            else if (tokens[2] == "UsePST") use_pst_ = tokens[4] == "true";
            else if (tokens[2] == "TranspositionTable") transposition_table_ = tokens[4] == "true";
            else if (tokens[2] == "Quiescence") quiescence_ = tokens[4] == "true";
            else if (tokens[2] == "PVS") pvs_ = tokens[4] == "true";
            else if (tokens[2] == "UseAspirationWindows") aspiration_windows_ = tokens[4] == "true";
            else if (tokens[2] == "UseNullMovePruning") null_move_pruning_ = tokens[4] == "true";
            else late_move_reductions_ = tokens[4] == "true";
        } else if (tokens[2] == "Depth") depth_ = integer(tokens[4], 1, 8);
        else if (tokens[2] == "Hash") hash_megabytes_ = integer(tokens[4], 1, 256);
        else if (tokens[2] == "AspirationDelta") aspiration_delta_ = integer(tokens[4], 1, 500);
        else if (tokens[2] == "LMRReduction") lmr_reduction_ = integer(tokens[4], 1, 3);
    }

    void set_position(const std::vector<std::string>& tokens) {
        stop_search();
        chess::Board candidate;
        std::uint64_t history = 0;
        std::size_t index = 2;
        if (tokens.size() < 2) throw std::invalid_argument("position needs startpos or fen");
        if (tokens[1] == "fen") {
            if (tokens.size() < 8) throw std::invalid_argument("FEN needs six fields");
            std::string fen;
            for (index = 2; index < 8; ++index) fen += (index == 2 ? "" : " ") + tokens[index];
            candidate = board_from_fen(fen);
        } else if (tokens[1] != "startpos") throw std::invalid_argument("unknown position format");
        if (index < tokens.size()) {
            if (tokens[index++] != "moves") throw std::invalid_argument("expected moves");
            while (index < tokens.size()) {
                const auto previous_key = candidate.hash();
                apply_legal(candidate, tokens[index++]);
                history = chesslab::next_history(history, previous_key, candidate);
            }
        }
        board_ = candidate;  // Invalid commands never replace the previous position.
        history_ = history;
    }

    void go(const std::vector<std::string>& tokens) {
        stop_search();
        chesslab::SearchLimits limits;
        limits.depth = depth_;
        limits.iterative_deepening = iterative_deepening_;
        limits.move_ordering = move_ordering_;
        limits.use_pst = use_pst_;
        limits.evaluation = evaluation_;
        limits.transposition_table = transposition_table_;
        limits.hash_megabytes = hash_megabytes_;
        limits.history = history_;
        limits.quiescence = quiescence_;
        limits.principal_variation_search = pvs_;
        limits.aspiration_windows = aspiration_windows_;
        limits.aspiration_delta = aspiration_delta_;
        limits.null_move_pruning = null_move_pruning_;
        limits.late_move_reductions = late_move_reductions_;
        limits.lmr_reduction = lmr_reduction_;
        bool explicit_depth = false;
        for (std::size_t i = 1; i < tokens.size(); ++i) {
            if (tokens[i] == "infinite") limits.depth = 64;
            else if (tokens[i] == "depth" || tokens[i] == "movetime" || tokens[i] == "nodes") {
                const auto key = tokens[i];
                if (++i >= tokens.size()) throw std::invalid_argument("go limit needs a value");
                const int value = integer(tokens[i], 1, key == "depth" ? 8 : 2000000000);
                if (key == "depth") { limits.depth = value; explicit_depth = true; }
                else if (key == "movetime") limits.milliseconds = value;
                else limits.nodes = value;
            }
        }
        if (!explicit_depth && (limits.milliseconds || limits.nodes)) limits.depth = chesslab::MAX_SEARCH_PLY;
        if (!explicit_depth && limits.milliseconds) {
            limits.time_managed = true;
            limits.iterative_deepening = true;
        }
        stopped_.store(false, std::memory_order_relaxed);
        const auto position = board_;
        const bool pruning = alpha_beta_;
        worker_ = std::thread([this, position, limits, pruning] {
            try {
                const auto result = chesslab::search(position, limits, pruning, stopped_,
                    [&position](const auto& iteration) {
                        output("info string " + table_info(iteration));
                        output("info string " + search_info(iteration));
                        output("info string " + optimization_info(iteration));
                        report_info(iteration, position, true);
                    });
                if (!result.complete) report_info(result, position, false);
                output(std::string("info string ") + (result.complete ? "complete " : "incomplete ") +
                       (pruning ? "alpha-beta " : "minimax ") +
                       (limits.iterative_deepening ? "iterative " : "fixed ") +
                       (limits.move_ordering ? "ordered " : "unordered ") +
                       (limits.use_pst ? "material+pst " : "material ") +
                       (limits.transposition_table ? "cached " : "uncached ") +
                       (limits.quiescence ? "qsearch " : "static-leaf ") +
                       (pruning && limits.principal_variation_search ? "pvs " : "full-window ") +
                       table_info(result) + " " + search_info(result) + " " + optimization_info(result));
                output("bestmove " + (result.best_move == chess::Move{} ? std::string("0000") :
                                      chess::uci::moveToUci(result.best_move)));
            } catch (const std::exception& error) {
                output(std::string("info string search failed: ") + error.what());
                output("bestmove 0000");
            }
        });
    }
};

}  // namespace

int main(int argc, char** argv) {
    try {
        if (argc > 1) {
            const std::string command = argv[1];
            if ((command == "--eval" || command == "--eval-bench") && argc >= 3) {
                bool use_pst = true;
                chesslab::EvaluationOptions options;
                int repeats = 200000;
                for (int i = 2; i < argc - 1; ++i) {
                    const std::string flag = argv[i];
                    if (flag == "--no-pst") use_pst = false;
                    else if (flag == "--baseline") options.advanced = false;
                    else if (flag == "--disable" && i + 1 < argc - 1) {
                        const std::string name = argv[++i];
                        const auto found = std::find(chesslab::EVAL_OPTION_NAMES.begin(), chesslab::EVAL_OPTION_NAMES.end(), name);
                        if (found == chesslab::EVAL_OPTION_NAMES.end()) throw std::invalid_argument("unknown evaluation category");
                        options.enabled[found - chesslab::EVAL_OPTION_NAMES.begin()] = false;
                    } else if (flag == "--repeats" && i + 1 < argc - 1) repeats = integer(argv[++i], 1, 100000000);
                    else throw std::invalid_argument("unknown evaluation flag");
                }
                const auto board = board_from_fen(argv[argc - 1]);
                if (command == "--eval") std::cout << evaluation_json(board, use_pst, options) << '\n';
                else {
                    volatile std::int64_t checksum = 0;
                    const auto start = std::chrono::steady_clock::now();
                    for (int i = 0; i < repeats; ++i) checksum += chesslab::evaluate(board, use_pst, options);
                    const auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now() - start).count();
                    std::cout << "{\"calls\":" << repeats << ",\"ns_per_call\":" << double(ns) / repeats
                              << ",\"checksum\":" << checksum << "}\n";
                }
            } else if (command == "--legal-moves" && argc == 3) {
                auto board = board_from_fen(argv[2]);
                chess::Movelist moves;
                chess::movegen::legalmoves(moves, board);
                for (const auto move : moves) std::cout << chess::uci::moveToUci(move) << '\n';
            } else if (command == "--perft" && (argc == 3 || argc == 4)) {
                auto board = argc == 4 ? board_from_fen(argv[3]) : chess::Board();
                std::cout << chesslab::perft(board, integer(argv[2], 0, 6)) << '\n';
            } else throw std::invalid_argument("usage: chesslab-engine [--perft DEPTH [FEN] | --legal-moves FEN | --eval [--no-pst] [--baseline] [--disable EvalCategory] FEN | --eval-bench [flags] FEN]");
        } else UciEngine().loop();
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
    return 0;
}
