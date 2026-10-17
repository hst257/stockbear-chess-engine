#pragma once
// Isolated Stage 2.1: measured common zero/one/two-element lists only.
#include <algorithm>
#include <cmath>
#include <cstdint>
namespace chesslab::stage21 {
template<class T,class Key>
inline void tiny_sort(T* values,int count,Key key) {
    if (count<=2) {
        if (count==2 && key(values[1])<key(values[0])) std::swap(values[0],values[1]);
        return;
    }
    // Equal-key and larger-list behavior stays with the reference algorithm.
    std::sort(values,values+count,[&](T a,T b) { return key(a)<key(b); });
}
inline void state_sort(std::uint16_t* values,int count) {
    tiny_sort(values,count,[](std::uint16_t value) { return value; });
}
inline void row_sort(int* values,int count) {
    tiny_sort(values,count,[](int value) { return std::abs(value); });
}
} // namespace chesslab::stage21
