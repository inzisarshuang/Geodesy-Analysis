# Project-Driven Study Layout Design

**Date:** 2026-10-14

**Status:** proposed for user review

**Scope:** shared project contract for Geodesy-Workflow, Geodesy-Preprocessing,
Geodesy-Analysis, and Geodesy-Visualization

## 1. Purpose

Organize a research project around independently runnable processing cases,
instead of repeating orbit direction and track beneath every processing stage.
Shared acquisitions and topography remain stored once, while each case owns all
derived preprocessing, analysis, visualization, configuration, and log outputs.

The design resolves the current Jishishan layout problems:

- `ascending` and `descending` are repeated below `WORK`, `ANALYSIS`, logs, and
  visualization;
- `WORK` does not say which repository owns an output;
- S1 and SAOCOM DEMs are stored inside sensor work areas and both GAMMA DEMs are
  misleadingly named `srtm.dem` although the source is COP30;
- one topography directory cannot distinguish multiple regions, sources, or
  coverage variants;
- Analysis still contains an obsolete figure directory and an empty
  `quicklooks/` concept;
- several manifests contain absolute cross-stage paths, which makes a case
  difficult to move or archive.

Success means a user selects a case once, every derived output is found below
that case, shared source data is not duplicated, and every cross-stage input is
selected by an explicit manifest rather than by scanning directories.

## 2. Ownership Boundaries

The repositories retain distinct responsibilities:

- **Geodesy-Workflow** owns the cross-repository project/case path contract,
  validation, migration orchestration, run records, and provenance policy.
- **Geodesy-Preprocessing** owns acquisition manifests, topography acquisition
  and conversion manifests, SLC generation, geometry, registration, and final
  RSLC subsetting.
- **Geodesy-Analysis** owns numerical products after preprocessing: baseline
  networks, interferograms, filtering, unwrapping, and later time-series work.
- **Geodesy-Visualization** owns rendered figures and never writes scientific
  Analysis products.
- **Geodesy-Data-Adapter** remains responsible for format contracts and data
  conversion. It does not run baseline, interferogram, filtering, unwrapping,
  project migration, or visualization workflows.

Repository names map directly to case directories:

| Repository | Case directory |
|---|---|
| Geodesy-Preprocessing | `PRE/` |
| Geodesy-Analysis | `ANALYSIS/` |
| Geodesy-Visualization | `VISUALIZATION/` |
| Geodesy-Workflow | `LOG/` plus contract and migration records |

The generic names `WORK` and `FIGURES` are not used in the target layout.

## 3. Project, Sensor Archive, and Case Model

The research project root contains three different kinds of content:

1. project-wide topography datasets;
2. sensor-specific query/download or raw-product archives;
3. independently runnable processing cases.

For the current project, the target structure is:

```text
Gansu_Jishishan_LT1/
├── config/
│   └── topography/
│       ├── jishishan_cop30.cfg
│       └── guizhou_cop30.cfg
│
├── TOPOGRAPHY/
│   ├── catalog.json
│   ├── jishishan_cop30/
│   │   ├── SOURCE/
│   │   │   ├── jishishan_cop30.tif
│   │   │   └── download_manifest.json
│   │   ├── GAMMA/
│   │   │   ├── jishishan_cop30.dem
│   │   │   ├── jishishan_cop30.dem.par
│   │   │   └── conversion_manifest.json
│   │   └── topography_manifest.json
│   └── guizhou_cop30/
│       ├── SOURCE/
│       ├── GAMMA/
│       └── topography_manifest.json
│
├── S1/
│   ├── config/
│   │   └── acquisition/
│   ├── QUERY/
│   │   ├── ascending/
│   │   └── descending/
│   ├── DOWNLOAD/
│   │   ├── ascending/Orbit_128/
│   │   └── descending/Orbit_135/
│   ├── ASCENDING_128/
│   │   └── <case layout>
│   └── DESCENDING_135/
│       └── <case layout>
│
└── SAOCOM/
    ├── RAW/
    │   └── guizhou/
    └── GUIZHOU/
        └── <case layout>
```

`S1/ASCENDING_128` and `S1/DESCENDING_135` are formal case paths. The sensor
name is not repeated in their final directory component. `SAOCOM/GUIZHOU` is
the current descriptive case path because the available manifest has no track
identifier; a track may be added as a manifest field later without parsing or
renaming the directory.

