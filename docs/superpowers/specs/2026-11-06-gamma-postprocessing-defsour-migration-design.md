# GAMMA Post-processing and Defsour Migration Design

**Date:** 2026-11-06

**Status:** Approved
**Scope:** `Geodesy-Analysis`, `Geodesy-DataAdapter`, and the
`Gansu_Jishishan_LT1` study project

## 1. Intent

Complete the currently missing part of the legacy GAMMA post-processing chain
without carrying forward its numeric directory flags, implicit path discovery,
or mixed scientific/export responsibilities.

The migration covers the scientific behavior currently implemented by:

- `8-3atm_mod_mask_ISBAS`;
- `8dinsar`;
- `8stacking`;
- `8sbas_mb_ISBAS`; and
- the GAMMA, MintPy, and LiCSBAS Defsour conversion entry points under the
  legacy `Toolbox_InSAR` tree.

The resulting processing chain is:

```text
DETRENDING/GAMMA_QUAD
    -> ATMOSPHERE/<METHOD>
    -> TIMESERIES/{DINSAR,STACKING,GAMMA_MB}
    -> DataAdapter/{CANONICAL,EXPORT/DEFSOUR}
    -> Visualization publication products
```

The term `TIMESERIES` is the common product-family root selected for all three
downstream deformation methods. `DINSAR` remains explicitly a single-pair
product inside that family rather than being presented as a multi-epoch
inversion.

## 2. Current State

`Geodesy-Analysis` currently has executable, manifest-driven stages for GAMMA
baseline selection, interferogram formation, filtering, MCF unwrapping, and
quadratic detrending. It has no atmosphere, DInSAR, stacking, or GAMMA `mb`
package and no corresponding command entry points.

`Geodesy-DataAdapter` already contains:

- bounded GAMMA, MintPy, and LiCSBAS source support;
- canonical HDF5 conversion;
- Defsour metadata and point-block contracts;
- validity-mask and grid-aggregation primitives;
- profile-aware reprojection primitives; and
- atomic Defsour writing.

It does not yet contain the complete source-to-Defsour orchestration, strict
CFG loaders, or CLI commands. Those user-facing workflows still live in the
legacy `Toolbox_InSAR` and import its sibling `lib` package.

The legacy post-processing scripts also disagree on their effective contract:

- filtering choices are encoded as `0`, `1`, and `2` and then converted into
  directory suffixes;
- DInSAR skips missing pairs, GAMMA `mb` aborts on a missing pair, and stacking
  writes an entry without validating that its input exists;
- DInSAR and GAMMA `mb` consume `*.atm.unw.fill`, while stacking searches for
  `*.atm.unw`;
- result directory names encode pair counts and filtering flags;
- scientific products, GAMMA quicklooks, KML, and GeoTIFF are mixed together;
  and
- the DInSAR script calls `dispmap` on an unwrapped pair but labels the result
  as mean velocity even though no temporal normalization is performed.

These inconsistencies are migration inputs to resolve, not behavior to preserve
silently.

## 3. Goals

1. Add manifest-driven atmosphere correction after GAMMA quadratic detrending.
2. Add independent DInSAR, stacking, and GAMMA `mb` workflows beneath one
   `TIMESERIES` family.
3. Make all upstream products explicit through manifests instead of filtering
   flags, suffixes, `find`, or working-directory conventions.
4. Preserve expensive-result skip behavior: reuse only complete, validated,
   signature-matching Analysis products.
5. Keep GAMMA scientific quicklooks synchronized with their processing stage
   under the central `FIGURES` hierarchy.
6. Move complete GAMMA/MintPy/LiCSBAS-to-Defsour workflows into
   `Geodesy-DataAdapter` without duplicating its existing low-level contracts.
7. Keep DataAdapter outputs deterministic, bounded-memory, validated, and
   atomically replaceable.
8. Update the real Gansu project CFG paths and directory entry points for the
   new stages without deleting or overwriting existing scientific data.
9. Retain the old scripts as rollback references until the user completes
   representative real-data testing and accepts the migrated results.

## 4. Non-goals

- Do not add MintPy or DS-InSAR scientific inversion to `Geodesy-Analysis` in
  this migration.
- Do not add mandatory `run_id`, `main`, or `test` directories.
- Do not combine the three time-series methods into one configuration file or
  one monolithic runner.
- Do not make publication/cartographic figures part of Analysis.
- Do not force a persistent canonical HDF5 intermediate before every Defsour
  export.
