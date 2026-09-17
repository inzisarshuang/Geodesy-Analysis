# Migration Provenance

- Source repository: `/mnt/beegfs/procesados/yiluntan/GAMMA-InSAR`
- Foundation source commit: `92434754ac7279643ded6c7740fa7d4bb242f455`
- F1 transfer source commit: `560ff7080fbb5cd03161170660183d933241c23e`
- Package inventory: `/mnt/beegfs/procesados/yiluntan/GAMMA-InSAR/2-GAMMA-POST/Toolbox_InSAR/geodesy_analysis`
- Foundation date: 2026-09-17
- Current state: `shadow`; package source transferred, wheel acceptance pending

## F1 transfer

- `baseline.py` and `filtering.py` retain their existing numerical behavior.
- `masking.py` uses Adapter 0.19.0 for explicit binary raster input and the
  Analysis-local atomic output boundary for mask publication.
- `timeseries.py` uses Adapter 0.19.0 for GAMMA parameters, real/complex binary
  rasters, grid shape, and lookup mapping. Interferogram-pair parsing and atomic
  CSV output are Analysis-owned.
- Production Analysis modules contain no `lib`, sibling checkout, or `sys.path`
  imports.

Promotion to `compatible` still requires a built and installed 0.1.0 wheel plus
the complete GAMMA compatibility suite after removal of the shadowing local
package. Promotion to `default` additionally requires a representative project
shadow run.
