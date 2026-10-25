// ns_driver.cpp - NeuroSim (DNN_NeuroSim_V1.4, Inference_pytorch/NeuroSIM) driven for ONE ReRAM macro of this design: 512 rows x 32 weight columns, 2T2R differential
// (a differential cell is two physical columns per weight bit => 64 physical columns), 45 nm, one read = g active rows. It calls NeuroSim's own SubArray model - the area,
// latency and energy printed are NeuroSim's, not ours; our inputs are the device and circuit constants of studies/crossbar (see run_neurosim.py).
//
// NOT part of this repository's build: NeuroSim is CC BY-NC 4.0 and is cloned and built outside the repository by run_neurosim.py; this file is linked against its objects
// (everything except main.cpp). Definition.h is NeuroSim's own "globals" header, meant to be included by exactly one translation unit - this one.
//
//   ns_driver <rows> <phys_cols> <g> <F_nm> <readPulse_ns> <Ron> <Roff> <Raccess> <numColMuxed> <levelOutput> [pLRS]
#include <cstdio>
#include <random>
#include <cmath>
#include <iostream>
#include <fstream>
#include <string>
#include <stdlib.h>
#include <vector>
#include <sstream>
#include <chrono>
#include <algorithm>
#include "constant.h"
#include "formula.h"
#include "Param.h"
#include "Tile.h"
#include "Chip.h"
#include "ProcessingUnit.h"
#include "SubArray.h"
#include "Definition.h"

using namespace std;

int main(int argc, char *argv[]) {
  if (argc < 11) {
    fprintf(stderr, "usage: ns_driver rows cols g F_nm pulse_ns Ron Roff Raccess colMuxed levelOutput [pLRS]\n");
    return 2;
  }
  gen.seed(0);
  int rows = atoi(argv[1]), cols = atoi(argv[2]), g = atoi(argv[3]);
  double F_nm = atof(argv[4]), pulse = atof(argv[5]) * 1e-9, Ron = atof(argv[6]), Roff = atof(argv[7]), Racc = atof(argv[8]);
  int mux = atoi(argv[9]), levels = atoi(argv[10]);
  double pLRS = argc > 11 ? atof(argv[11]) : 0.5;

  // the Param constructor (patched by run_neurosim.py: technode 45, RRAM, 1T1R CMOS access, HP roadmap, 1T1R cell width/height) has already run
  param->operationmode = 2;                  // conventional, parallel read of numRowParallel rows
  param->conventionalParallel = 1;
  param->conventionalSequential = 0;
  param->numRowSubArray = rows;
  param->numColSubArray = cols;
  param->numRowParallel = g;
  param->parallelRead = 1;
  param->numColMuxed = mux;
  param->levelOutput = levels;
  param->numBitInput = 1;
  param->cellBit = 1;
  param->numColPerSynapse = 1;
  param->resistanceOn = Ron;
  param->resistanceOff = Roff;
  param->maxConductance = 1.0 / Ron;
  param->minConductance = 1.0 / Roff;
  param->resistanceAccess = Racc;
  param->readVoltage = 0.1;                  // V_READ of studies/crossbar/device/constants.py
  param->accessVoltage = 1.1;                // V_WL
  param->readPulseWidth = pulse;
  param->featuresize = F_nm * 1e-9;          // cell geometry feature size (NeuroSim's own 45 nm node uses an 80 nm wire width / feature size; see the report)
  param->relaxArrayCellHeight = 0;
  param->relaxArrayCellWidth = 0;
  param->clkFreq = 1.0 / (pulse + 0.3e-9);

  SubArray *subArray = NULL;
  ProcessingUnitInitialize(subArray, inputParameter, tech, cell, 1, 1, 1, 1);
  subArray->CalculateArea();

  // one read: g active rows; every stored differential cell has exactly one LRS branch, so a physical column sees an LRS branch with probability pLRS = 0.5
  vector<double> input(rows, 0.0);
  for (int i = 0; i < g; i++) input[i] = 1.0;
  vector<vector<double> > weight(rows, vector<double>(cols, 1.0 / Roff));
  std::mt19937 rng(1);
  std::bernoulli_distribution lrs(pLRS);
  for (int i = 0; i < rows; i++)
    for (int j = 0; j < cols; j++) weight[i][j] = lrs(rng) ? 1.0 / Ron : 1.0 / Roff;
  subArray->activityRowRead = (double)g / rows;
  subArray->levelOutput = levels;
  vector<double> colRes = GetColumnResistance(input, weight, cell, 1, subArray->resCellAccess);
  subArray->CalculateLatency(1e20, colRes, false);
  subArray->CalculatePower(colRes);

  printf("rows %d phys_cols %d g %d F_nm %.1f cell_w_F %.1f cell_h_F %.1f\n", rows, cols, g, F_nm, cell.widthInFeatureSize, cell.heightInFeatureSize);
  printf("area_total_um2 %.3f\n", subArray->area * 1e12);
  printf("height_um %.3f width_um %.3f\n", subArray->height * 1e6, subArray->width * 1e6);
  printf("area_array_um2 %.3f\n", subArray->areaArray * 1e12);
  printf("area_ADC_um2 %.3f area_accum_um2 %.3f area_other_um2 %.3f\n", subArray->areaADC * 1e12, subArray->areaAccum * 1e12, subArray->areaOther * 1e12);
  printf("area_modules_um2 wlDecoder %.1f wlSwitchMatrix %.1f wlNewSwitchMatrix %.1f slSwitchMatrix %.1f mux %.1f muxDecoder %.1f precharger %.1f multilevelSenseAmp %.1f multilevelSAEncoder %.1f sarADC %.1f adder %.1f dff %.1f shiftAddInput %.1f shiftAddWeight %.1f\n",
         subArray->wlDecoder.area * 1e12, subArray->wlSwitchMatrix.area * 1e12, subArray->wlNewSwitchMatrix.area * 1e12, subArray->slSwitchMatrix.area * 1e12, subArray->mux.area * 1e12, subArray->muxDecoder.area * 1e12,
         subArray->precharger.area * 1e12, subArray->multilevelSenseAmp.area * 1e12, subArray->multilevelSAEncoder.area * 1e12, subArray->sarADC.area * 1e12, subArray->adder.area * 1e12,
         subArray->dff.area * 1e12, subArray->shiftAddInput.area * 1e12, subArray->shiftAddWeight.area * 1e12);
  printf("read_latency_ns %.4f (ADC %.4f accum %.4f other %.4f)\n", subArray->readLatency * 1e9, subArray->readLatencyADC * 1e9, subArray->readLatencyAccum * 1e9, subArray->readLatencyOther * 1e9);
  printf("read_energy_pJ %.4f (array %.4f ADC %.4f accum %.4f other %.4f)\n", subArray->readDynamicEnergy * 1e12, subArray->readDynamicEnergyArray * 1e12, subArray->readDynamicEnergyADC * 1e12,
         subArray->readDynamicEnergyAccum * 1e12, subArray->readDynamicEnergyOther * 1e12);
  printf("leakage_uW %.4f\n", subArray->leakage * 1e6);
  printf("cap_row_fF %.2f cap_col_fF %.2f res_row_ohm %.1f res_col_ohm %.1f\n", subArray->capRow1 * 1e15, subArray->capCol * 1e15, subArray->resRow, subArray->resCol);
  return 0;
}
