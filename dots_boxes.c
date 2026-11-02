// AI used: ChatGPT (OpenAI), GPT-6
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <string.h>

#define MAXR 10
#define MAXC 10
#define MAXB 100
#define MAXE 220
#define EXACT_LIMIT 20
#define SIM_BUDGET 24000

typedef struct { int R, C, E, B, hCount; } Topology;
typedef struct { unsigned char drawn[MAXE]; unsigned char sides[MAXB]; } Board;

static Topology T;
static int edge_boxes[MAXE][2], edge_box_count[MAXE];
static int box_active[MAXB], box_edges[MAXB][4];

static void add_incident(int e, int b) {
    edge_boxes[e][edge_box_count[e]++] = b;
}
static void build_topology(int R, int C) {
    T.R=R; T.C=C; T.B=R*C; T.hCount=(R+1)*C; T.E=T.hCount+R*(C+1);
    memset(edge_box_count,0,sizeof(edge_box_count));
    for (int b=0;b<T.B;b++) box_active[b]=1;
    for (int r=0;r<R;r++) for (int c=0;c<C;c++) {
        int b=r*C+c;
        int top=r*C+c, bottom=(r+1)*C+c;
        int left=T.hCount+r*(C+1)+c, right=left+1;
        box_edges[b][0]=top; box_edges[b][1]=bottom;
        box_edges[b][2]=left; box_edges[b][3]=right;
        add_incident(top,b); add_incident(bottom,b);
        add_incident(left,b); add_incident(right,b);
    }
}
static int apply_edge(Board *b, int e) {
    if (e<0 || e>=T.E || b->drawn[e]) return 0;
    b->drawn[e]=1;
    int got=0;
    for(int k=0;k<edge_box_count[e];k++) {
        int x=edge_boxes[e][k];
        if(box_active[x] && ++b->sides[x]==4) got++;
    }
    return got;
}
static int edge_gain(const Board *b,int e) {
    int g=0;
    for(int k=0;k<edge_box_count[e];k++) {
        int x=edge_boxes[e][k]; if(box_active[x] && b->sides[x]==3) g++;
    }
    return g;
}
static int is_safe(const Board *b,int e) {
    for(int k=0;k<edge_box_count[e];k++) {
        int x=edge_boxes[e][k]; if(box_active[x] && b->sides[x]==2) return 0;
    }
    return 1;
}
static int safe_count(const Board *b) {
    int n=0; for(int e=0;e<T.E;e++) if(!b->drawn[e] && is_safe(b,e)) n++; return n;
}
static int free_count(const Board *b) {
    int n=0; for(int e=0;e<T.E;e++) n+=!b->drawn[e]; return n;
}
static int bitcount(uint32_t x) { return __builtin_popcount(x); }

/* Exact negamax for small endings. Value is boxes earned by side to move minus
   boxes earned by the other side. Captures grant another move. */
static int exact_n, local_edge[MAXE], base_sides[MAXB];
static uint32_t local_box_mask[MAXB];
static int8_t *memo;
static int exact_ready;
static uint32_t exact_full_mask;