Directory names help people navigate, but code does not derive scientific
metadata from them. Sensor, orbit direction, relative orbit, track, frame,
polarizations, dates, and source products are read from explicit manifest
fields. The program verifies the manifest's `case_id` against the configured
case path, but never splits `ASCENDING_128` to guess values.

## 4. Canonical Case Layout

Each processing case has one stable root:

```text
S1/ASCENDING_128/
├── config/
│   ├── preprocessing/
│   ├── analysis/
│   └── visualization/
│
├── PRE/
│   ├── acquisition_manifest.json
│   └── GAMMA/
│       ├── SLC/
│       ├── GEOMETRY/
│       ├── RSLC/
│       └── RSLC_SUBSET/
│
├── ANALYSIS/
│   └── GAMMA/
│       ├── BASELINE/
│       ├── INTERFEROGRAM/
│       │   ├── MLI/
│       │   └── PAIRS/
│       ├── FILTERING/
│       │   └── PAIRS/
│       └── UNWRAPPING/
│           └── PAIRS/
│
├── VISUALIZATION/
│   └── GAMMA/
│       ├── BASELINE/
│       ├── INTF/
│       ├── COHERENCE/
│       └── UNW/
│
└── LOG/
    ├── PRE/GAMMA/
    ├── ANALYSIS/GAMMA/
    └── VISUALIZATION/GAMMA/
```

The case root already identifies the orbit/track selection, so no later path
adds another `ascending`, `descending`, `128`, or `135` component.

`RSLC` contains the full registered stack. `RSLC_SUBSET` is the canonical
handoff to Analysis after ROI subsetting. If a user chooses a full-frame run,
the subsetting workflow still publishes `RSLC_SUBSET` and records that the
window covers the full frame. Analysis therefore has one stable input contract.

## 5. Shared Acquisition Handoff

Query and downloaded/raw products are stored once in the sensor archive. A
case does not copy SAFE directories or other large source products. Instead,
case creation writes `PRE/acquisition_manifest.json` with at least:

```json
{
  "schema_version": 1,
  "status": "complete",
  "case_id": "S1/ASCENDING_128",
  "sensor": "sentinel1",
  "orbit_direction": "ascending",
  "relative_orbit": 128,
  "polarizations": ["VV"],
  "source_manifest": "S1/DOWNLOAD/ascending/source_manifest.json",
  "products": [
    {
      "date": "20231226",
      "paths": [
        "S1/DOWNLOAD/ascending/Orbit_128/<product>.SAFE"
      ]
    }
  ]
}
```

These paths are relative to the research project root. The manifest is the
only acquisition-to-case handoff; later preprocessing configuration does not
repeat raw directories, image lists, orbit direction, or selected dates.

The source archive is read-only to case workflows. A case may read any path
declared by its acquisition manifest, but it cannot write into `QUERY`,
`DOWNLOAD`, `RAW`, `TOPOGRAPHY`, or another case.

## 6. Multiple Topography Datasets

`TOPOGRAPHY` is organized by dataset, not by sensor. Each dataset has a stable
identifier:

```text
<region>_<source>
<region>_<source>_<coverage-or-purpose>
```

Examples are `jishishan_cop30`, `guizhou_cop30`, and
`jishishan_cop30_wide`. Bounds, buffer size, horizontal/vertical datum,
resolution, download time, and checksums belong in manifests rather than the
directory name.

`TOPOGRAPHY/catalog.json` lists dataset IDs and project-relative manifest
paths. It is an index, not an implicit default. Every geometry configuration
must explicitly select one `topography_manifest.json`; code never chooses the
first `.tif` or `.dem` found in a directory.

The source and backend products retain the dataset stem:

```text
jishishan_cop30/SOURCE/jishishan_cop30.tif
jishishan_cop30/GAMMA/jishishan_cop30.dem
jishishan_cop30/GAMMA/jishishan_cop30.dem.par
```

The historical command name `srtm2dem` does not determine the filename. A
COP30 input must never be published as `srtm.dem`.

The topography manifest records all available backend conversions. A case
records the selected dataset ID and manifest path in its geometry and
registered-stack provenance. Geometry products derived from an orbit, such as
lookup tables and radar-coordinate height grids, remain under the case's
`PRE/GAMMA/GEOMETRY`; only the source DEM and reusable GAMMA DEM are shared.

