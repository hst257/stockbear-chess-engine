#include "nnue_v3.hpp"
#include "transposition.hpp"
#include "profiling.hpp"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <fstream>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <cstdint>

namespace chesslab {
namespace {
constexpr std::size_t MAX_FLOATS = 1312225;

std::uint32_t rotate(std::uint32_t x, int n) { return (x >> n) | (x << (32 - n)); }
std::array<unsigned char, 32> sha256(const unsigned char* data, std::size_t size) {
    // SHA-256 compression; fixed standard round constants and big-endian blocks.
    constexpr std::uint32_t k[64] = {
        0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
        0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
        0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
        0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
        0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
        0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
        0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
        0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2};
    std::array<std::uint32_t,8> h = {0x6a09e667,0xbb67ae85,0x3c6ef372,0xa54ff53a,
                                    0x510e527f,0x9b05688c,0x1f83d9ab,0x5be0cd19};
    const std::size_t padded = (size + 9 + 63) / 64 * 64;
    for (std::size_t block = 0; block < padded; block += 64) {
        std::uint32_t w[64]{};
        for (int i = 0; i < 64; ++i) {
            const auto pos = block + i;
            unsigned char byte = pos < size ? data[pos] : pos == size ? 0x80 : 0;
            if (pos >= padded - 8) byte = static_cast<unsigned char>((std::uint64_t(size) * 8) >> (8 * (padded - pos - 1)));
            w[i / 4] |= std::uint32_t(byte) << (24 - 8 * (i % 4));
        }
        for (int i = 16; i < 64; ++i) {
            auto s0 = rotate(w[i-15],7) ^ rotate(w[i-15],18) ^ (w[i-15] >> 3);
            auto s1 = rotate(w[i-2],17) ^ rotate(w[i-2],19) ^ (w[i-2] >> 10);
            w[i] = w[i-16] + s0 + w[i-7] + s1;
        }
        auto a=h[0],b=h[1],c=h[2],d=h[3],e=h[4],f=h[5],g=h[6],v=h[7];
        for (int i=0;i<64;++i) {
            auto t1=v+(rotate(e,6)^rotate(e,11)^rotate(e,25))+((e&f)^(~e&g))+k[i]+w[i];
            auto t2=(rotate(a,2)^rotate(a,13)^rotate(a,22))+((a&b)^(a&c)^(b&c));
            v=g;g=f;f=e;e=d+t1;d=c;c=b;b=a;a=t1+t2;
        }
        h[0]+=a;h[1]+=b;h[2]+=c;h[3]+=d;h[4]+=e;h[5]+=f;h[6]+=g;h[7]+=v;
    }
    std::array<unsigned char,32> out{};
    for(int i=0;i<32;++i) out[i]=static_cast<unsigned char>(h[i/4]>>(24-8*(i%4)));
    return out;
}

NnueV3Frame states(const chess::Board& board, int base) {
    profiling::Scope measured(profiling::NNUE_FEATURES);
    NnueV3Frame out;
    for (int p = 0; p < 2; ++p) {
        auto color = p == 0 ? chess::Color::WHITE : chess::Color::BLACK;
        if (board.pieces(chess::PieceType::KING, color).count() != 1) throw std::invalid_argument("V3 requires both kings");
        out.kings[p] = board.kingSq(color).index() ^ (p == 0 ? 0 : 56);
    }
    auto append = [&](int state) {
        out.states[0][out.state_count] = base + state;
        out.states[1][out.state_count++] = base + (state < 4 ? state ^ 2 : state);
    };
    for (int c = 0; c < 2; ++c) {
        const auto color = c == 0 ? chess::Color::WHITE : chess::Color::BLACK;
        const int home = c == 0 ? 0 : 56;
        if (board.kingSq(color).index() != home + 4) continue;
        for (int side = 0; side < 2; ++side) {
            auto right = side == 0 ? chess::Board::CastlingRights::Side::KING_SIDE : chess::Board::CastlingRights::Side::QUEEN_SIDE;
            if (board.castlingRights().has(color,right) && board.at(chess::Square(home + (side == 0 ? 7 : 0))) == chess::Piece(chess::PieceType::ROOK,color)) append(c*2+side);
        }
    }
    if (board.enpassantSq() != chess::Square::NO_SQ) {
        chess::Movelist captures;
        chess::movegen::legalmoves<chess::movegen::MoveGenType::CAPTURE>(captures,board,chess::PieceGenType::PAWN);
        for (auto move : captures) if (move.typeOf() == chess::Move::ENPASSANT) { append(4 + board.enpassantSq().index()%8); break; }
    }
    for (auto& list : out.states) std::sort(list.begin(),list.begin()+out.state_count);
    return out;
}
int feature(int absolute, int p, int king, int buckets) {
    const int type = absolute / 64 % 6;
    if (type == 5) return -1; // Kings condition a perspective, never piece rows.
    const int category = ((absolute / 384) ^ p) * 5 + type;
    if (buckets == 16) king = (king / 16) * 4 + king % 8 / 2;
    return (king * 10 + category) * 64 + ((absolute % 64) ^ (p == 0 ? 0 : 56));
}
void refresh_perspective(const NnueV3Model& model, const chess::Board& board, int p, NnueV3Frame& out) {
    std::array<int,V3_MAX_ACTIVE> active{};
    int count = 0;
    auto occupied = board.occ();
    while (occupied) {
        int sq = occupied.pop();
        auto pc = board.at(chess::Square(sq));
        int index = feature((int(pc.color())*6+int(pc.type()))*64+sq,p,out.kings[p],model.king_buckets);
        if (index < 0) continue;
        if (count >= 30) throw std::invalid_argument("Too many v3 non-king pieces");
        active[count++] = index;
    }
    for (int i=0;i<out.state_count;++i) active[count++]=out.states[p][i];
    std::sort(active.begin(),active.begin()+count);
    std::copy_n(model.weights.data(),32,out.values[p].begin());
    for (int i=0;i<count;++i) {
        const auto* row=model.row(active[i]);
        for (int j=0;j<32;++j) out.values[p][j]+=row[j];
    }
}
}

std::shared_ptr<const NnueV3Model> nnue_v3_load(const std::string& path) {
    std::ifstream file(path,std::ios::binary|std::ios::ate);
    const auto length = file ? file.tellg() : std::streampos(0);
    if (!file || length < 72 || length > std::streamoff(72+MAX_FLOATS*4)) throw std::invalid_argument("Missing or invalid-size v3 model");
    file.seekg(0);
    std::vector<unsigned char> raw(static_cast<std::size_t>(length));
    if (!file.read(reinterpret_cast<char*>(raw.data()),raw.size())) throw std::invalid_argument("Truncated v3 model");
    if (std::memcmp(raw.data(),"SBNNUE3\0",8)) throw std::invalid_argument("Invalid v3 magic");
    const int contract = raw[12];
    const int features = contract == 1 ? 40972 : contract == 2 ? 10252 : 0;
    if (!features) throw std::invalid_argument("Incompatible v3 feature contract");
    const std::size_t floats = (features+1)*32 + 1089;
    if (raw.size() != 72+floats*4) throw std::invalid_argument("Invalid v3 weight size");
    const std::uint32_t expected[8]={3,std::uint32_t(contract),std::uint32_t(features),32,16,4,400,6};
    for (int i=0;i<8;++i) {
        std::uint32_t v=0;
        for(int j=0;j<4;++j) v|=std::uint32_t(raw[8+i*4+j])<<(8*j);
        if(v!=expected[i]) throw std::invalid_argument("Incompatible v3 feature/architecture/precision/scale");
    }
    auto checksum=sha256(raw.data()+72,raw.size()-72);
    if (!std::equal(checksum.begin(),checksum.end(),raw.begin()+40)) throw std::invalid_argument("V3 checksum mismatch");
    auto model=std::make_shared<NnueV3Model>();
    model->king_buckets = contract == 1 ? 64 : 16;
    model->features = features;
    model->weights.resize(floats);
    for (std::size_t i=0;i<floats;++i) {
        std::uint32_t bits=0;
        for(int j=0;j<4;++j) bits|=std::uint32_t(raw[72+4*i+j])<<(8*j);
        std::memcpy(&model->weights[i],&bits,4);
        if (!std::isfinite(model->weights[i]) || std::abs(model->weights[i]) > 1e6f) throw std::invalid_argument("Nonfinite or unsafe-magnitude v3 weights");
    }
    for(int j=0;j<32;++j) if(model->row(features)[j]!=0) throw std::invalid_argument("Nonzero v3 padding");
    for(int i=0;i<64;++i) for(int h=0;h<16;++h) model->head[i][h]=model->weights[floats-1057+h*64+i];
    std::ostringstream hash;
    for(auto byte:checksum) hash<<std::hex<<std::setfill('0')<<std::setw(2)<<int(byte);
    model->payload_sha256=hash.str();
    return model;
}
NnueV3Features nnue_v3_features(const chess::Board& board, int king_buckets) {
    if (king_buckets != 64 && king_buckets != 16) throw std::invalid_argument("Unsupported v3 king buckets");
    auto state=states(board,king_buckets*640);
    NnueV3Features out;
    for (int p=0;p<2;++p) {
        int count=0;
        auto occupied=board.occ();
        while(occupied) {
            int sq=occupied.pop(); auto pc=board.at(chess::Square(sq));
            int index=feature((int(pc.color())*6+int(pc.type()))*64+sq,p,state.kings[p],king_buckets);
            if(index<0) continue;
            if(count>=30) throw std::invalid_argument("Too many v3 pieces");
            out.active[p][count++]=index;
        }
        for(int i=0;i<state.state_count;++i) out.active[p][count++]=state.states[p][i];
        std::sort(out.active[p].begin(),out.active[p].begin()+count);
        out.count=count;
    }
    return out;
}
void nnue_v3_refresh(const NnueV3Model& model, const chess::Board& board, NnueV3Frame& out) {
    profiling::Scope measured(profiling::NNUE_REFRESH);
    out=states(board,model.features-12);
    for(int p=0;p<2;++p) refresh_perspective(model,board,p,out);
}
void nnue_v3_update(const NnueV3Model& model,const NnueV3Frame& parent,const chess::Board& after,const NnueDelta& delta,NnueV3Frame& out) {
    profiling::Scope measured(profiling::NNUE_UPDATE);
    out=states(after,model.features-12);
    for(int p=0;p<2;++p) {
        if(model.king_index(out.kings[p])!=model.king_index(parent.kings[p])) {
            profiling::Scope refresh_measured(profiling::NNUE_REFRESH);
            refresh_perspective(model,after,p,out);
            continue;
        }
        out.values[p]=parent.values[p];
        int changes[18],count=0;
        auto change=[&](int index,bool remove) { if(index>=0) changes[count++]=(index+1)*(remove?-1:1); };
        for(int i=0;i<delta.removed_count;++i) change(feature(delta.removed[i],p,out.kings[p],model.king_buckets),true);
        for(int i=0;i<delta.added_count;++i) change(feature(delta.added[i],p,out.kings[p],model.king_buckets),false);
        for(int i=0;i<parent.state_count;++i) if(!std::binary_search(out.states[p].begin(),out.states[p].begin()+out.state_count,parent.states[p][i])) change(parent.states[p][i],true);
        for(int i=0;i<out.state_count;++i) if(!std::binary_search(parent.states[p].begin(),parent.states[p].begin()+parent.state_count,out.states[p][i])) change(out.states[p][i],false);
        std::sort(changes,changes+count,[](int a,int b){return std::abs(a)<std::abs(b);});
        for(int i=0;i<count;++i) {
            const auto* row=model.row(std::abs(changes[i])-1);
            if(changes[i]<0) for(int j=0;j<32;++j) out.values[p][j]-=row[j];
            else for(int j=0;j<32;++j) out.values[p][j]+=row[j];
        }
    }
}
float nnue_v3_side_to_move(const NnueV3Model& model,const chess::Board& board,const NnueV3Frame& frame) {
    profiling::Scope measured(profiling::NNUE_HEAD);
    float hidden[16];
    const auto size = model.weights.size();
    std::copy_n(model.weights.data()+size-33,16,hidden);
    const int first=board.sideToMove()==chess::Color::WHITE?0:1;
    for(int i=0;i<64;++i) {
        float value=std::clamp(frame.values[first^(i/32)][i%32],0.0f,1.0f);
        for(int h=0;h<16;++h) hidden[h]+=value*model.head[i][h];
    }
    float output=model.weights[size-1];
    for(int h=0;h<16;++h) output+=std::clamp(hidden[h],0.0f,1.0f)*model.weights[size-17+h];
    return output*400;
}
int nnue_v3_white_score(const NnueV3Model& model,const chess::Board& board,const NnueV3Frame& frame) {
    float cp=nnue_v3_side_to_move(model,board,frame)*(board.sideToMove()==chess::Color::WHITE?1:-1);
    return static_cast<int>(std::lround(std::clamp(cp,float(-MATE_THRESHOLD+1),float(MATE_THRESHOLD-1))));
}
} // namespace chesslab