typedef struct { int boxes, loop; } Component;
static Component components[MAXB];
static int component_count, component_of[MAXB];
static int8_t *component_memo;
static size_t component_memo_size;
static int active_component_boxes[MAXB];
static int active_component_loop;
static int simulated_steps;
static int local_gain(uint32_t mask, int i) {
    int g=0, e=local_edge[i];
    for(int k=0;k<edge_box_count[e];k++) {
        int b=edge_boxes[e][k];
        if(box_active[b] && base_sides[b]+bitcount(mask & local_box_mask[b])==3) g++;
    }
    return g;
}
static int solve_exact(uint32_t mask) {
    int8_t *slot=&memo[mask];
    if(*slot!=-128) return *slot;
    uint32_t left=((uint32_t)1u<<exact_n)-1u;
    left^=mask;
    if(!left) { *slot=0; return 0; }
    int best=-1000;
    /* Captures first improve pruning-like early bests even without alpha-beta. */
    for(int pass=0;pass<2;pass++) for(int i=0;i<exact_n;i++) {
        uint32_t bit=(uint32_t)1u<<i;
        if(!(left&bit)) continue;
        int g=local_gain(mask,i);
        if((pass==0)!=(g>0)) continue;
        int v=g ? g+solve_exact(mask|bit) : -solve_exact(mask|bit);
        if(v>best) best=v;
    }
    *slot=(int8_t)best;
    return best;
}
static int exact_choice(const Board *b) {
    if (!exact_ready) {
        exact_n=0;
        for(int e=0;e<T.E;e++) if(!b->drawn[e]) local_edge[exact_n++]=e;
        for(int x=0;x<T.B;x++) {
            base_sides[x]=b->sides[x]; local_box_mask[x]=0;
        }
        for(int i=0;i<exact_n;i++) {
            int e=local_edge[i];
            for(int k=0;k<edge_box_count[e];k++)
                local_box_mask[edge_boxes[e][k]]|=(uint32_t)1u<<i;
        }
        exact_full_mask=((uint32_t)1u<<exact_n)-1u;
        size_t states=(size_t)1u<<exact_n;
        memo=(int8_t*)malloc(states*sizeof(int8_t));
        if(!memo) return local_edge[0];
        memset(memo,0x80,states*sizeof(int8_t));
        exact_ready=1;
    }

    uint32_t mask=0;
    for(int i=0;i<exact_n;i++) if(b->drawn[local_edge[i]]) mask|=(uint32_t)1u<<i;
    uint32_t left=exact_full_mask^mask;
    if(!left) return -1;

    int best=-1000, choice=-1;
    for(int pass=0;pass<2;pass++) for(int i=0;i<exact_n;i++) {
        uint32_t bit=(uint32_t)1u<<i;
        if(!(left&bit)) continue;
        int g=local_gain(mask,i);
        if((pass==0)!=(g>0)) continue;
        int v=g ? g+solve_exact(mask|bit) : -solve_exact(mask|bit);
        if(v>best) { best=v; choice=local_edge[i]; }
    }
    return choice;
}

/* In a no-capture/no-safe position every unfinished box has two open sides.
   The graph formed by shared open sides then consists of chains and loops. */
static int find_components(const Board *b) {
    int deg[MAXB]={0}, adj[MAXB][4];
    for(int x=0;x<T.B;x++) component_of[x]=-1;
    for(int x=0;x<T.B;x++) if(box_active[x] && b->sides[x]<4 && b->sides[x]!=2) return 0;
    for(int e=0;e<T.E;e++) if(!b->drawn[e] && edge_box_count[e]==2) {
        int a=edge_boxes[e][0], d=edge_boxes[e][1];
        if(box_active[a] && box_active[d] && b->sides[a]==2 && b->sides[d]==2) {
            if(deg[a]<4 && deg[d]<4) { adj[a][deg[a]++]=d; adj[d][deg[d]++]=a; }
        }
    }
    component_count=0;
    for(int start=0;start<T.B;start++) if(box_active[start] && b->sides[start]==2 && component_of[start]<0) {
        int q[MAXB], head=0, tail=0, sumdeg=0;
        int id=component_count++;
        q[tail++]=start; component_of[start]=id;
        while(head<tail) {
            int x=q[head++]; sumdeg+=deg[x];
            for(int k=0;k<deg[x];k++) if(component_of[adj[x][k]]<0) {
                component_of[adj[x][k]]=id; q[tail++]=adj[x][k];
            }
        }
        components[id].boxes=tail;
        components[id].loop=(sumdeg/2==tail && tail>=4);
    }
    return component_count>0;
}

typedef struct { int boxes, loop, count; size_t stride; } ComponentType;
static ComponentType component_types[2*MAXB];
static int component_type_of[MAXB], component_type_count;

/* Compress identical chains/loops into counts. The product of (count+1)
   over component types is small for boards with at most 100 boxes. */
