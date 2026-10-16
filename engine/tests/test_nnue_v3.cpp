#include "nnue_v3.hpp"
#include <algorithm>
#include <cmath>
#include <iostream>
#include <iomanip>
#include <random>
#include <stdexcept>

int main(int argc,char** argv) {
    try {
        if(argc<2) throw std::invalid_argument("Expected model path [--verify]");
        auto model=chesslab::nnue_v3_load(argv[1]);
        if(argc>2 && std::string(argv[2])=="--head") {
            constexpr float patterns[]={-1e6f,-1.0f,0.0f,1e-7f,.5f,1.0f,1.0000001f,1e6f};
            std::cout<<'['<<std::setprecision(10);
            for(int n=0;n<8;++n) for(int turn=0;turn<2;++turn) {
                chess::Board board;
                if(turn) board.makeNullMove();
                chesslab::NnueV3Frame frame;
                for(int p=0;p<2;++p) for(int j=0;j<32;++j) frame.values[p][j]=patterns[(n+p+j)%8];
                if(n||turn) std::cout<<',';
                std::cout<<chesslab::nnue_v3_side_to_move(*model,board,frame);
            }
            std::cout<<"]\n";
        } else if(argc>2 && std::string(argv[2])=="--verify") {
            std::mt19937 rng(20261016);
            float max_lane=0,max_cp=0;
            std::uint64_t transitions=0,nulls=0,king_refreshes=0;
            const char* roots[]={chess::constants::STARTPOS,
                "r3k2r/8/8/3pP3/8/8/8/R3K2R w KQkq d6 0 1",
                "7k/4P3/8/8/8/8/8/K7 w - - 0 1",
                "4r2k/8/8/2PpP3/8/8/8/4K3 w - d6 0 1",
                "4r2k/8/8/3pP3/8/8/8/4K3 w - d6 0 1",
                "8/8/8/3k4/8/4K3/3P4/8 w - - 0 1"};
            auto compare=[&](const chess::Board& board,const chesslab::NnueV3Frame& a) {
                chesslab::NnueV3Frame b;chesslab::nnue_v3_refresh(*model,board,b);
                if(a.kings!=b.kings || a.states!=b.states || a.state_count!=b.state_count) throw std::logic_error("V3 metadata mismatch");
                for(int p=0;p<2;++p) for(int j=0;j<32;++j) max_lane=std::max(max_lane,std::abs(a.values[p][j]-b.values[p][j]));
                max_cp=std::max(max_cp,std::abs(chesslab::nnue_v3_side_to_move(*model,board,a)-chesslab::nnue_v3_side_to_move(*model,board,b)));
            };
            for(int walk=0;walk<180;++walk) {
                chess::Board board(roots[walk%6]);
                chesslab::NnueV3Frame parent;chesslab::nnue_v3_refresh(*model,board,parent);
                for(int ply=0;ply<128;++ply) {
                    chess::Movelist moves;chess::movegen::legalmoves(moves,board);
                    if(moves.empty()) break;
                    const auto fen=board.getFen();const auto saved=parent;
                    // Every legal sibling at fixture roots, then three per ply.
                    const int limit=ply==0?int(moves.size()):std::min(3,int(moves.size()));
                    for(int n=0;n<limit;++n) {
                        auto move=moves[n];auto delta=chesslab::nnue_move_delta(board,move);
                        board.makeMove(move);chesslab::NnueV3Frame child;
                        chesslab::nnue_v3_update(*model,parent,board,delta,child);compare(board,child);
                        for(int p=0;p<2;++p) king_refreshes+=model->king_index(child.kings[p])!=model->king_index(parent.kings[p]);
                        ++transitions;board.unmakeMove(move);
                        if(board.getFen()!=fen || parent.values!=saved.values) throw std::logic_error("Sibling/board restoration failed");
                    }
                    if(!board.inCheck()) {
                        board.makeNullMove();chesslab::NnueV3Frame child;
                        chesslab::nnue_v3_update(*model,parent,board,{},child);compare(board,child);
                        board.unmakeNullMove();++nulls;
                        if(board.getFen()!=fen || parent.values!=saved.values) throw std::logic_error("Null restoration failed");
                    }
                    auto move=moves[rng()%moves.size()];auto delta=chesslab::nnue_move_delta(board,move);
                    board.makeMove(move);chesslab::NnueV3Frame child;
                    chesslab::nnue_v3_update(*model,parent,board,delta,child);parent=child;compare(board,parent);++transitions;
                }
            }
            std::cout<<std::setprecision(10)<<"{\"transitions\":"<<transitions<<",\"nulls\":"<<nulls<<",\"king_refreshes\":"<<king_refreshes
                     <<",\"max_lane_error\":"<<max_lane<<",\"max_cp_error\":"<<max_cp<<",\"frame_bytes\":"<<sizeof(chesslab::NnueV3Frame)<<"}\n";
            if(max_lane>1e-4f || max_cp>.02f) throw std::logic_error("V3 incremental tolerance exceeded");
        } else {
            std::string fen;
            while(std::getline(std::cin,fen)) {
                chess::Board board(fen);chesslab::NnueV3Frame frame;chesslab::nnue_v3_refresh(*model,board,frame);
                auto active=chesslab::nnue_v3_features(board,model->king_buckets);
                std::cout<<std::setprecision(10)<<"{\"cp\":"<<chesslab::nnue_v3_side_to_move(*model,board,frame)<<",\"features\":[";
                for(int p=0;p<2;++p) {if(p)std::cout<<',';std::cout<<'[';for(int i=0;i<active.count;++i){if(i)std::cout<<',';std::cout<<active.active[p][i];}std::cout<<']';}
                std::cout<<"]}\n";
            }
        }
    } catch(const std::exception& e) {std::cerr<<e.what()<<'\n';return 1;}
}