- Do not redesign the numerical algorithms beyond resolving demonstrably
  ambiguous or inconsistent legacy input/output semantics.
- Do not automatically migrate or delete legacy Gansu result directories.

## 5. Anti-goals

The implementation must not:

- infer an atmosphere, filtering, unwrapping, or detrending method from a
  directory suffix;
- scan arbitrary directories to guess scientific inputs;
- call a single-pair displacement product velocity without explicit temporal
  normalization;
- silently continue with an incomplete pair inventory;
- regard a BMP, PNG, KML, or GeoTIFF as proof that an Analysis result is
  scientifically complete;
- read an entire time-series cube into memory solely to export Defsour;
- silently infer CRS, units, LOS sign, byte order, nodata meaning, temporal
  reference, or spatial reference; or
- import runtime code from the legacy `GAMMA-InSAR` sibling source tree.

## 6. Considered Approaches

### 6.1 Stage-contract migration — selected

Each scientific stage receives a strict CFG, reads validated upstream
manifests, publishes a completion manifest, and derives method-centric defaults
from `processing_root`. Shared pair-table and GAMMA geometry preparation is
implemented once for downstream methods.

This approach fits the already migrated Analysis architecture, removes legacy
path ambiguity, preserves result reuse, and gives DataAdapter a stable product
boundary.

### 6.2 Direct one-for-one shell migration — rejected

Wrapping or translating each legacy script independently would be faster
initially, but it would retain incompatible missing-pair behavior, duplicated
table preparation, numeric filter flags, directory guessing, and mixed export
ownership.

### 6.3 One combined post-processing command — rejected

A single command with atmosphere, DInSAR, stacking, `mb`, quicklook, and export
cases would reduce the number of entry points but would create a large CFG with
many conditionally meaningful keys. It would also prevent the three scientific
methods from being rerun and manifested independently.

## 7. Repository and Configuration Layout

The Analysis repository stores examples directly by processing method, without
an extra `analysis/` layer:

```text
Geodesy-Analysis/
└── config/
    └── GAMMA_mb/
        ├── gamma_baseline.cfg
        ├── gamma_geocoding.cfg
        ├── gamma_interferogram.cfg
        ├── insar_filtering.cfg
        ├── gamma_mcf_unwrapping.cfg
        ├── gamma_quad_detrending.cfg
        ├── gamma_atmosphere.cfg
        ├── gamma_dinsar.cfg
        ├── gamma_stacking.cfg
        └── gamma_sbas_mb.cfg
```

The DataAdapter repository separates normalized data from explicit exchange
exports:

```text
Geodesy-DataAdapter/
└── config/
    ├── canonical/
    │   ├── gamma_to_canonical_h5.cfg
    │   ├── mintpy_to_canonical_h5.cfg
    │   ├── licsbas_to_canonical_h5.cfg
    │   └── inspect_h5.cfg
    └── data2defsour/
        ├── gamma_to_defsour.cfg
        ├── mintpy_to_defsour.cfg
        └── licsbas_to_defsour.cfg
```

The Gansu project uses the same categories directly below its root `config/`
and does not retain numeric stage prefixes. Repository example CFGs remain
portable; Gansu CFGs contain the real project paths.

Every CFG involved in this processing chain begins with the previously approved
path-contract headings and explicitly identifies its upstream manifests,
scientific output, figure output, log output, and downstream consumer.

## 8. Analysis Scientific Layout

Under one existing `<processing_root>`:

```text
<processing_root>/
├── DETRENDING/
│   └── GAMMA_QUAD/
├── ATMOSPHERE/
│   └── <METHOD>/
│       ├── PAIRS/
│       └── atmosphere_manifest.json
├── TIMESERIES/
│   ├── DINSAR/
│   │   └── timeseries_manifest.json
│   ├── STACKING/
│   │   └── timeseries_manifest.json
│   └── GAMMA_MB/
│       ├── DISPLACEMENT/
│       ├── DISPLACEMENT_GEO/
│       ├── INTERMEDIATE/
│       └── timeseries_manifest.json
├── CANONICAL/
├── EXPORT/
│   └── DEFSOUR/
├── FIGURES/
│   ├── ATMOSPHERE/<METHOD>/
│   └── TIMESERIES/{DINSAR,STACKING,GAMMA_MB}/
└── LOG/
    ├── ATMOSPHERE/<METHOD>/
    └── TIMESERIES/{DINSAR,STACKING,GAMMA_MB}/
```

