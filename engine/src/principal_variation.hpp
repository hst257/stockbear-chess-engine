#pragma once

#include <algorithm>
#include <array>
#include <cstdint>
#include <vector>

#include "transposition.hpp"

namespace chesslab {

// Recursive PVs need at most the absolute search ceiling. Only occupied slots
// are written/read; constructing a line does not clear 128 bytes or allocate.
class PrincipalVariation {
    std::array<std::uint16_t, MAX_SEARCH_PLY> moves_;
    std::size_t length_ = 0;
public:
    void clear() { length_ = 0; }
    std::size_t size() const { return length_; }
    bool empty() const { return length_ == 0; }
    chess::Move operator[](std::size_t index) const { return chess::Move(moves_[index]); }
    void emplace_back(std::uint16_t move) { if (length_ < moves_.size()) moves_[length_++] = move; }
    void prepend(chess::Move move, const PrincipalVariation& child) {
        length_ = std::min(child.length_, moves_.size() - 1) + 1;
        moves_[0] = move.move();
        std::copy_n(child.moves_.begin(), length_ - 1, moves_.begin() + 1);
    }
    void publish(std::vector<chess::Move>& destination) const {
        destination.clear();
        destination.reserve(length_);
        for (std::size_t i = 0; i < length_; ++i) destination.emplace_back(moves_[i]);
    }
};

}  // namespace chesslab
