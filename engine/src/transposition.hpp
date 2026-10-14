#pragma once

#include <algorithm>
#include <array>
#include <cstdint>
#include <optional>
#include <vector>

#include "chess.hpp"

namespace chesslab {

inline constexpr int MATE_SCORE = 30000;
inline constexpr int MATE_THRESHOLD = MATE_SCORE - 128;
inline constexpr int MAX_SEARCH_PLY = 64;

// A multiset fingerprint of prior positions since the last pawn move/capture.
// Addition preserves multiplicity while permitting equivalent move orders.
inline std::uint64_t history_component(std::uint64_t key) {
    key += 0x9e3779b97f4a7c15ULL;
    key = (key ^ (key >> 30)) * 0xbf58476d1ce4e5b9ULL;
    key = (key ^ (key >> 27)) * 0x94d049bb133111ebULL;
    return key ^ (key >> 31);
}

inline std::uint64_t next_history(std::uint64_t previous, std::uint64_t parent_key,
                                  const chess::Board& child) {
    return child.halfMoveClock() == 0 ? 0 : previous + history_component(parent_key);
}

inline int score_to_table(int score, int ply) {
    return score >= MATE_THRESHOLD ? score + ply : score <= -MATE_THRESHOLD ? score - ply : score;
}

inline int score_from_table(int score, int ply) {
    return score >= MATE_THRESHOLD ? score - ply : score <= -MATE_THRESHOLD ? score + ply : score;
}

enum class Bound : std::uint8_t { EXACT, LOWER, UPPER };

struct TableEntry {
    std::uint64_t key = 0;
    std::uint64_t history = 0;
    int score = 0;
    std::int16_t depth = -1;  // Empty slots cannot match even a zero Zobrist key.
    std::uint8_t halfmove = 0;
    Bound bound = Bound::EXACT;
    std::uint8_t length = 0;
    // Compact, complete PVs keep exact hits useful without chasing evicted slots.
    std::array<std::uint16_t, MAX_SEARCH_PLY> pv{};

    chess::Move move() const { return length ? chess::Move(pv[0]) : chess::Move{}; }
};

inline std::optional<int> table_score(const TableEntry& entry, int depth, int ply,
                                      int alpha, int beta, bool pruning) {
    // Greater-depth values describe a different horizon; only use their move.
    if (entry.depth != depth) return std::nullopt;
    const int score = score_from_table(entry.score, ply);
    if (entry.bound == Bound::EXACT || (pruning &&
        ((entry.bound == Bound::LOWER && score >= beta) ||
         (entry.bound == Bound::UPPER && score <= alpha)))) return score;
    return std::nullopt;
}

class TranspositionTable {
public:
    explicit TranspositionTable(int megabytes = 16) {
        const auto capacity = static_cast<std::size_t>(std::clamp(megabytes, 1, 256)) * 1024 * 1024 /
                              sizeof(TableEntry);
        std::size_t size = 1;
        while (size <= capacity / 2) size *= 2;
        entries_.resize(size);
    }

    const TableEntry* probe(std::uint64_t key, std::uint64_t history, unsigned halfmove) const {
        const auto& entry = entries_[index(key, history, halfmove)];
        return entry.depth >= 0 && entry.key == key && entry.history == history &&
               entry.halfmove == halfmove ? &entry : nullptr;
    }

    void store(std::uint64_t key, std::uint64_t history, unsigned halfmove, int depth,
               int score, Bound bound, const std::vector<chess::Move>& pv) {
        auto& entry = entries_[index(key, history, halfmove)];
        const bool same = entry.depth >= 0 && entry.key == key && entry.history == history &&
                          entry.halfmove == halfmove;
        // Prefer deeper entries; at equal depth preserve exact scores over bounds.
        if (entry.depth > depth || (same && entry.depth == depth &&
                                   entry.bound == Bound::EXACT && bound != Bound::EXACT)) return;
        if (entry.depth < 0) ++occupied_;
        entry.key = key;
        entry.history = history;
        entry.halfmove = static_cast<std::uint8_t>(halfmove);
        entry.depth = static_cast<std::int16_t>(depth);
        entry.score = score;
        entry.bound = bound;
        entry.length = static_cast<std::uint8_t>(std::min(pv.size(), entry.pv.size()));
        for (std::size_t i = 0; i < entry.length; ++i) entry.pv[i] = pv[i].move();
    }

    int hashfull() const { return static_cast<int>(occupied_ * 1000 / entries_.size()); }
    std::size_t size() const { return entries_.size(); }

private:
    std::vector<TableEntry> entries_;
    std::size_t occupied_ = 0;

    std::size_t index(std::uint64_t key, std::uint64_t history, unsigned halfmove) const {
        return (key ^ history_component(history) ^ history_component(halfmove)) & (entries_.size() - 1);
    }
};

}  // namespace chesslab
