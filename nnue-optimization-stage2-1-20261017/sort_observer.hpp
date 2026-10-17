#pragma once
// Observer only: never included in a timed candidate or production source.
#include <algorithm>
#include <array>
#include <cstdint>
#include <cstdlib>
#include <fstream>
#include <string>
namespace chesslab::sort_observer {
struct Bucket {
    std::uint64_t calls=0, sorted=0, reverse=0, equal=0, comparisons=0;
    std::uint64_t insertion_comparisons=0, insertion_moves=0;
    std::array<std::uint64_t,16> key_bins{};
};
inline thread_local Bucket buckets[2][8][2][17];
inline thread_local int phase=0, kind=0;
struct Phase {
    int previous;
    explicit Phase(int next): previous(phase) { phase=next; }
    ~Phase() { phase=previous; }
};
inline void reset() {
    for (auto& phases:buckets) for (auto& kinds:phases)
        for (auto& types:kinds) for (auto& b:types) b=Bucket{};
    phase=kind=0;
}
template<class T>
inline void sort(T* values,int count,bool rows) {
    auto& b=buckets[phase][kind][rows?1:0][count];
    auto key=[&](T v) { return rows ? std::abs(int(v)) : int(v); };
    bool sorted=true,reverse=true,equal=false;
    int shadow[16];
    for (int i=0;i<count;++i) {
        const auto k=key(values[i]); shadow[i]=k;
        ++b.key_bins[std::min(15,k/49)];
        if (i) { sorted &= key(values[i-1])<=k; reverse &= key(values[i-1])>=k; }
        for (int j=0;j<i;++j) equal |= key(values[j])==k;
    }
    for (int i=1;i<count;++i) {
        const int v=shadow[i]; int j=i;
        while (j>0) {
            ++b.insertion_comparisons;
            if (shadow[j-1]<=v) break;
            shadow[j]=shadow[j-1]; --j; ++b.insertion_moves;
        }
        shadow[j]=v;
    }
    ++b.calls; b.sorted+=sorted; b.reverse+=reverse; b.equal+=equal;
    std::sort(values,values+count,[&](T a,T c) { ++b.comparisons; return key(a)<key(c); });
}
inline void finish(const std::string& fen,std::uint64_t nodes) {
    const char* path=std::getenv("STOCKBEAR_SORT_OBSERVER");
    if (!path) return;
    std::ofstream out(path,std::ios::app);
    out << "{\"fen\":\"" << fen << "\",\"nodes\":" << nodes << ",\"buckets\":[";
    bool first=true;
    for (int p=0;p<2;++p) for (int k=0;k<8;++k) for (int t=0;t<2;++t) for (int n=0;n<=16;++n) {
        const auto& b=buckets[p][k][t][n]; if (!b.calls) continue;
        if (!first) out<<','; first=false;
        out << "{\"phase\":"<<p<<",\"kind\":"<<k<<",\"type\":"<<t<<",\"length\":"<<n
            <<",\"calls\":"<<b.calls<<",\"sorted\":"<<b.sorted<<",\"reverse\":"<<b.reverse
            <<",\"equal\":"<<b.equal<<",\"comparisons\":"<<b.comparisons
            <<",\"shadow_insertion_comparisons\":"<<b.insertion_comparisons
            <<",\"shadow_insertion_moves\":"<<b.insertion_moves<<",\"key_bins\":[";
        for(int i=0;i<16;++i) { if(i)out<<','; out<<b.key_bins[i]; } out<<"]}";
    }
    out << "]}\n";
}
} // namespace chesslab::sort_observer