static int prepare_component_dp(size_t *full_state) {
    component_type_count=0;
    for(int i=0;i<component_count;i++) {
        int t=0;
        while(t<component_type_count &&
              (component_types[t].boxes!=components[i].boxes ||
               component_types[t].loop!=components[i].loop)) t++;
        if(t==component_type_count) {
            component_types[t].boxes=components[i].boxes;
            component_types[t].loop=components[i].loop;
            component_types[t].count=0;
            component_type_count++;
        }
        component_types[t].count++;
        component_type_of[i]=t;
    }

    size_t states=1;
    for(int t=0;t<component_type_count;t++) {
        component_types[t].stride=states;
        size_t radix=(size_t)component_types[t].count+1;
        if(states>2000000/radix) return 0;
        states*=radix;
    }
    if(states>component_memo_size) {
        int8_t *p=(int8_t*)realloc(component_memo,states*sizeof(int8_t));
        if(!p) return 0;
        component_memo=p;
        component_memo_size=states;
    }
    memset(component_memo,0x80,states*sizeof(int8_t));
    component_memo[0]=0;
    *full_state=0;
    for(int t=0;t<component_type_count;t++)
        *full_state+=(size_t)component_types[t].count*component_types[t].stride;
    return 1;
}

/* Current player opens one component. The opponent minimizes by taking all,
   or by handing over 2 boxes (chain) / 4 boxes (loop) and the move. */
static int component_state_value(size_t state) {
    if(state==0) return 0;
    int8_t *slot=&component_memo[state];
    if(*slot!=(int8_t)-128) return *slot;
    int best=-1000;
    for(int t=0;t<component_type_count;t++) {
        int count=(int)((state/component_types[t].stride)%
                        ((size_t)component_types[t].count+1));
        if(!count) continue;
        int rest=component_state_value(state-component_types[t].stride);
        int n=component_types[t].boxes;
        int h=component_types[t].loop?4:(n>=3?2:0);
        int outcome=-n-rest;
        if(h) {
            int handout=2*h-n+rest;
            if(handout<outcome) outcome=handout;
        }
        if(outcome>best) best=outcome;
    }
    *slot=(int8_t)best;
    return best;
}

static int component_position_value(void) {
    size_t full;
    if(!prepare_component_dp(&full)) return 0;
    return component_state_value(full);
}

static int choose_opening_edge(const Board *b) {
    if(!find_components(b)) return -1;
    int chosen=-1;
    size_t full=0;
    if(prepare_component_dp(&full)) {
        int best=-1000;
        for(int i=0;i<component_count;i++) {
            int t=component_type_of[i];
            int rest=component_state_value(full-component_types[t].stride);
            int n=components[i].boxes;
            int h=components[i].loop?4:(n>=3?2:0);
            int candidate=-n-rest;
            if(h) {
                int handout=2*h-n+rest;
                if(handout<candidate) candidate=handout;
            }
            if(candidate>best) {best=candidate;chosen=i;}
        }
    }
    if(chosen<0) {
        int shortest=1000;
        for(int i=0;i<component_count;i++) if(components[i].boxes<shortest) {
            shortest=components[i].boxes;
            chosen=i;
        }
    }
    if(chosen<0) return -1;
    memset(active_component_boxes,0,sizeof(active_component_boxes));
    active_component_loop=components[chosen].loop;
    for(int x=0;x<T.B;x++) if(component_of[x]==chosen)
        active_component_boxes[x]=1;
    /* In a chain, open an end of the path. Drawing a shared link in the
       middle gives the opponent two simultaneous captures and destroys the
       chain model used by the endgame DP. A loop has no external end, so any
       shared edge opens it. */
    for(int e=0;e<T.E;e++) if(!b->drawn[e]) {
        int inside=0;
        for(int k=0;k<edge_box_count[e];k++)
            if(component_of[edge_boxes[e][k]]==chosen) inside++;
        if(!components[chosen].loop && inside==1) return e;
        if(components[chosen].loop && inside==2) return e;
    }
    return -1;
}

static uint32_t rng_next(uint32_t *state) {
    uint32_t x=*state;
    if(!x) x=0x9e3779b9u;
    x^=x<<13; x^=x>>17; x^=x<<5;
    *state=x;
    return x;
}