## 7. Configuration and Path Safety

The research project root and the case output root are separate concepts.
This distinction is required because a case must read project-level shared
inputs while being forbidden to write outside itself.

A case-local configuration uses the project root plus an explicit case root:

```ini
[project]
# From S1/ASCENDING_128/config/<stage>/ to the research project root.
root = ../../../..

[case:main]
case_root = S1/ASCENDING_128
acquisition_manifest = S1/ASCENDING_128/PRE/acquisition_manifest.json
topography_manifest = TOPOGRAPHY/jishishan_cop30/topography_manifest.json
output_dir = S1/ASCENDING_128/PRE/GAMMA/GEOMETRY
```

All paths are resolved from the CFG location through the configured project
root, never from the process working directory.

Path policy is asymmetric:

- declared inputs must remain inside the research project root;
- normal stage outputs and logs must remain inside the configured case root;
- topography acquisition/conversion commands are the only workflows allowed
  to write under the selected `TOPOGRAPHY/<dataset_id>` root;
- sensor query/download commands are the only workflows allowed to write in
  the sensor archive;
- symlink resolution is checked before access so a link cannot escape the
  permitted root.

Direct component CLIs may retain `--case main` during compatibility migration.
The directory layout does not depend on that label. A later Workflow launcher
may infer the one configured case, but this design does not require changing
all CLI argument syntax at once.

## 8. Analysis Pair and Visualization Layout

Scientific pair products remain grouped by date pair:

```text
ANALYSIS/GAMMA/INTERFEROGRAM/PAIRS/20231226-20240131/
├── pair.int
├── pair.int.flt
├── pair.tflt
├── pair.cc
├── pair.off
├── pair.baseline
├── pair.diff.par
└── pair.sim.topo.unw
```

The short `pair.*` names are acceptable inside a uniquely named pair
directory. Flattening hundreds of pairs into one directory is rejected.
Filtering and unwrapping publish their own `PAIRS/<date-pair>` trees and never
modify a completed interferogram directory.

Analysis does not create `quicklooks/`, PNG files, or an Analysis-local
`FIGURES` directory. Visualization reads completed manifests and publishes
figures by product type:

```text
VISUALIZATION/GAMMA/BASELINE/baseline_network.png
VISUALIZATION/GAMMA/INTF/20231226-20240131.intf.png
VISUALIZATION/GAMMA/COHERENCE/20231226-20240131.cc.png
VISUALIZATION/GAMMA/UNW/20231226-20240131.unw.png
```

The existing baseline-plot ownership decision remains valid: Analysis owns
the network and manifest; Visualization owns the rendered image. This design
supersedes only the old project output paths in that decision.

## 9. Manifest Path Contract

Directory scanning is not a cross-stage API. Every stage consumes an explicit
completed manifest and publishes its own manifest atomically after validating
all required assets.

New manifests use these path rules:

- assets owned by the same manifest use paths relative to the manifest's
  directory;
- references to another stage, a source archive, or topography use explicitly
  named project-relative fields such as `baseline_manifest_project_path` or
  `topography_manifest_project_path`;
- new portable manifests do not store absolute paths for logs, source
  manifests, radar height, or preceding-stage manifests;
- scientific metadata is stored in fields, never inferred from path spelling;
- schema versions change when path interpretation changes; old versions remain
  reader-compatible but are never silently rewritten.

Manifests record `case_id`, backend, inputs and digests so a consumer can prove
that a product belongs to the configured case and was derived from the selected
acquisition/topography inputs.

## 10. Existing Jishishan and Guizhou Evidence

The design is grounded in the current real products:

- S1 ascending has three registered VV scenes (`20231027`, `20231226`, and
  `20240131`), a completed one-pair SBAS network, and one validated
  `20231226-20240131` interferogram.
- The S1 registered stack occupies about 13 GiB. Its Analysis output occupies
  about 665 MiB; each complex interferogram is 116,163,560 bytes.
- The SAOCOM diagnostic stack contains six dates and both HH/HV polarizations,
  occupies about 19 GiB, and preserves real quality status in its manifest.
- The Jishishan COP30 source is about 14 MiB; the Guizhou COP30 source is about
  96 MiB. Both currently convert to files called `srtm.dem`, demonstrating the
  naming collision this design removes.

