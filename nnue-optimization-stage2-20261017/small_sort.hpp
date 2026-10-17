#pragma once
// Isolated Stage 2 candidate: remove generic sorting machinery for tiny lists.
// State keys are unique (<=5); legal move-derived row keys are unique (<=16).
// Sorting by absolute feature index retains the original float operation order.
namespace chesslab::stage2 {
template<class T, class Key>
inline void small_sort(T* values, int count, Key key) {
    for (int i = 1; i < count; ++i) {
        const T value = values[i];
        const auto value_key = key(value);
        int j = i;
        while (j > 0 && key(values[j - 1]) > value_key) {
            values[j] = values[j - 1];
            --j;
        }
        values[j] = value;
    }
}
}  // namespace chesslab::stage2