static int count_twos(const Board *b) {
    int n=0;
    for(int x=0;x<T.B;x++) if(box_active[x] && b->sides[x]==2) n++;
    return n;
}

/* Score a safe move without rescanning the whole board. A safe move can only
   make boxes with one side become two-sided, which removes their other open
   edges from the set of safe replies. */
static int safe_move_score(const Board *b,int e,int twos,int safes) {
    int add_twos=0, lost_safe=0, removed[8], removed_n=0;
    for(int k=0;k<edge_box_count[e];k++) {
        int x=edge_boxes[e][k];
        if(!box_active[x] || b->sides[x]!=1) continue;
        add_twos++;
        for(int j=0;j<4;j++) {
            int f=box_edges[x][j], seen=0;
            if(f==e || b->drawn[f] || !is_safe(b,f)) continue;
            for(int z=0;z<removed_n;z++) if(removed[z]==f) {seen=1;break;}
            if(!seen && removed_n<8) {removed[removed_n++]=f;lost_safe++;}
        }
    }
    int next_safe=safes-lost_safe;
    return -600*(twos+add_twos)-15*next_safe+(int)(((uint32_t)e*2654435761u)&3u);
}

static int rollout_endgame_value(const Board *b) {
    if(!find_components(b)) return 0;
    return component_position_value();
}

static int active_remaining_boxes(const Board *b) {
    int n=0;
    for(int x=0;x<T.B;x++)
        if(active_component_boxes[x] && b->sides[x]<4) n++;
    return n;
}

static void remember_opened_component(const Board *b,int e) {
    if(!find_components(b)) return;
    int chosen=-1;
    for(int k=0;k<edge_box_count[e];k++) {
        int x=edge_boxes[e][k];
        if(component_of[x]>=0) { chosen=component_of[x]; break; }
    }
    if(chosen<0) return;
    memset(active_component_boxes,0,sizeof(active_component_boxes));
    active_component_loop=components[chosen].loop;
    for(int x=0;x<T.B;x++) if(component_of[x]==chosen)
        active_component_boxes[x]=1;
}

static int unopened_component_value(const Board *b) {
    Board q=*b;
    for(int x=0;x<T.B;x++) if(active_component_boxes[x]) q.sides[x]=4;
    if(!find_components(&q)) return 0;
    return component_position_value();
}

static int find_handout_edge(const Board *b) {
    for(int e=0;e<T.E;e++) if(!b->drawn[e] && edge_gain(b,e)==0) {
        int touches=0, only_active=1;
        for(int k=0;k<edge_box_count[e];k++) {
            int x=edge_boxes[e][k];
            if(b->sides[x]<4) {
                if(!active_component_boxes[x]) only_active=0;
                else touches=1;
            }
        }
        if(!touches || !only_active) continue;
        Board q=*b;
        apply_edge(&q,e);
        for(int f=0;f<T.E;f++) if(!q.drawn[f] && edge_gain(&q,f)>0)
            return e;
    }
    return -1;
}

/* During a long-chain/loop endgame, preserve the option to hand out the last
   2 boxes of a chain or 4 of a loop. The component DP decides whether control
   is worth keeping; this routine implements that decision on actual edges. */
static int choose_capture_edge(const Board *b) {
    int n=active_remaining_boxes(b);
    if(n==0) {
        memset(active_component_boxes,0,sizeof(active_component_boxes));
        active_component_loop=0;
    }
    if(n>0) {
        int h=active_component_loop?4:2;
        if(n==h) {
            int rest=unopened_component_value(b);
            int take_all=n+rest;
            int handout=n-2*h-rest;
            if(handout>take_all) {
                int e=find_handout_edge(b);
                if(e>=0) return e;
            }
        }
        int best=-1,best_gain=-1;
        for(int e=0;e<T.E;e++) if(!b->drawn[e]) {
            int g=edge_gain(b,e), active_gain=0;
            if(!g) continue;
            for(int k=0;k<edge_box_count[e];k++) {
                int x=edge_boxes[e][k];
                if(active_component_boxes[x] && b->sides[x]==3) active_gain++;
            }
            if(active_gain>best_gain) {best_gain=active_gain;best=e;}
        }
        if(best>=0) return best;
    }

    int best=-1,best_gain=-1;
    for(int e=0;e<T.E;e++) if(!b->drawn[e]) {
        int g=edge_gain(b,e);
        if(g>best_gain) {best_gain=g;best=e;}
    }
    return best;
}

