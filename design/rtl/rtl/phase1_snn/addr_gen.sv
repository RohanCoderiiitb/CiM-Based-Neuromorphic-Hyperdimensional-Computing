// addr_gen.sv - block A. Combinational: AER word -> crossbar row address, NeuroHDC eq.19.
//   addr = p*256 + min(floor(16 y / H), 15)*16 + min(floor(16 x / W), 15)
// Two sensor geometries are supported, selected by `geom_dvs_i` (the configuration's AER field width):
//   128x128 (DVS-Gesture)  word = p<<14 | y<<7 | x   cell = field >> 3                              : pure wiring, no gate on the event path
//   34x34   (N-MNIST)      word = p<<12 | y<<6 | x   cell = min(floor(field * 482 / 1024), 15)      : a constant table (exhaustively == floor(16 c / 34), clamped as events_to_frames clamps)
// LOW ACTIVITY: the table inputs are forced to zero in the 128x128 geometry, so a DVS event toggles nothing but the nine wires of its address (the table used to toggle on every event and
// its result was then discarded). A third geometry needs one more decode here; snn_top asserts that the configuration is one of the two.
import cim_neurohdc_pkg::AER_SHIFT_DVS;
import cim_neurohdc_pkg::AER_SHIFT_NMNIST;
import cim_neurohdc_pkg::COORD_SHIFT;
import cim_neurohdc_pkg::GRID_DIM;
import cim_neurohdc_pkg::GEO2_W;
import cim_neurohdc_pkg::GEO2_H;
import cim_neurohdc_pkg::W_ADDR;
import cim_neurohdc_pkg::W_AER;
import cim_neurohdc_pkg::W_GRID;

module addr_gen (
    input  logic [ W_AER-1:0] aer_i,
    input  logic              geom_dvs_i,   // 1: 128x128 fields of AER_SHIFT_DVS bits, 0: 34x34 fields of AER_SHIFT_NMNIST bits
    output logic [W_ADDR-1:0] addr_o
);
  localparam int SD = AER_SHIFT_DVS;
  localparam int SN = AER_SHIFT_NMNIST;
  localparam int N_C = 1 << SN;
  function automatic logic [N_C*W_GRID-1:0] mk_rom34();
    logic [N_C*W_GRID-1:0] r;
    int v;
    for (int i = 0; i < N_C; i++) begin
      v = (i * 482) >> COORD_SHIFT;
      if (v > GRID_DIM - 1) v = GRID_DIM - 1;
      r[i*W_GRID+:W_GRID] = W_GRID'(v);
    end
    mk_rom34 = r;
  endfunction
  // a second geometry other than 34 x 34 (the large chip: 240 x 180, 8-bit fields): separate x and y tables, floor(16 c / D) clamped as events_to_frames clamps
  function automatic logic [N_C*W_GRID-1:0] mk_rom(input int d);
    logic [N_C*W_GRID-1:0] r;
    int c;
    for (int i = 0; i < N_C; i++) begin
      c = (i < d) ? i : d - 1;
      r[i*W_GRID+:W_GRID] = W_GRID'((c * GRID_DIM) / d);
    end
    mk_rom = r;
  endfunction
  localparam bit G34 = (GEO2_W == 34) && (GEO2_H == 34);
  localparam logic [N_C*W_GRID-1:0] ROMX = G34 ? mk_rom34() : mk_rom(GEO2_W);
  localparam logic [N_C*W_GRID-1:0] ROMY = G34 ? mk_rom34() : mk_rom(GEO2_H);

  logic [SN-1:0] xn, yn;  // the 34x34 fields, isolated
  logic [W_GRID-1:0] col, row;
  logic p;
  assign xn  = geom_dvs_i ? '0 : aer_i[SN-1:0];
  assign yn  = geom_dvs_i ? '0 : aer_i[2*SN-1:SN];
  assign col = geom_dvs_i ? aer_i[SD-1-:W_GRID] : ROMX[int'(xn)*W_GRID+:W_GRID];      // field >> 3 = the top W_GRID bits of the 7-bit field
  assign row = geom_dvs_i ? aer_i[2*SD-1-:W_GRID] : ROMY[int'(yn)*W_GRID+:W_GRID];
  assign p   = geom_dvs_i ? aer_i[2*SD] : aer_i[2*SN];
  assign addr_o = {p, row, col};
endmodule