No filtering or atmosphere method is repeated below a downstream method. That
lineage is recorded in the manifest. A user may override every output, figure,
and log directory explicitly in CFG; otherwise these defaults are derived from
`processing_root` and printed during dry-run.

## 9. Atmosphere Stage

### 9.1 Input contract

The stage reads:

- one complete schema-v2 GAMMA quadratic-detrending manifest;
- the linked filtering, unwrapping, interferogram, and registered-stack
  manifests required to validate lineage and grid identity;
- explicit atmosphere masks where the selected method requires them; and
- explicit GAMMA executable names or executable-directory configuration through
  the existing command-runner boundary.

The stage never accepts a filtering index or constructs an upstream path from a
method name.

### 9.2 Methods

The first migration supports the four behaviors in the legacy script with
descriptive method identities:

| CFG method | Output directory | Legacy behavior |
|---|---|---|
| `none` | `ATMOSPHERE/NONE` | no atmosphere model |
| `gamma_atm_mod_2d_auto` | `ATMOSPHERE/GAMMA_ATM_MOD_2D_AUTO` | DEM-correlated fit using an explicit automatic mask |
| `gamma_atm_mod_2d_polygon` | `ATMOSPHERE/GAMMA_ATM_MOD_2D_POLYGON` | outside-polygon correction plus protected inside region |
| `gamma_fspf_atm_mod_2d` | `ATMOSPHERE/GAMMA_FSPF_ATM_MOD_2D` | FSPF followed by DEM-correlated atmosphere removal |

`none` publishes the same downstream manifest contract but references the
detrended phase directly instead of duplicating every large phase raster.

The first polygon-method migration requires an explicit GAMMA `poly_file` whose
vertices use the format consumed by `poly_mask`. The protected region is the
polygon interior: the outside region is atmosphere-corrected, the original
detrended phase is retained inside, and the two complementary products are
merged. The runner validates that the polygon file is non-empty, records its
digest, and generates both mask conventions itself. Precomputed raster-mask
input may be added later under a separately specified contract. Interactive
polygon drawing is outside the batch runner.

### 9.3 Products and quicklooks

Each pair record contains, where applicable:

- corrected unwrapped phase;
- simulated atmosphere phase;
- GAMMA atmosphere parameter file;
- applied mask identity;
- method parameters;
- stage-local GAMMA quicklooks; and
- per-pair command log.

The manifest records a complete pair inventory and the digest of every upstream
manifest. Pair outputs are published only after command success and basic byte
size/finite-value validation. Missing quicklooks may be repaired without
rerunning atmosphere estimation.

## 10. Shared Downstream Preparation

DInSAR, stacking, and GAMMA `mb` share a read-only preparation layer that:

1. reads one complete atmosphere manifest;
2. verifies case, processing root, grid, pair inventory, and upstream digests;
3. reads temporal baselines from the baseline/interferogram lineage rather than
   assuming a fourth column in an arbitrary text file;
4. produces deterministic GAMMA `diff_tab`, image tables, and pair-index tables
   inside the selected output staging directory; and
5. resolves registered MLI and interferometric geocoding assets without copying
   or discovering them by wildcard.

Every selected pair must exist and validate. Partial-network execution is only
allowed through an explicit selected-pair file whose resulting identity is
recorded in the output manifest; a missing selected input is always an error.

## 11. DInSAR Contract

The first migrated DInSAR workflow requires exactly one explicit pair. This
matches the actual numerical operation of the legacy script and prevents a
multi-line `diff_tab` from being passed accidentally as positional arguments to
`dispmap`.

The direct `dispmap` result is named and manifested as cumulative LOS
displacement for that pair. It is not called mean velocity. Rate normalization
is deferred until a separate, explicit scientific option is designed and
validated.

The workflow publishes:

- radar-coordinate LOS displacement;
- geocoded LOS displacement and required GAMMA parameter metadata;
- GAMMA radar/geocoded quicklooks; and
- `timeseries_manifest.json` with `method = gamma_dinsar` and the selected pair.

## 12. Stacking Contract

The stacking workflow consumes a validated selected pair network and executes
the GAMMA `stacking` and `dispmap` sequence. Reference-window size and location
are explicit CFG parameters rather than fixed `15 x 15` values hidden in code.

It publishes:

- mean phase rate;
- phase-rate uncertainty products produced by GAMMA;
- mean LOS velocity in radar and geocoded coordinates;
- stage-local quicklooks; and
- a complete manifest with pair network, temporal baselines, grid, units,
  reference window, command parameters, and upstream digests.

## 13. GAMMA `mb` Contract

