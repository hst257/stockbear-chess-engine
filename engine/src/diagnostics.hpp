#pragma once

// Entirely absent from ordinary builds. Counters describe logical work, not
// hardware cache traffic. They never control evaluation or search decisions.
#ifdef CHESSLAB_DIAGNOSTICS
#include <array>
#include <cstdint>
#include <sstream>
#include <string>

namespace chesslab::diagnostics {
struct Report {
    std::uint64_t updates = 0, copies = 0, refreshes = 0, null_updates = 0;
    std::uint64_t q_updates = 0, normal_updates = 0, unvisited_updates = 0;
    std::uint64_t unused_updates = 0, unused_q_updates = 0, unused_null_updates = 0;
    std::uint64_t unused_leaf_updates = 0, unused_leaf_rows = 0;
    std::uint64_t visits = 0, qvisits = 0, null_visits = 0;
    std::uint64_t evaluated_visits = 0, evaluated_qvisits = 0, evaluated_null_visits = 0;
    std::uint64_t evaluation_calls = 0, evaluated_frames = 0;
    std::uint64_t delta_rows = 0, zero_delta_updates = 0, maximum_delta = 0;
    std::uint64_t copy_payload_bytes = 0, row_weight_bytes = 0, row_value_read_write_bytes = 0;
    std::uint64_t pending_edges = 0, pending_rows = 0, maximum_pending_edges = 0, maximum_pending_rows = 0;
    std::uint64_t frame_bytes = 0, stack_bytes = 0;
    std::array<std::uint64_t, 17> delta_histogram{};
    std::string json() const {
        std::ostringstream out;
        out << '{';
#define CHESSLAB_DIAG_FIELD(name) out << "\"" #name "\":" << name << ','
        CHESSLAB_DIAG_FIELD(updates); CHESSLAB_DIAG_FIELD(copies); CHESSLAB_DIAG_FIELD(refreshes);
        CHESSLAB_DIAG_FIELD(null_updates); CHESSLAB_DIAG_FIELD(q_updates); CHESSLAB_DIAG_FIELD(normal_updates);
        CHESSLAB_DIAG_FIELD(unvisited_updates); CHESSLAB_DIAG_FIELD(unused_updates);
        CHESSLAB_DIAG_FIELD(unused_q_updates); CHESSLAB_DIAG_FIELD(unused_null_updates);
        CHESSLAB_DIAG_FIELD(unused_leaf_updates); CHESSLAB_DIAG_FIELD(unused_leaf_rows);
        CHESSLAB_DIAG_FIELD(visits); CHESSLAB_DIAG_FIELD(qvisits); CHESSLAB_DIAG_FIELD(null_visits);
        CHESSLAB_DIAG_FIELD(evaluated_visits); CHESSLAB_DIAG_FIELD(evaluated_qvisits);
        CHESSLAB_DIAG_FIELD(evaluated_null_visits); CHESSLAB_DIAG_FIELD(evaluation_calls);
        CHESSLAB_DIAG_FIELD(evaluated_frames); CHESSLAB_DIAG_FIELD(delta_rows);
        CHESSLAB_DIAG_FIELD(zero_delta_updates); CHESSLAB_DIAG_FIELD(maximum_delta);
        CHESSLAB_DIAG_FIELD(copy_payload_bytes); CHESSLAB_DIAG_FIELD(row_weight_bytes);
        CHESSLAB_DIAG_FIELD(row_value_read_write_bytes); CHESSLAB_DIAG_FIELD(pending_edges);
        CHESSLAB_DIAG_FIELD(pending_rows); CHESSLAB_DIAG_FIELD(maximum_pending_edges);
        CHESSLAB_DIAG_FIELD(maximum_pending_rows); CHESSLAB_DIAG_FIELD(frame_bytes); CHESSLAB_DIAG_FIELD(stack_bytes);
#undef CHESSLAB_DIAG_FIELD
        out << "\"delta_histogram\":[";
        for (unsigned i = 0; i < delta_histogram.size(); ++i) { if (i) out << ','; out << delta_histogram[i]; }
        out << "]}";
        return out.str();
    }
};
struct Frame {
    bool live = false, root = false, evaluated = false, visited = false;
    bool q = false, null_edge = false, current_q = false, current_null = false, visit_evaluated = false;
    bool descendant_evaluated = false;
    std::uint64_t pending_edges = 0, pending_rows = 0, delta = 0;
};
inline thread_local bool active = false;
inline thread_local Report report;
inline thread_local std::array<Frame, 65> frames;
inline thread_local std::uint64_t last_delta = 0;
inline thread_local bool next_null = false;
inline void reset(bool enabled, std::uint64_t frame_bytes, std::uint64_t stack_bytes) {
    active = enabled; report = {}; frames = {}; last_delta = 0; next_null = false;
    if (active) { report.frame_bytes = frame_bytes; report.stack_bytes = stack_bytes; frames[0].live = true; frames[0].root = true; }
}
inline void retire(Frame& frame) {
    if (!frame.live || frame.root) return;
    if (!frame.visited) ++report.unvisited_updates;
    else if (frame.q) ++report.q_updates;
    else ++report.normal_updates;
    if (!frame.evaluated) {
        ++report.unused_updates;
        if (frame.visited && frame.q) ++report.unused_q_updates;
        if (frame.null_edge) ++report.unused_null_updates;
        if (!frame.descendant_evaluated) { ++report.unused_leaf_updates; report.unused_leaf_rows += frame.delta; }
    }
}
inline void rows(unsigned count, unsigned width, unsigned weight_bytes) {
    if (!active) return;
    last_delta = count;
    report.delta_rows += count;
    report.maximum_delta = count > report.maximum_delta ? count : report.maximum_delta;
    if (count == 0) ++report.zero_delta_updates;
    ++report.delta_histogram[count < 16 ? count : 16];
    // Two perspectives. Values read + written; weights read once per row.
    report.row_weight_bytes += 2ULL * count * width * weight_bytes;
    report.row_value_read_write_bytes += 4ULL * count * width * sizeof(float);
}
inline void copied(std::uint64_t bytes) {
    if (active) { ++report.copies; report.copy_payload_bytes += bytes; }
}
inline void prepare(int ply) {
    if (!active) return;
    const bool null_edge = next_null;
    next_null = false;
    auto& frame = frames[ply];
    retire(frame);
    const auto& parent = frames[ply - 1];
    frame = {}; frame.live = true; frame.null_edge = null_edge;
    frame.delta = last_delta;
    frame.pending_edges = (parent.evaluated || parent.root ? 0 : parent.pending_edges) + 1;
    frame.pending_rows = (parent.evaluated || parent.root ? 0 : parent.pending_rows) + last_delta;
    ++report.updates;
    if (null_edge) ++report.null_updates;
}
inline void visit(int ply, bool q, bool null_subtree) {
    if (!active) return;
    auto& frame = frames[ply];
    if (!frame.visited) frame.q = q;
    frame.visited = true; frame.current_q = q; frame.current_null = null_subtree; frame.visit_evaluated = false;
    ++report.visits;
    if (q) ++report.qvisits;
    if (null_subtree) ++report.null_visits;
}
inline void evaluation(int ply) {
    if (!active) return;
    auto& frame = frames[ply];
    ++report.evaluation_calls;
    if (!frame.visit_evaluated) {
        ++report.evaluated_visits;
        if (frame.current_q) ++report.evaluated_qvisits;
        if (frame.current_null) ++report.evaluated_null_visits;
        frame.visit_evaluated = true;
    }
    if (!frame.evaluated) {
        for (int ancestor = ply - 1; ancestor >= 0 && !frames[ancestor].descendant_evaluated; --ancestor)
            frames[ancestor].descendant_evaluated = true;
        ++report.evaluated_frames;
        report.pending_edges += frame.pending_edges; report.pending_rows += frame.pending_rows;
        if (frame.pending_edges > report.maximum_pending_edges) report.maximum_pending_edges = frame.pending_edges;
        if (frame.pending_rows > report.maximum_pending_rows) report.maximum_pending_rows = frame.pending_rows;
        frame.evaluated = true;
    }
}
inline Report finish() {
    if (active) for (auto& frame : frames) retire(frame);
    active = false;
    return report;
}
}  // namespace chesslab::diagnostics
#endif