static int rollout_safe_move(const Board *b,int twos,int safes,uint32_t *rng) {
    int best=-1,best_score=-1000000000;
    for(int e=0;e<T.E;e++) if(!b->drawn[e] && is_safe(b,e)) {
        int score=safe_move_score(b,e,twos,safes)+(int)(rng_next(rng)&7u);
        if(score>best_score) {best_score=score;best=e;}
    }
    return best;
}

static int safe_rollout(Board state,int root_to_move,uint32_t rng) {
    while(simulated_steps<SIM_BUDGET) {
        int safes=0;
        for(int e=0;e<T.E;e++) if(!state.drawn[e] && is_safe(&state,e)) safes++;
        if(!safes) {
            int v=rollout_endgame_value(&state);
            /* root_to_move means the side to move is the root player. */
            return root_to_move ? v : -v;
        }
        int e=rollout_safe_move(&state,count_twos(&state),safes,&rng);
        if(e<0) break;
        apply_edge(&state,e);
        root_to_move=!root_to_move;
        simulated_steps++;
    }
    return 0;
}

static int choose_safe_with_rollouts(const Board *b,int safes,int remaining) {
    int edges[MAXE], scores[MAXE], n=0, twos=count_twos(b);
    for(int e=0;e<T.E;e++) if(!b->drawn[e] && is_safe(b,e)) {
        edges[n]=e; scores[n]=safe_move_score(b,e,twos,safes); n++;
    }
    if(!n) return -1;

    uint32_t seed=0x91e10da5u ^ (uint32_t)(remaining*65537u+T.R*257u+T.C);
    for(int e=0;e<T.E;e++) if(b->drawn[e]) seed=(seed^(uint32_t)(e+1))*16777619u;
    int candidate[6], nc=0;
    for(int k=0;k<4 && k<n;k++) {
        int best=-1, best_score=-1000000000;
        for(int i=0;i<n;i++) {
            int used=0; for(int j=0;j<nc;j++) if(candidate[j]==edges[i]) used=1;
            if(!used && scores[i]>best_score) best_score=scores[i],best=i;
        }
        if(best>=0) candidate[nc++]=edges[best];
    }
    for(int k=0;k<2 && nc<n;k++) {
        int idx=(int)(rng_next(&seed)%(uint32_t)n), tries=0, used;
        do {
            used=0; for(int j=0;j<nc;j++) if(candidate[j]==edges[idx]) used=1;
            if(!used) break;
            idx=(idx+1)%n;
        } while(++tries<n);
        if(!used) candidate[nc++]=edges[idx];
    }

    int best_edge=candidate[0]; double best_value=-1e100;
    for(int i=0;i<nc;i++) {
        double total=0.0; int reps=0;
        for(int run=0;run<2;run++) {
            Board q=*b; apply_edge(&q,candidate[i]);
            if(simulated_steps+free_count(&q)>SIM_BUDGET) break;
            uint32_t rseed=seed ^ (uint32_t)(candidate[i]*2654435761u) ^ (uint32_t)(run*2246822519u);
            total+=safe_rollout(q,0,rseed); reps++;
        }
        if(reps) {
            double value=total/reps;
            if(value>best_value) {best_value=value;best_edge=candidate[i];}
        }
    }
    return best_edge;
}