The GAMMA `mb` workflow keeps the established numerical sequence:

```text
mb -> tpf_2d -> ts_rate -> dispmap
   -> optional displacement-map generation
   -> optional geocoding of all epochs
```

The following become ordinary CFG settings rather than environment-only flags:

- `mb_mode`;
- reference-window location and size;
- `gamma` smoothing value;
- `dtmax`;
- generation of mean geocoded products;
- generation of per-epoch displacement rasters;
- generation of geocoded per-epoch displacement rasters;
- quicklook limits and colormap; and
- explicit `visdt_pwr` executable when required by the installed GAMMA version.

Executable lookup follows existing command-runner rules and never hard-codes a
specific `/opt/GAMMA_*` or home-directory path.

Large `TS_*.diff` and `TS_tpf_*.tpf` files are placed directly in a declared
`INTERMEDIATE` directory rather than generated in the result root and moved at
the end. Final cumulative-displacement products and mean velocity remain
separate and are described with explicit units and quantities.

## 14. Analysis Reuse, Publication, and Failure Rules

Analysis follows the approved expensive-product contract:

- complete manifest, matching signature, and valid products: skip;
- absent output: run through a sibling staging directory and publish;
- existing incomplete output: fail and tell the user which directory to inspect
  or delete;
- complete output with a different signature: fail and require deletion or an
  explicitly different `output_dir`; and
- missing quicklook only: regenerate the quicklook when possible without
  rerunning the scientific command.

Signatures include the selected method, all scientific parameters, selected
pair inventory, executable command contract, grid identity, upstream manifest
digests, and explicit auxiliary masks.

## 15. Analysis and DataAdapter Ownership Boundary

Analysis owns:

- GAMMA scientific commands;
- GAMMA binary scientific results and parameter files;
- pair/network/time-series manifests;
- geocoding required to define the Analysis scientific result; and
- GAMMA-native stage quicklooks used for quality control.

DataAdapter owns:

- persistent canonical HDF5;
- explicit unit/reference/CRS transformations;
- GeoTIFF and Defsour exchange output;
- bounded source reading and reprojection for export; and
- atomic replacement of inexpensive generated exports.

Visualization owns only publication/cartographic rendering. KML and persistent
GeoTIFF are not part of the Analysis completion signature. If retained as an
export option, they are produced through DataAdapter, not used to determine
whether DInSAR, stacking, or GAMMA `mb` is complete.

## 16. Defsour Workflow Design

### 16.1 User-facing commands

`Geodesy-DataAdapter` adds three strict commands:

```text
insar-adapter export-gamma-defsour
insar-adapter export-mintpy-defsour
insar-adapter export-licsbas-defsour
```

Each requires `--config`. The CLI loads source-specific configuration and then
calls source readers, source-neutral transforms, and the existing Defsour
exporter. No workflow imports the legacy Toolbox.

The GAMMA command remains a generic adapter workflow whose required inputs are
explicit tab, raster, parameter, DEM, mask, date, and metadata settings. It does
not require an Analysis manifest and therefore remains usable with externally
produced GAMMA results. An optional `source_manifest` may point to an Analysis
`timeseries_manifest.json`; when supplied, its completion state, product paths,
dates, grid, units, and digest are validated and recorded as provenance. Explicit
CFG scientific metadata must agree with the manifest rather than being silently
filled from it.

### 16.2 Direct export and canonical interoperability

Direct source-to-Defsour remains supported because the legacy GAMMA workflow
needs explicit grid alignment, masks, reprojection, and downsampling that are
not removed merely by writing canonical HDF5. A persistent canonical HDF5 file
is therefore optional rather than mandatory.

Source-specific code ends at a validated stream/grid boundary. Temporal
referencing, validity composition, factor selection, grid aggregation,
reprojection, template alignment, metadata construction, and Defsour writing
are reusable workflow components shared wherever their source semantics permit.

### 16.3 Preserved capabilities

The migration preserves:

- date selection and unique output naming;
- temporal reference modes `preserve`, `first`, and explicit date;
- explicit deformation scaling with a correspondingly explicit output unit;
- masks and finite nodata sentinels;
- factor, target-point, and target-pixel-size downsampling;
- mean or median window aggregation;
- explicit target CRS;
- GAMMA native and aligned-grid modes;
- reusable alignment templates for multiple tracks;
- optional native/downsampled GeoTIFF products where supported; and
- a machine-readable export manifest plus a human-readable metadata summary.