These sizes rule out a migration strategy based on copying complete products
into a second tree. Real-data verification must use manifests, sizes, selected
digests, and same-filesystem rename only when an explicit migration step is
approved.

## 11. Compatibility and Migration

Migration is contract-first and non-destructive:

1. Add and test project/case/topography manifest schemas and shared path
   validation without moving real data.
2. Teach readers to accept both legacy absolute/lowercase paths and the new
   portable contract; new writers emit only the new contract.
3. Make new runs publish directly into case roots.
4. Update case-local CFG files and validate them with dry-run before any
   scientific command runs.
5. Migrate small metadata, configuration, logs, and figures first.
6. Offer a separate migration command with `--dry-run` for large existing
   products. It produces a source-to-target map, detects collisions, verifies
   manifests, and never copies or deletes data implicitly.
7. Move large directories only after explicit approval and only by recoverable
   same-filesystem rename. Validate manifests and representative digests after
   each move before changing the next case.

Legacy-to-target examples are:

| Legacy | Target |
|---|---|
| `S1/DEM/` | `TOPOGRAPHY/jishishan_cop30/SOURCE/` |
| `S1/WORK/GAMMA/DEM/` | `TOPOGRAPHY/jishishan_cop30/GAMMA/` |
| `SAOCOM_Guizhou/DEM/` | `TOPOGRAPHY/guizhou_cop30/SOURCE/` |
| `S1/WORK/GAMMA/ascending/` | `S1/ASCENDING_128/PRE/GAMMA/` |
| `S1/ANALYSIS/GAMMA/ascending/` | `S1/ASCENDING_128/ANALYSIS/GAMMA/` |
| `S1/VISUALIZATION/ascending/` | `S1/ASCENDING_128/VISUALIZATION/GAMMA/` |
| `SAOCOM_Guizhou/WORK/GAMMA/` | `SAOCOM/GUIZHOU/PRE/GAMMA/` |

Completed legacy manifests remain readable in place. No large validated
product is regenerated merely to change capitalization or directory spelling.

## 12. Implementation Decomposition

This architecture is implemented in independently testable subprojects rather
than one cross-repository rewrite:

1. **Project and path contract:** Workflow schemas, case identity, common path
   resolution, containment rules, and a read-only layout validator.
2. **Topography catalog:** Preprocessing writers/readers for multiple datasets,
   truthful filenames, explicit selection, and existing DEM inventory.
3. **Acquisition-to-case handoff:** create `acquisition_manifest.json` from S1
   query/download outputs and equivalent imported-product manifests.
4. **Preprocessing case outputs:** make SLC, geometry, registration, and subset
   workflows consume manifests and publish below `PRE/`.
5. **Analysis and Visualization outputs:** remove quicklooks, adopt independent
   pair-stage directories, and publish figures below `VISUALIZATION/`.
6. **Real-project migration:** migrate Jishishan S1 cases and the Guizhou SAOCOM
   case one at a time with dry-run evidence and no scientific recomputation.

Each subproject receives its own implementation plan and acceptance gate. The
first implementation plan covers only item 1; later items cannot assume its
contract until its tests pass.

## 13. Verification

The architecture gate requires:

- schema tests for case identity, project-relative paths, dataset catalogs,
  unknown keys, path escape, symlink escape, and cross-case output rejection;
- a synthetic project containing two sensors, two S1 cases, and at least three
  topography datasets, proving that no implicit default is selected;
- read-only validation of the current S1 and SAOCOM manifests;
- inventory evidence for all legacy-to-target mappings before any move;
- unchanged scientific sizes/digests for the validated S1 baseline and
  interferogram products;
- S1 baseline and interferogram restart checks still returning `skipped`;
- the Visualization baseline command still producing a non-empty image without
  invoking Analysis or GAMMA;
- repository unit tests and `git diff --check` for every repository touched by
  an implementation subproject.

## 14. Out of Scope

- rerunning completed S1 or SAOCOM registration merely to change paths;
- implementing filtering, unwrapping, or time-series algorithms in the layout
  contract;
- copying multi-gigabyte products into a parallel tree;
- choosing a topography dataset by filename or directory order;
- deriving sensor/orbit/track metadata from a case directory name;
- merging the existing baseline-plot feature branches as part of design
  approval.
