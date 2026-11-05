# Method-Centric Project Layout and Central FIGURES Design

**Date:** 2026-11-04
**Status:** Approved
**Scope:** Geodesy-1Preprocessing, Geodesy-2Analysis,
Geodesy-3Data_Adapter, Geodesy-4Visualization, and the
`Gansu_Jishishan_LT1` study project

## 1. Intent

The study-project filesystem shall be organized around the sensor, study case,
processing method, and scientific product rather than around source-repository
names such as `PRE`, `ANALYSIS`, and `VISUALIZATION`.

The layout must preserve the operational strengths of the original GAMMA shell
workflow:

- every CFG explains the directories consumed and produced by that step;
- preprocessing and analysis reuse valid existing results during batch runs;
- deleting a completed result is the normal way to request that result again;
- scientific products remain easy to locate by method and product type; and
- all quicklooks and publication figures can be browsed from one `FIGURES`
  hierarchy.

Repository ownership remains unchanged. Removing `PRE`, `ANALYSIS`, and
`VISUALIZATION` from the study-project path does not merge the four codebases or
their responsibilities.

## 2. Goals

1. Introduce one explicit processing-method root per case, for example:
   `SAOCOM/GUIZHOU/GAMMA_mb` or `S1/ASCENDING_128/GAMMA`.
2. Store preprocessing products directly below that method root as `SLC` and
   `RSLC`, with preprocessing geocoding below `RSLC/GEOCODING`.
3. Store interferometric geocoding separately at method-root `GEOCODING`.
4. Store scientific analysis products by product and method, without a generic
   `ANALYSIS` parent.
5. Store all generated images below one method-root `FIGURES` tree.
6. Keep interferogram phase, coherence, and intensity quicklooks adjacent in a
   flat `FIGURES/INTF` directory by using a shared pair-name prefix.
7. Expose every scientific output and figure directory in CFG while providing
   documented defaults derived from `processing_root`.
8. Retain completion-aware skip behavior for Preprocessing and Analysis.
9. Let Data Adapter and Visualization atomically replace their inexpensive
   generated outputs.
10. Migrate the real Gansu S1 and SAOCOM cases without deleting scientific data.

## 3. Non-goals

- This change does not introduce mandatory `run_id`, `main`, or `test`
  directories.
- This change does not encode filtering or unwrapping choices into the case name.
- This change does not combine repository source trees.
- This change does not redesign the numerical algorithms.
- This change does not require rerunning all existing S1 and SAOCOM products.
- This change does not make publication figures scientific processing outputs.

## 4. Anti-goals

The implementation must not:

- skip merely because a non-empty directory exists;
- silently reuse products whose recorded inputs or parameters differ;
- overwrite expensive Preprocessing or Analysis products automatically;
- scatter canonical quicklooks through pair directories;
- duplicate the same image in both a product directory and `FIGURES`;
- place preprocessing geocoding and interferometric geocoding in one directory;
- hard-code the Gansu absolute project path in reusable repository examples; or
- destructively move existing Gansu products without a recorded migration map.

## 5. Considered Approaches

### 5.1 Central FIGURES hierarchy — selected

All canonical BMP, PNG, JPG, SVG, and PDF outputs live below one `FIGURES`
directory. Scientific manifests record the associated figure paths.

This was selected because the primary operational requirement is convenient
photo-browser inspection across many pairs and processing methods. It also
prevents quicklooks from being mixed with binary scientific rasters.

### 5.2 Figures stored inside each result directory — rejected

This simplifies deleting a result and its figures together, but reproduces the
current browsing problem: users must enter many product, method, and pair
directories to compare results.

### 5.3 Distributed figures plus a symlink index — rejected

This offers centralized browsing without duplicate files, but symlinks become
fragile when projects are copied, mounted elsewhere, or archived. A generated
catalog may be added later, but it is not the canonical storage design.

## 6. Canonical Case and Method Roots

Each CFG case shall declare two distinct concepts:

```ini
project = SAOCOM/GUIZHOU
processing_root = SAOCOM/GUIZHOU/GAMMA_mb
```

- `project` is the two-component case identity.
- `processing_root` is the project-relative root of one processing method.
- Individual input and output paths remain visible and may override derived
  defaults.
- A repository must never infer `GAMMA`, `GAMMA_mb`, or another method name from
  the sensor name.
- `processing_root` must remain within the declared case root.

This permits another method to coexist without a mandatory run identifier:

```text
SAOCOM/GUIZHOU/GAMMA_mb/
SAOCOM/GUIZHOU/ISCE2/
```

## 7. Canonical Scientific Layout