All cube-like input is processed by epoch and bounded row/window blocks. Output
files are written beneath one sibling staging directory and validated as a
complete epoch set. The entire export directory is then published as one
transactional snapshot. A failed run leaves the previously complete export set
unchanged; it must never expose a mixture of old and new Defsour, GeoTIFF,
manifest, template, or metadata-summary files. The final export manifest is the
completion marker for the snapshot.

### 16.4 Metadata rules

Every export requires explicit:

- source and output CRS;
- deformation and height units;
- deformation quantity;
- LOS sign convention;
- nodata and zero policy;
- temporal and spatial reference;
- source provenance; and
- every scale, aggregation, resampling, and reprojection action.

The adapter never derives these fields merely from a filename or source family.

## 17. Gansu Project Integration

The implementation adds project CFGs for the existing Gansu S1/SAOCOM cases
whose migrated upstream manifests are available. The code task prepares and
validates those CFGs but does not execute the new atmosphere or time-series
scientific commands on the user's real data. The user performs the first real
Gansu runs and scientific acceptance after code delivery.

Project integration must:

1. leave existing legacy `PRODUCT`, `RESULT_*`, and figure directories intact;
2. write new products only under the agreed method-centric roots;
3. use explicit absolute or project-root-relative paths in project CFGs;
4. record any legacy-to-new comparison mapping without moving legacy data;
5. expose atmosphere, three time-series outputs, figure directories, logs,
   canonical output, and Defsour export directories for manual override; and
6. avoid committing large scientific products or private raw data;
7. include concise run commands and expected output/manifest locations for the
   user's real-data test; and
8. retain all legacy results so the user can compare them after running the new
   code.

## 18. Implementation Sequence

The migration is divided into dependency-ordered increments:

1. complete the approved repository/project config-directory cleanup relevant
   to Analysis and DataAdapter;
2. add the atmosphere manifest, CFG, planner, runner, publication, and focused
   tests;
3. add shared downstream pair/network/geometry preparation;
4. add stacking;
5. add single-pair DInSAR with corrected displacement semantics;
6. add GAMMA `mb` time-series processing;
7. add GAMMA-to-Defsour orchestration;
8. add MintPy-to-Defsour orchestration;
9. add LiCSBAS-to-Defsour orchestration;
10. add/update bilingual documentation and Gansu runtime CFGs; and
11. hand off real-project commands and comparison guidance to the user; retire
    no legacy entry point until the user reports an accepted real-data result.

Each increment remains separately reviewable and does not require waiting for
all later methods before its contract and tests are stable.

## 19. Focused Verification

Verification is proportional and uses the existing `envInSAR` environment:

1. strict CFG-loader tests for required, conditional, duplicate, and unknown
   keys;
2. plan tests for path derivation, manifest lineage, grid identity, pair
   inventory, and overlap rejection;
3. command-contract tests with a fake GAMMA executable for every migrated
   scientific method;
4. skip/incomplete/signature-mismatch/quicklook-repair tests;
5. synthetic bounded-memory Defsour workflow tests for GAMMA, MintPy, and
   LiCSBAS;
6. one small numerical fixture per atmosphere/time-series/Defsour method where
   behavior can be compared without a full external run;
7. path-only/CFG validation of the real Gansu configurations without executing
   external scientific processing;
8. `git diff --check` plus the focused test files touched by each increment; and
9. a handoff checklist for the user's later real-data runs and comparisons.

The implementation does not run unrelated repository-wide environment or
dependency experiments. Passing synthetic and fake-command tests proves the
software and command contract, not scientific parity on the user's real data;
that final acceptance remains explicitly pending until the user runs the
delivered configurations.

For the user's later shadow run using the same GAMMA installation and identical
scientific inputs, command arguments and output dimensions must match the legacy
workflow.
Float scientific rasters must have the same finite/nodata mask and be equal
within `rtol = 1e-6` and `atol = 1e-6` in their declared units; deterministic
integer masks and pair/date inventories must match exactly. Defsour comparison
uses identical point order and coordinates plus deformation/elevation tolerance
equal to half one unit of the configured last printed decimal. Quicklooks are
inspected for existence and dimensions but are not numerical parity evidence.
Any justified exception must be recorded in the shadow-run report and approved
before the corresponding legacy entry point is retired.

## 20. Builder Decisions Left Open

The builder may choose internal dataclass names, helper-file boundaries, JSON
field ordering, and small implementation details that do not alter the public
CFG, manifest lineage, scientific semantics, directory layout, ownership
boundary, or reuse behavior defined above.
