# Analysis Products and Figures Layout Design

**Date:** 2026-10-14  
**Status:** proposed for user review  
**Repositories:** Geodesy-Analysis, Geodesy-Visualization  
**Project contract:** study-project result directories and their manifests

## 1. Purpose

Make InSAR results easy to inspect without mixing scientific rasters with
rendered pictures. Analysis stages must remain independently publishable and
restart-safe, while users must be able to find every figure by product type and
every numerical product by interferometric pair.

Success means:

- `quicklooks/` no longer exists below an Analysis product;
- all rendered images are below the study project's top-level `FIGURES/` tree;
- wrapped interferograms, coherence, and future unwrapped products have
  separate figure categories;
- numerical pair products remain grouped by date pair rather than being spread
  through one directory;
- filtering and unwrapping do not mutate a completed interferogram directory;
- manifests, rather than directory scans, remain the interface between stages.

## 2. Ownership Boundary

Geodesy-Analysis owns numerical processing and scientific manifests. It may
call GAMMA or another configured processing backend, but it must not render or
publish PNG quicklooks.

Geodesy-Visualization owns rendered figures. It reads completed Analysis
manifests and numerical assets without invoking GAMMA or altering Analysis
products.

The filesystem name `FIGURES` describes project output, not repository
ownership. Code that writes below `FIGURES/` still belongs to
Geodesy-Visualization.

## 3. Target Project Layout

For one sensor, backend, and orbit direction, numerical products use this
layout:

```text
S1/ANALYSIS/GAMMA/ascending/
├── BASELINE/
│   ├── baseline_manifest.json
│   ├── baseline_select_SBAS
│   ├── image_pairs_SBAS
│   └── provenance.json
├── INTERFEROGRAM/
│   ├── interferogram_manifest.json
│   ├── provenance.json
│   ├── MLI/
│   │   ├── 20231226.mli
│   │   ├── 20231226.mli.par
│   │   └── ave_mli
│   └── PAIRS/
│       └── 20231226-20240131/
│           ├── pair.int
│           ├── pair.int.flt
│           ├── pair.tflt
│           ├── pair.cc
│           ├── pair.off
│           ├── pair.baseline
│           ├── pair.diff.par
│           └── pair.sim.topo.unw
├── FILTERING/
│   ├── filtering_manifest.json
│   ├── provenance.json
│   └── PAIRS/
│       └── 20231226-20240131/
│           └── pair.filtered
└── UNWRAPPING/
    ├── unwrapping_manifest.json
    ├── provenance.json
    └── PAIRS/
        └── 20231226-20240131/
            └── pair.unw
```

Rendered figures use one separate, human-facing tree:

```text
S1/FIGURES/GAMMA/ascending/
├── BASELINE/
│   └── baseline_network.png
├── INTF/
│   └── 20231226-20240131.intf.png
├── COHERENCE/
│   └── 20231226-20240131.cc.png
└── UNW/
    └── 20231226-20240131.unw.png
```

The same pattern applies to other sensors and processing backends; for example,
`SAOCOM/ANALYSIS/GAMMA/...` and `SAOCOM/FIGURES/GAMMA/...`. A future ISCE
backend uses `ISCE` in place of `GAMMA` without sharing backend-specific files.

## 4. Pair Organization

Numerical products remain in one directory per date pair. The pair directory
is named `YYYYMMDD-YYYYMMDD`, with the earlier/master and later/slave order
preserved from the selected network. Files inside retain concise backend names
such as `pair.tflt` and `pair.cc` because the directory already supplies the
pair identity.

This is preferred over a flat directory because a normal SBAS project can
contain hundreds of pairs and thousands of files. It is also preferred over a
single pair directory shared by all stages: filtering and unwrapping must be
able to publish atomically without modifying the completed interferogram
stage.

Figures are intentionally organized in the opposite direction: first by
product type, then by a date-pair filename. This makes visual comparison of all
wrapped interferograms or all unwrapped results straightforward while keeping
filenames unique outside their numerical pair directory.

## 5. Analysis Changes

The interferogram runner will:

- stop accepting a `quicklook_renderer` callback;
- stop creating `INTERFEROGRAM/quicklooks`;
- stop recording quicklook failures in scientific `warnings`;
- write new products under uppercase `MLI/` and `PAIRS/`;
- continue publishing the manifest only after every required numerical asset
  validates;
- continue preserving pair order and explicit per-product paths in the
  manifest.

`warnings` remains available only for scientific processing warnings if such a
warning category is later defined. Rendering failures never affect Analysis
completion.