```text
<SENSOR>/
├── DOWNLOAD/                              # raw/vendor data, outside case method root
└── <CASE>/
    └── <PROCESSING_METHOD>/
        ├── SLC/
        ├── RSLC/
        │   ├── GEOCODING/                # geometry used to form/register RSLC
        │   └── SUBSET/                   # optional registered-stack crop
        ├── BASELINE/
        ├── GEOCODING/                    # geometry used by interferometry/geocoding
        ├── INTF/
        │   ├── MLI/
        │   └── PAIRS/
        │       └── <master>-<slave>/     # phase, coherence and pair parameters together
        ├── FILTERING/
        │   └── <METHOD>/
        │       └── PAIRS/
        ├── UNW/
        │   └── <METHOD>/
        │       └── PAIRS/
        ├── DETRENDING/
        │   └── <METHOD>/
        │       └── PAIRS/
        ├── ATMOSPHERE/
        │   └── <METHOD>/
        ├── TIMESERIES/
        │   └── <METHOD>/
        ├── CANONICAL/                    # Data Adapter canonical datasets
        ├── EXPORT/                       # Defsour and other explicit exports
        ├── FIGURES/
        ├── LOG/
        ├── images                        # method-stack date inventory, when required
        └── pairs.txt                     # shared selected interferogram pairs
```

`COH` is not a separate top-level scientific directory. Coherence produced with
an interferogram belongs to the same `INTF/PAIRS/<pair>` scientific record.
Filtered coherence belongs to the selected `FILTERING/<METHOD>/PAIRS/<pair>`
record. This preserves pair provenance and avoids separating products generated
by one operation.

## 8. Central FIGURES Layout

```text
FIGURES/
├── PRE/
│   ├── SLC/
│   ├── RSLC/
│   ├── RSLC_SUBSET/
│   └── RSLC_GEOCODING/
├── BASELINE/
├── GEOCODING/
├── INTF/
├── FILTERING/
│   ├── NL_INSAR/
│   ├── GAMMA_BM3D/
│   └── GAMMA_ADF/
├── UNW/
│   └── GAMMA_MCF/
├── DETRENDING/
│   └── GAMMA_QUAD/
├── ATMOSPHERE/
│   └── <METHOD>/
├── TIMESERIES/
│   └── <METHOD>/
└── PUBLICATION/
    └── <WORKFLOW>/
```

### 8.1 Interferogram browsing convention

`FIGURES/INTF` remains flat. Pair products use identical pair prefixes so a
normal filename sort keeps related images adjacent:

```text
20231027.mli.bmp
20231226.mli.bmp
ave_mli.bmp
20231027-20231226.intensity.bmp
20231027-20231226.phase.bmp
20231027-20231226.coherence.bmp
```

No pair subdirectory is introduced below `FIGURES/INTF`.

### 8.2 Figure ownership

- Geodesy-1Preprocessing writes only `FIGURES/PRE/**`.
- Geodesy-2Analysis writes stage-local quality-control quicklooks below
  `FIGURES/BASELINE`, `FIGURES/GEOCODING`, `FIGURES/INTF`,
  `FIGURES/FILTERING`, `FIGURES/UNW`, `FIGURES/DETRENDING`,
  `FIGURES/ATMOSPHERE`, and `FIGURES/TIMESERIES`.
- Geodesy-4Visualization writes publication/cartographic products only below
  `FIGURES/PUBLICATION/<WORKFLOW>`.
- Data Adapter does not create presentation figures.

## 9. CFG Documentation Contract

Every processing-chain CFG example and every Gansu runtime CFG shall begin with
a concise path contract. The comments must use actual CFG keys rather than only
describing a conceptual directory.

Required headings are:

```ini
# STEP / 当前步骤
# CASE AND METHOD ROOT / 项目与方法根目录
# REQUIRED INPUTS / 必需输入
# OUTPUTS / 本步骤输出
# DOWNSTREAM USE / 后续用途
# REUSE / SKIP / 重用与跳过规则
```

Preprocessing CFGs list only acquisition and preprocessing dependencies and
outputs. They do not need to enumerate Analysis, Adapter, or Visualization
directories.

Analysis CFGs explicitly list every required upstream Preprocessing manifest or
product and identify which downstream Analysis step consumes their output.

Each case keeps explicit path entries such as:

```ini
processing_root = S1/ASCENDING_128/GAMMA
output_dir = S1/ASCENDING_128/GAMMA/INTF
figure_dir = S1/ASCENDING_128/GAMMA/FIGURES/INTF
```

If `output_dir` or `figure_dir` is omitted, the CLI dry-run must print the
derived path before execution.

## 10. Reuse and Skip Contract

### 10.1 Preprocessing and Analysis

Expensive processing retains completion-aware reuse.

A result may be skipped only when all of the following hold:

1. its completion manifest exists and declares `status = complete`;
2. every required product recorded by the manifest exists and passes its basic
   validation;
3. the current scientific input/config signature matches the manifest; and
4. the manifest schema and case/method identities match the selected CFG case.

Behavior by state:

- **complete and matching:** report `skipped` and continue the batch;
- **directory absent:** calculate and publish the result;
- **directory present but incomplete:** fail with a message identifying the
  directory that the user must inspect, move, or delete;
- **complete but signature differs:** fail and instruct the user to delete or
  choose another `output_dir`; never silently reuse or overwrite it.

The skip unit follows the smallest independently manifested expensive result:

- SLC generation: acquisition date/scene;
- stack registration and geocoding: complete stack/geometry manifest;
- interferogram, filtering, unwrapping, and detrending: pair product where the
  workflow supports pair-level manifests, plus a deterministic stage summary;
- baseline selection: complete network manifest.

Deleting the relevant completed output is the normal explicit request to run it
again.

### 10.2 Figures

Figures are derived products and do not decide whether scientific data are
complete. If science is valid but required quicklooks are absent, the workflow
regenerates only the missing figures when technically possible. It must not
rerun expensive GAMMA science solely because a BMP or PNG was deleted.

### 10.3 Data Adapter and Visualization

Geodesy-3Data_Adapter and Geodesy-4Visualization write into a sibling staging
path, validate the new artifact, and atomically replace an existing target.
They do not require the user to delete old outputs first.

## 11. Manifest and Path Rules

- Scientific manifests are stored beside their scientific product, not in
  `FIGURES`.
- Manifests record `processing_root`, scientific output paths, and figure paths.
- Project-internal paths are stored relative to the research-project root.
- Explicit external absolute paths remain absolute and are labeled as external.
- A scientific output, figure output, log directory, input directory, and
  staging directory must not overlap.
- Figure filenames are deterministic and must not depend on execution order.
- Path defaults are centralized in shared layout helpers rather than duplicated
  in each workflow loader.

## 12. Logs

Logs mirror products below the method root:

```text
LOG/
├── SLC/
├── RSLC/
├── BASELINE/
├── GEOCODING/
├── INTF/
├── FILTERING/<METHOD>/
├── UNW/<METHOD>/
├── DETRENDING/<METHOD>/
└── PUBLICATION/<WORKFLOW>/
```

Skipped items emit a concise skip reason. Failed attempts retain diagnostic
logs without replacing completed scientific products.

## 13. Gansu Migration

The migration covers both:

```text
S1/ASCENDING_128
S1/DESCENDING_135
SAOCOM/GUIZHOU
```

The migration shall:

1. generate a machine-readable old-to-new path map before moving anything;
2. reject collisions and missing source/manifest relationships;
3. use same-filesystem renames where possible;
4. never delete a scientific product as part of migration;
5. relocate quicklooks into the central `FIGURES` hierarchy;
6. update manifest paths and CFG paths consistently;
7. keep raw `DOWNLOAD` and acquisition query data outside method roots; and
8. retain a migration report sufficient to audit every moved directory.

Legacy `PRE`, `ANALYSIS`, and `VISUALIZATION` directories may be removed only
after they are empty and the migrated manifests validate. Compatibility
symlinks are not created by default.

## 14. Repository-Specific Work

### Geodesy-1Preprocessing

- Introduce shared `project` plus `processing_root` layout resolution.
- Replace canonical `PRE/GAMMA/**` enforcement with default derivation and
  explicit override validation.
- standardize completion-aware skipping and incomplete-output errors;
- move preprocessing quicklooks to `FIGURES/PRE/**`; and
- update all relevant CFG examples with the path documentation contract.

### Geodesy-2Analysis

- Derive method-centric defaults for baseline, geocoding, interferogram,
  filtering, MCF, and quad detrending;
- retain valid-result skipping instead of unconditional replacement;
- add figure-only repair for missing stage quicklooks;
- centralize path/manifest/skip helpers; and
- update all analysis CFG examples and Gansu cases.

### Geodesy-3Data_Adapter

- keep atomic overwrite as the default;
- align tests and bilingual documentation with that behavior; and
- default canonical/export products to `CANONICAL` and `EXPORT` when used in a
  method-centric project.

### Geodesy-4Visualization

- finish the `src/` package migration;
- package fonts, CPTs, and nested example CFGs correctly;
- resolve installed assets without assuming a source checkout;
- default publication output to `FIGURES/PUBLICATION/<WORKFLOW>`; and
- atomically replace previously generated figures.

## 15. Verification Strategy

Verification is intentionally focused rather than exhaustive:

1. unit tests for layout derivation, overlap rejection, skip classification,
   figure naming, and atomic replacement;
2. CFG loader checks for every modified example;
3. dry-run path parity for one S1 and one SAOCOM case;
4. migration-map validation without moving data first;
5. one representative existing-result skip and one deleted-result rerun per
   expensive workflow family; and
6. targeted Visualization output inspection after the package move.

The implementation must use the existing `envInSAR` environment for repository
tests and real-project checks unless a workflow explicitly belongs to another
already-established environment.
