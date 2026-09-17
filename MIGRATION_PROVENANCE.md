# Migration Provenance

- Source repository: `/mnt/beegfs/procesados/yiluntan/GAMMA-InSAR`
- Source commit: `92434754ac7279643ded6c7740fa7d4bb242f455`
- Package inventory: `/mnt/beegfs/procesados/yiluntan/GAMMA-InSAR/2-GAMMA-POST/Toolbox_InSAR/geodesy_analysis`
- Foundation date: 2026-09-17
- Foundation state: `inventory`; no scientific implementation copied

## Confirmed standalone blockers

- `geodesy_analysis/insar/masking.py` imports `atomic_output_path` and
  `read_binary_raster` from the legacy sibling `lib.toolbox_io` module.
- `geodesy_analysis/insar/timeseries.py` imports raster geometry helpers from
  `lib.toolbox_geo` and binary/file helpers from `lib.toolbox_io`.

F1 must move these capabilities behind installed package interfaces before the
Analysis package can be physically transferred without sibling-source imports.
