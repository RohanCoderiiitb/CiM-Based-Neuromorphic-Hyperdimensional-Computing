// top2_tree.sv - leader (value + lowest index) and SECOND-LARGEST VALUE of N unsigned scores by a binary tournament of pairwise merges. No sort.
//   merge(l, r):  l.v >= r.v ? { l.v, l.i, max(l.v2, r.v) } : { r.v, r.i, max(r.v2, l.v) }       (left holds the lower indices, so a tie keeps the lower index)
// Two classes tied for the lead give second == leader (margin 0). The leaf's "second" is 0: scores are >= 0, so this phantom entry never exceeds a real one (N >= 2).
// Depth ceil(log2 N) comparator levels. Reference: design/reference_model/model/fixedpoint/hdc_query.py top2_tournament.
module top2_tree #(
    parameter int N = 10,
    parameter int W = 11,
    parameter int WI = 5,
    parameter int BASE = 0  // index of the first element of this subtree
) (
    input  logic [N*W-1:0] scores_i,
    output logic [  W-1:0] v1_o,
    output logic [ WI-1:0] i1_o,
    output logic [  W-1:0] v2_o
);
  if (N == 1) begin : g_leaf
    assign v1_o = scores_i;
    assign i1_o = WI'(BASE);
    assign v2_o = '0;
  end else begin : g_split
    localparam int H = N / 2;
    logic [W-1:0] lv1, lv2, rv1, rv2;
    logic [WI-1:0] li, ri;
    top2_tree #(
        .N   (H),
        .W   (W),
        .WI  (WI),
        .BASE(BASE)
    ) u_l (
        .scores_i(scores_i[H*W-1:0]),
        .v1_o    (lv1),
        .i1_o    (li),
        .v2_o    (lv2)
    );
    top2_tree #(
        .N   (N - H),
        .W   (W),
        .WI  (WI),
        .BASE(BASE + H)
    ) u_r (
        .scores_i(scores_i[N*W-1:H*W]),
        .v1_o    (rv1),
        .i1_o    (ri),
        .v2_o    (rv2)
    );
    logic left_wins;
    assign left_wins = (lv1 >= rv1);
    assign v1_o = left_wins ? lv1 : rv1;
    assign i1_o = left_wins ? li : ri;
    assign v2_o = left_wins ? ((lv2 >= rv1) ? lv2 : rv1) : ((rv2 >= lv1) ? rv2 : lv1);
  end
endmodule
