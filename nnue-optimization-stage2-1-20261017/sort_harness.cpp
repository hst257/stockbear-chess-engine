// Deterministic ordering parity and varied-input tiny-sort microbenchmarks.
#include "small_sort.hpp"
#if STAGE21_SORT_MODE == 2
#include "selective_sort.hpp"
#endif
#include <algorithm>
#include <array>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <random>
#include <stdexcept>
#include <string>
using List=std::array<int,16>;
template<class T,class Key>
inline void selected(T* a,int n,Key key) {
#if STAGE21_SORT_MODE == 0
    std::sort(a,a+n,[&](T x,T y) { return key(x)<key(y); });
#elif STAGE21_SORT_MODE == 1
    chesslab::stage2::small_sort(a,n,key);
#else
    chesslab::stage21::tiny_sort(a,n,key);
#endif
}
template<class T> inline void consume(const T& v) { __asm__ volatile("" : : "m"(v) : "memory"); }
int main(int argc,char** argv) {
    const bool bench=argc>1 && std::string(argv[1])=="--bench";
    std::mt19937 rng(20261018);
    std::uint64_t tests=0,mismatches=0,digest=1469598103934665603ULL;
    // Exact integer identity, including opposite signs sharing the same key.
    for(int n=0;n<=16;++n) for(int kind=0;kind<8;++kind) for(int trial=0;trial<1000;++trial) {
        List input{};
        for(int i=0;i<n;++i) {
            int k=kind<3 ? i+1 : 1+int(rng()%780);
            if(kind==3)k=1+int(rng()%4);
            if(kind==4)k=768+int(rng()%13);
            if(kind==5)k=(i%2)?780:1;
            if(kind==6)k=1;
            input[i]=k*(rng()%2 ? 1 : -1);
        }
        if(kind==0) std::sort(input.begin(),input.begin()+n,[](int a,int b){return std::abs(a)<std::abs(b);});
        if(kind==1) std::sort(input.begin(),input.begin()+n,[](int a,int b){return std::abs(a)>std::abs(b);});
        if(kind==2) std::shuffle(input.begin(),input.begin()+n,rng);
        auto expected=input,actual=input;
        std::sort(expected.begin(),expected.begin()+n,[](int a,int b){return std::abs(a)<std::abs(b);});
        selected(actual.data(),n,[](int v){return std::abs(v);});
        ++tests; mismatches+=actual!=expected;
        if(!std::is_sorted(actual.begin(),actual.begin()+n,[](int a,int b){return std::abs(a)<std::abs(b);}))
            throw std::runtime_error("Invalid row ordering");
        // State keys use the actual uint16 representation and duplicate values.
        std::array<std::uint16_t,16> state{},reference{};
        for(int i=0;i<n;++i) state[i]=std::abs(input[i])-1;
        reference=state; std::sort(reference.begin(),reference.begin()+n);
        selected(state.data(),n,[](std::uint16_t v){return v;});
        if(state!=reference)throw std::runtime_error("State sort mismatch");
        ++tests;
        for(int i=0;i<n;++i)digest=(digest^std::uint32_t(actual[i]))*1099511628211ULL;
    }
#if STAGE21_SORT_MODE != 1
    if(mismatches)throw std::runtime_error("Reference equal-key identity mismatch");
#endif
    if(!bench) {
        std::cout<<"{\"passed\":true,\"tests\":"<<tests<<",\"equal_key_identity_mismatches\":"<<mismatches
                 <<",\"legacy_unique_legal_key_contract\":"<<(STAGE21_SORT_MODE==1?"true":"false")<<",\"digest\":\""<<digest<<"\"}\n";
        return 0;
    }
    std::cout<<std::setprecision(12)<<"{\"iterations\":100000,\"cases\":[";
    bool first=true;
    for(int n=0;n<=16;++n) for(int type=0;type<2;++type) {
        std::array<List,256> corpus{};
        for(auto& a:corpus) for(int i=0;i<n;++i) {
            const int k=type?1+int(rng()%780):768+int(rng()%12);
            a[i]=type && rng()%2 ? -k:k;
        }
        auto key=[&](int v){return type?std::abs(v):v;};
        List scratch{};
        for(int i=0;i<1000;++i) { scratch=corpus[i%256];selected(scratch.data(),n,key);consume(scratch); }
        auto start=std::chrono::steady_clock::now();
        for(int i=0;i<100000;++i) {scratch=corpus[i%256];selected(scratch.data(),n,key);consume(scratch);}
        double ns=std::chrono::duration<double,std::nano>(std::chrono::steady_clock::now()-start).count()/100000;
        start=std::chrono::steady_clock::now();
        for(int i=0;i<100000;++i) {scratch=corpus[i%256];consume(scratch);}
        double copy=std::chrono::duration<double,std::nano>(std::chrono::steady_clock::now()-start).count()/100000;
        if(!first)std::cout<<',';first=false;
        std::cout<<"{\"length\":"<<n<<",\"type\":"<<type<<",\"copy_plus_sort_ns\":"<<ns<<",\"copy_reference_ns\":"<<copy<<'}';
    }
    std::cout<<"]}\n";
}
