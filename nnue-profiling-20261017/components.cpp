// Measurement harness only. Independently spells out the frozen float head;
// never linked into the application or used to select a chess move.
#include "nnue.hpp"
#include "nnue_weights.hpp"
#include "transposition.hpp"
#include <algorithm>
#include <atomic>
#include <chrono>
#include <cmath>
#include <cstring>
#include <iostream>
#include <random>
#include <windows.h>
#include <cpuid.h>
using namespace chesslab;
namespace w = chesslab::nnue_weights;
volatile double checksum = 0;
template<class F> double measure(int n, F f) {
    for (int i=0;i<1000;++i) f(i);
    const auto start=std::chrono::steady_clock::now();
    for(int i=0;i<n;++i) { f(i); std::atomic_signal_fence(std::memory_order_seq_cst); }
    return double(std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now()-start).count())/n;
}
__attribute__((noinline)) void activation(const NnueAccumulator& a, int first, float* input) {
    for(int p=0;p<2;++p) for(int j=0;j<w::WIDTH;++j)
        input[p*w::WIDTH+j]=std::clamp(a.values[p==0?first:1-first][j],0.f,1.f);
}
__attribute__((noinline)) void dense(const NnueAccumulator& a,int first,float* destination) {
    // Match production's local aligned buffer and register promotion. Writing
    // a caller-visible buffer on every row falsely inflates this component.
    alignas(64) float hidden[w::HIDDEN];
    std::copy_n(w::fc1_bias,w::HIDDEN,hidden);
    for(int p=0;p<2;++p) for(int j=0;j<w::WIDTH;++j) {
        const float input=std::clamp(a.values[p==0?first:1-first][j],0.f,1.f);
        const auto* weights=w::fc1_transposed+(p*w::WIDTH+j)*w::HIDDEN;
        for(int h=0;h<w::HIDDEN;++h) hidden[h]+=weights[h]*input;
    }
    std::copy_n(hidden,w::HIDDEN,destination);
}
__attribute__((noinline)) float output_layer(const float* hidden) {
    float value=w::fc2_bias[0];
    for(int h=0;h<w::HIDDEN;++h) value+=w::fc2_weight[h]*std::clamp(hidden[h],0.f,1.f);
    return value*400.f;
}
__attribute__((noinline)) int score_conversion(float cp) {
    return int(std::lround(std::clamp(cp,float(-MATE_THRESHOLD+1),float(MATE_THRESHOLD-1))));
}
int main(int argc,char**argv) {
    if(argc==2 && std::string(argv[1])=="--varied") {
        // Deterministic legal walks are timing fixtures, not engine games,
        // tournament outcomes, training examples or held-out data.
        std::array<NnueAccumulator,512> frames;
        std::array<chess::Board,512> boards;
        chess::Board board; std::mt19937 rng(20261017);
        for(int i=0;i<512;++i) {
            chess::Movelist legal; chess::movegen::legalmoves(legal,board);
            if(i%64==0 || legal.empty()) {board=chess::Board();chess::movegen::legalmoves(legal,board);}
            board.makeMove<true>(legal[rng()%legal.size()]);
            boards[i]=board;nnue_refresh(board,frames[i]);
        }
        std::cout<<"{\"seed\":20261017,\"frames\":512,\"frame_storage_bytes\":"<<sizeof(frames);
        for(int size:{1,32,128,512}) {
            std::cout<<",\"head_"<<size<<"_positions_ns\":"<<measure(200000,[&](int i){checksum+=nnue_side_to_move(boards[i%size],frames[i%size]);});
        }
        std::cout<<",\"checksum\":"<<checksum<<"}\n";return 0;
    }
    if(argc==2 && std::string(argv[1])=="--cores") {
        std::cout<<"[";
        for(unsigned i=0;i<12;++i) {
            SetThreadAffinityMask(GetCurrentThread(),DWORD_PTR(1)<<i);
            unsigned a,b,c,d; __cpuid_count(0x1a,0,a,b,c,d); const unsigned type=a>>24;
            __cpuid_count(7,1,a,b,c,d);
            if(i)std::cout<<",";
            std::cout<<"{\"logical_cpu\":"<<i<<",\"hybrid_core_type\":"<<type<<",\"avx_vnni\":"<<((a&(1<<4))?"true":"false")<<"}";
        }
        std::cout<<"]\n"; return 0;
    }
    if(argc<2)return 1;
    chess::Board board(argv[1]); const int n=argc>2?std::stoi(argv[2]):100000;
    nnue_set_kernel("scalar");
    NnueAccumulator parent,child; nnue_refresh(board,parent);
    chess::Movelist moves; chess::movegen::legalmoves(moves,board);
    if(moves.empty())return 2;
    auto after=board; const auto move=moves[0]; const auto delta=nnue_move_delta(board,move);
    after.makeMove<true>(move); auto states=nnue_search_states(after);
    alignas(64) float hidden[w::HIDDEN],input[2*w::WIDTH];
    const int first=board.sideToMove()==chess::Color::WHITE?0:1;
    dense(parent,first,hidden);
    auto result=output_layer(hidden),reference=nnue_side_to_move(board,parent);
    if(std::memcmp(&result,&reference,sizeof(float)))throw std::runtime_error("head bit parity");
    std::mt19937 rng(20261017);
    for(int k=0;k<200;++k) {
        auto a=parent;
        for(auto& side:a.values)for(float&v:side)v=float(int(rng()%40001)-20000)/1000;
        dense(a,k%2,hidden); result=output_layer(hidden);
        auto sideboard=board; if((sideboard.sideToMove()==chess::Color::WHITE?0:1)!=k%2)sideboard.makeNullMove();
        reference=nnue_side_to_move(sideboard,a);
        if(std::memcmp(&result,&reference,sizeof(float)))throw std::runtime_error("random head bit parity");
    }
    dense(parent,first,hidden); activation(parent,first,input);
    int zeros=0,saturated=0; for(float v:input){zeros+=v==0;saturated+=v==1;}
    auto emit=[&](const char*name,auto f){std::cout<<",\""<<name<<"\":"<<measure(n,f);};
    std::cout<<"{\"head_parity_cases\":201,\"zero_inputs\":"<<zeros<<",\"saturated_inputs\":"<<saturated;
    emit("harness_ns",[&](int){checksum+=1.;});
    emit("delta_ns",[&](int){checksum+=nnue_move_delta(board,move).removed_count;});
    emit("state_ns",[&](int){checksum+=nnue_search_states(after).count;});
    emit("compact_update_ns",[&](int){nnue_update_search(parent,after,delta,child);checksum+=child.values[0][0];});
    emit("compact_rows_metadata_ns",[&](int){nnue_update_search_states(parent,states,delta,child);checksum+=child.values[0][0];});
    emit("activation_ns",[&](int i){activation(parent,first,input);checksum+=input[i%(2*w::WIDTH)];});
    emit("dense_with_input_clip_ns",[&](int i){dense(parent,first,hidden);checksum+=hidden[i%w::HIDDEN];});
    emit("hidden_clip_output_ns",[&](int){checksum+=output_layer(hidden);});
    emit("score_conversion_ns",[&](int i){checksum+=score_conversion(float(i%2001)-1000);});
    emit("production_head_ns",[&](int){checksum+=nnue_side_to_move(board,parent);});
    std::cout<<",\"frame_bytes\":"<<sizeof(NnueAccumulator)<<",\"state_bytes\":"<<sizeof(NnueSearchFeatures)<<",\"checksum\":"<<checksum<<"}\n";
}