static int choose_edge(const Board *b) {
    int remaining=free_count(b);
    if(remaining<=EXACT_LIMIT && remaining>0) return exact_choice(b);

    int best=-1; double best_score=-1e100;
    int any_capture=0;
    for(int e=0;e<T.E;e++) if(!b->drawn[e] && edge_gain(b,e)) any_capture=1;

    if(any_capture) {
        return choose_capture_edge(b);
    }

    int safe=0;
    for(int e=0;e<T.E;e++) if(!b->drawn[e] && is_safe(b,e)) safe++;
    if(safe) {
        int move=choose_safe_with_rollouts(b,safe,remaining);
        if(move>=0) return move;
    }

    int opening=choose_opening_edge(b);
    if(opening>=0) return opening;

    /* All moves open a box. Estimate the forced capture run each move gives
       the opponent; choose the smallest concession and favor positions where
       they have no safe reply after the run. */
    for(int e=0;e<T.E;e++) if(!b->drawn[e]) {
        Board q=*b; apply_edge(&q,e);
        int conceded=0;
        for(int step=0;step<T.B;step++) {
            int cap=-1, cg=0;
            for(int x=0;x<T.E;x++) if(!q.drawn[x]) {
                int g=edge_gain(&q,x);
                if(g>cg) {cg=g;cap=x;}
            }
            if(cap<0) break;
            conceded+=apply_edge(&q,cap);
        }
        int oppSafe=safe_count(&q);
        double score=-10000.0*conceded + (oppSafe==0 ? 250.0 : -2.0*oppSafe);
        score += (double)((e*1103515245u + remaining*12345u) & 1023u)*0.0001;
        if(score>best_score) {best_score=score;best=e;}
    }
    if(best<0) for(int e=0;e<T.E;e++) if(!b->drawn[e]) return e;
    return best;
}
static void print_edge(int e) {
    int r1,c1,r2,c2;
    if(e<T.hCount) {
        r1=e/T.C; c1=e%T.C; r2=r1; c2=c1+1;
    } else {
        int z=e-T.hCount; r1=z/(T.C+1); c1=z%(T.C+1); r2=r1+1; c2=c1;
    }
    printf("LINE %d %d %d %d\n",r1,c1,r2,c2);
    fflush(stdout);
}
int main(void) {
    char tag[64], row[64]; int R,C,first;
    if(scanf("%63s %d %d %d",tag,&R,&C,&first)!=4 || strcmp(tag,"GAME")!=0) return 0;
    if(R<1||R>MAXR||C<1||C>MAXC) return 0;
    build_topology(R,C);
    Board b; memset(&b,0,sizeof(b));
    for(int i=0;i<2*R+1;i++) {
        if(scanf("%63s",row)!=1) return 0;
        if((int)strlen(row)<2*C+1) return 0;
        if((i&1)==0) {
            int r=i/2;
            for(int c=0;c<C;c++) if(row[2*c+1]=='-') b.drawn[r*C+c]=1;
        } else {
            int r=i/2;
            for(int c=0;c<=C;c++) if(row[2*c]=='|') b.drawn[T.hCount+r*(C+1)+c]=1;
            for(int c=0;c<C;c++) if(row[2*c+1]=='#') box_active[r*C+c]=0;
        }
    }
    for(int e=0;e<T.E;e++) if(b.drawn[e]) {
        for(int k=0;k<edge_box_count[e];k++) {
            int x=edge_boxes[e][k]; if(box_active[x]) b.sides[x]++;
        }
    }

    while(scanf("%63s",tag)==1) {
        if(strcmp(tag,"YOUR_TURN")==0) {
            int e=choose_edge(&b);
            if(e<0) return 0;
            print_edge(e);
            apply_edge(&b,e);
        } else if(strcmp(tag,"OPPONENT")==0) {
            int r1,c1,r2,c2;
            if(scanf("%d %d %d %d",&r1,&c1,&r2,&c2)!=4) return 0;
            int e;
            if(r1==r2 && abs(c1-c2)==1) e=r1*T.C+(c1<c2?c1:c2);
            else if(c1==c2 && abs(r1-r2)==1) e=T.hCount+(r1<r2?r1:r2)*(T.C+1)+c1;
            else continue;
            if(edge_gain(&b,e)==0 && safe_count(&b)==0 &&
               active_remaining_boxes(&b)==0)
                remember_opened_component(&b,e);
            apply_edge(&b,e);
        } else if(strcmp(tag,"GAME_END")==0) {
            double points; scanf("%lf",&points); return 0;
        }
    }
    (void)first;
    return 0;
}
