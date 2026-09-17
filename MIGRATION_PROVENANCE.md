# Migration Provenance

- Source repository: `/mnt/beegfs/procesados/yiluntan/GAMMA-InSAR`
- Foundation source commit: `92434754ac7279643ded6c7740fa7d4bb242f455`
- F1 transfer source commit: `560ff7080fbb5cd03161170660183d933241c23e`
- Adapter boundary commit: `a10ec3c`
- GAMMA installed-package transition commit: `a6e0186634b0947c777758e4b71532e1157c36cf`
- F2 shadow-validation tool commit: `0850c17`
- Package inventory: `/mnt/beegfs/procesados/yiluntan/GAMMA-InSAR/2-GAMMA-POST/Toolbox_InSAR/geodesy_analysis`
- Foundation date: 2026-09-17
- Current state: `default`; installed wheel and Tenerife 060 representative
  project shadow comparison accepted

## F1 transfer

- `baseline.py` and `filtering.py` retain their existing numerical behavior.
- `masking.py` uses Adapter 0.19.0 for explicit binary raster input and the
  Analysis-local atomic output boundary for mask publication.
- `timeseries.py` uses Adapter 0.19.0 for GAMMA parameters, real/complex binary
  rasters, grid shape, and lookup mapping. Interferogram-pair parsing and atomic
  CSV output are Analysis-owned.
- Production Analysis modules contain no `lib`, sibling checkout, or `sys.path`
  imports.

The Analysis 0.1.0 wheel
(`sha256:2dae0f619bdcfde49291195b3ff6784e863407af96504d2ffa92abea01040f43`)
and Adapter 0.19.0 wheel
(`sha256:ba076687283e63896810b208a0115ef3ff22158b1d315cb0168c6d290bc4c9af`)
were installed in `envInSAR`. Analysis 19, Adapter 71, and GAMMA 59 tests passed,
including checks that imports resolve from `site-packages` and compatibility
exports are object-identical. The representative project gate for `default`
completed on 2026-09-17 with exact baseline, filtering, masking, and time-series
result fingerprints. The project-local evidence is under
`Tenerife/Ascending/LOG/migrations/F2-analysis/` and the three executions are
recorded under `Tenerife/Ascending/LOG/ANALYSIS/ANALYSIS_F2_SHADOW_*`. The final
comparison report SHA-256 is
`daac38535fce5de15f686865d1089767f8b26328f76487f64587c0985cf78e48`.