Filtering and unwrapping will each consume the preceding completed manifest and
publish their own output directory and manifest. They will not add files to an
existing `INTERFEROGRAM/PAIRS/<pair>/` directory.

## 6. Visualization Interface

Baseline plotting keeps its manifest-driven command and changes only its
project output path to `FIGURES/.../BASELINE`.

Pair-product rendering will use one CFG-driven Visualization entry. Each case
declares:

- `source_manifest`: completed Analysis manifest;
- `product`: `intf`, `coherence`, or `unw`;
- `figure_root`: the case root below `SENSOR/FIGURES/BACKEND/DIRECTION`;
- normal display controls such as color palette, phase range, DPI, and title;
- optional pair selection, defaulting to all pairs in manifest order.

The renderer chooses the correct manifest asset and output category:

| `product` | Source asset | Output directory | Filename suffix |
|---|---|---|---|
| `intf` | differential or filtered wrapped interferogram | `INTF/` | `.intf.png` |
| `coherence` | coherence raster | `COHERENCE/` | `.cc.png` |
| `unw` | unwrapped phase | `UNW/` | `.unw.png` |

`unw` configuration may be written before the unwrapping workflow exists, but
execution must fail clearly if no completed unwrapping manifest is available.
The command never infers scientific inputs by scanning directories.

## 7. Manifest and Compatibility Rules

New Analysis manifests continue to store project-relative asset paths. The
manifest remains the authoritative location map, so consumers do not hardcode
`MLI`, `PAIRS`, or old lowercase names.

Existing schema-1 manifests whose paths reference `mli/` and `pairs/` remain
readable and restart-safe. New writers emit `MLI/` and `PAIRS/`; compatibility
is achieved through manifest paths, not by creating duplicate directories or
symlinks.

The empty `quicklooks/` directory is not a required product and may be removed.
If an older project contains non-empty quicklooks, migration must first copy or
move recognizable pair images into the appropriate `FIGURES` category, verify
their count and non-zero size, and record the operation before removing the old
directory.

## 8. Jishishan Project Migration

The representative project will be migrated only after the new readers and
writers pass unit tests:

1. Move the validated baseline network figure from
   `S1/VISUALIZATION/ascending/BASELINE/` to
   `S1/FIGURES/GAMMA/ascending/BASELINE/` and update its Visualization CFG.
2. Remove the obsolete Analysis-local `FIGURES/` baseline test image after the
   new figure is verified.
3. Remove `INTERFEROGRAM/quicklooks` only if it is empty; otherwise follow the
   non-empty migration rule above.
4. Keep the existing lowercase `mli/` and `pairs/` scientific products in
   place because the completed manifest points to them. Do not rewrite a
   validated historical product merely for capitalization.
5. Generate future rerun outputs with the new uppercase layout.
6. Write migration evidence under
   `LOG/migrations/analysis-product-layout/validation.json`.

This avoids duplicating large rasters and preserves the already validated
interferogram result.

## 9. Failure and Restart Behavior

- Analysis failures preserve detailed logs and do not publish a partial stage
  directory.
- Visualization writes each figure through a temporary sibling and replaces
  the final image only after rendering succeeds.
- A missing or malformed manifest, absent asset, unsafe path, or unknown
  product is a configuration error and creates no final figure.
- Re-running Analysis with identical complete inputs returns `skipped` even if
  no figure exists.
- Re-running Visualization may replace only its configured figure outputs; it
  never modifies Analysis manifests or rasters.

## 10. Verification

Automated checks will cover:

- no Analysis production source contains quicklook rendering or a
  `quicklooks/` output;
- new interferogram publication uses `MLI/` and `PAIRS/<pair>/`;
- legacy lowercase manifest paths still validate and skip;
- pair order and product-path identity survive publication;
- `intf`, `coherence`, and `unw` map to the intended source and figure category;
- figure filenames include the exact date pair;
- output path containment and atomic figure replacement;
- no Visualization action invokes GAMMA.

The real-project gate will reuse the completed Jishishan interferogram manifest,
render at least one `intf` and one `coherence` figure, inspect them, verify that
Analysis still returns `skipped`, and record sizes and digests. `unw` receives a
unit-test fixture until a completed unwrapping manifest is available.

## 11. Out of Scope

- implementing filtering or unwrapping algorithms in this change;
- changing scientific GAMMA command parameters;
- flattening all pair products into one directory;
- duplicating legacy products solely to match capitalization;
- treating figures as prerequisites for later Analysis stages.
