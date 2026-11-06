# GAMMA Post-processing Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add manifest-driven GAMMA atmosphere correction, DInSAR, stacking, and `mb` workflows, with method-centric CFGs and Gansu runtime entries ready for user-operated real-data testing.

**Architecture:** Extend the existing Analysis `config -> immutable model -> side-effect-free plan -> transactional runner -> schema-v2 manifest` pattern. Atmosphere consumes quadratic-detrending lineage; three independent `insar/time_series/gamma/` workflows consume one validated atmosphere manifest through a shared network/geometry preparation contract. Existing `insar/timeseries.py` remains untouched as the legacy result-inspection API.

**Tech Stack:** Python 3.10+, stdlib `configparser`/`dataclasses`/`pathlib`/`json`, NumPy, installed GAMMA commands through `SubprocessCommandRunner`, pytest/unittest in `envInSAR`.

**Spec:** `docs/superpowers/specs/2026-11-06-gamma-postprocessing-defsour-migration-design.md`

## Global Constraints

- Run focused checks with `/home/yilun/miniconda3/envs/envInSAR/bin/python`; do not create or repair environments.
- Do not execute atmosphere, DInSAR, stacking, or GAMMA `mb` against real Gansu products; the user performs scientific acceptance.
- Do not import runtime code from `GAMMA-InSAR` or another undeclared sibling source tree.
- Analysis products are reusable only when a complete schema-v2 manifest, required products, and input signature all match.
- Existing incomplete or mismatched Analysis outputs are never overwritten; missing quicklooks may be repaired independently.
- All source inputs are read-only; science and figure directories publish transactionally from sibling staging directories.
- No numeric filter flags, implicit `find`, wildcard product discovery, mandatory `run_id`, `main`, or `test` output directories.
- Keep old scripts and legacy Gansu results unchanged until the user accepts real-data results.
- Publication/cartographic output remains outside Analysis; this plan creates only GAMMA-native stage quicklooks.

## Review Focus

- Existing interferogram manifests that do not declare a lookup table must work only when CFG supplies an explicit validated `lookup_table`; test this in Task 4.
- A selected network containing a missing atmosphere pair must fail before any GAMMA command or output directory mutation; test this in Task 4.
- Symlinked or overlapping science/figure/log/input paths must be rejected by every new loader/plan; test this in Tasks 2 and 4.
- A failure after one pair or one GAMMA `mb` subcommand must preserve any previous completed output and leave no published partial result; test this in Tasks 3, 5, 6, and 7.
- Complete science with one deleted quicklook must run only the quicklook command and keep scientific raster mtimes/content unchanged; test this in Tasks 3, 5, 6, and 7.

---

### Task 1: Formalize GAMMA Network Records and Downstream Geocoding Assets

**Files:**
- Modify: `src/geodesy_analysis/insar/network.py`
- Modify: `src/geodesy_analysis/insar/interferogram_generation/gamma/runner.py`
- Modify: `src/geodesy_analysis/insar/interferogram_generation/gamma/publication.py`
- Test: `tests/test_network.py`
- Test: `tests/test_gamma_interferogram_runner.py`

**Interfaces:**
- Produces: `GammaNetworkRecord(master: str, slave: str, perpendicular_baseline: float, temporal_baseline_days: float)` with `.name`.
- Produces: `read_gamma_network_records(path: str | Path) -> tuple[GammaNetworkRecord, ...]`.
- Produces: interferogram manifest fields `lookup_table_project_path`, `geocoded_reference_mli_project_path`, and existing map DEM/radar-height fields as required products.
- Preserves: `read_interferogram_pairs(path) -> list[str]` by deriving names from records when four-column records exist and retaining the current one-/two-column compatibility path.

- [ ] **Step 1: Add failing network-record tests**

Add tests asserting that `20231027 20231226 64.0239 60` produces one typed record, duplicate pairs/non-finite baselines/invalid dates fail, and the old one-column pair reader behavior remains unchanged.

- [ ] **Step 2: Run the focused network tests and confirm failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_network.py`

Expected: FAIL because `GammaNetworkRecord` and `read_gamma_network_records` do not exist.

- [ ] **Step 3: Implement the strict record parser**

Implement the exact interfaces above in `network.py`; require four fields for temporal-baseline consumers and keep `read_interferogram_pairs` compatible with pair-only files.

- [ ] **Step 4: Add failing interferogram-manifest asset assertions**

Extend the fake `geocoding.py` fixture and runner test to create and assert deterministic paths for `<dem_stem>.<reference>.<pol>.lt_fine` and `<dem_stem>.<reference>.<pol>.mli`; assert both appear in `required_products` and provenance.

- [ ] **Step 5: Publish the new asset identities**

Update `_geocode_reference`/manifest publication to validate the two files and record project-relative paths without scanning the directory.

- [ ] **Step 6: Run the focused tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_network.py tests/test_gamma_interferogram_runner.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/geodesy_analysis/insar/network.py src/geodesy_analysis/insar/interferogram_generation/gamma/runner.py src/geodesy_analysis/insar/interferogram_generation/gamma/publication.py tests/test_network.py tests/test_gamma_interferogram_runner.py
git commit -m "feat: publish GAMMA postprocessing inputs"
```

### Task 2: Add the Atmosphere Configuration and Plan Contract

**Files:**
- Create: `src/geodesy_analysis/insar/atmosphere/__init__.py`
- Create: `src/geodesy_analysis/insar/atmosphere/gamma/__init__.py`
- Create: `src/geodesy_analysis/insar/atmosphere/gamma/models.py`
- Create: `src/geodesy_analysis/insar/atmosphere/gamma/config.py`
- Create: `src/geodesy_analysis/insar/atmosphere/gamma/plan.py`
- Create: `src/geodesy_analysis/insar/atmosphere/gamma/publication.py`
- Test: `tests/test_gamma_atmosphere_config.py`
- Test: `tests/test_gamma_atmosphere_plan.py`

**Interfaces:**
- Produces: `load_gamma_atmosphere_config(path: Path, *, case_name: str | None = None) -> tuple[GammaAtmosphereCase, ...]`.
- Produces: `build_gamma_atmosphere_plan(case: GammaAtmosphereCase) -> GammaAtmospherePlan`.
- Produces: `gamma_atmosphere_input_signature(plan: GammaAtmospherePlan) -> str`.
- Methods: `none`, `gamma_atm_mod_2d_auto`, `gamma_atm_mod_2d_polygon`, `gamma_fspf_atm_mod_2d`.
- CFG keys: `project`, `case_root`, `processing_root`, `detrending_manifest`, `method`, `output_dir`, `figure_dir`, `intensity_background`, `fit_window_range`, `fit_window_azimuth`, `fit_step_range`, `fit_step_azimuth`, `height_correlation_threshold`, conditional `polygon_file`, and FSPF keys `fspf_mode`, `fspf_window_size`, `fspf_overlap`.
- Defaults: method-derived output/figure/log paths from `AnalysisProductLayout`; auto-mask comes from the linked MCF manifest; polygon file is mandatory only for the polygon method.

- [ ] **Step 1: Write failing strict-loader tests**

Cover every method, conditional polygon input, finite positive windows/steps, threshold range `[0,1]`, unknown/duplicate keys, explicit path overrides, method-centric defaults, symlinks, and disjoint science/figure/log/input paths.

- [ ] **Step 2: Run loader tests and confirm failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_gamma_atmosphere_config.py`

Expected: FAIL because the package does not exist.

- [ ] **Step 3: Implement models and strict CFG loading**

Use frozen dataclasses. Map method names to uppercase directory identities exactly as defined by the spec; do not derive any upstream path from the selected method.

- [ ] **Step 4: Write failing plan/lineage tests**

Build a synthetic schema-v2 chain and assert pair inventory, grid, MLI, coherence, radar height, MCF mask, detrended phase, manifest digests, polygon digest, and default commands are resolved. Reject a mismatched case, method, grid, digest, pair set, missing product, and empty polygon.

- [ ] **Step 5: Implement plan validation and signature publication**

Resolve same-stage paths relative to each source manifest and cross-stage project paths through the declared project root; validate big-endian float32 sizes as `width * lines * 4`.

- [ ] **Step 6: Run focused configuration/plan tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_gamma_atmosphere_config.py tests/test_gamma_atmosphere_plan.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/geodesy_analysis/insar/atmosphere tests/test_gamma_atmosphere_config.py tests/test_gamma_atmosphere_plan.py
git commit -m "feat: define GAMMA atmosphere workflow"
```

### Task 3: Execute and Publish Atmosphere Products

**Files:**
- Create: `src/geodesy_analysis/insar/atmosphere/gamma/runner.py`
- Create: `src/geodesy_analysis/insar/atmosphere/gamma/cli.py`
- Modify: `src/geodesy_analysis/common/reuse.py`
- Modify: `src/geodesy_analysis/insar/common/gamma_quicklooks.py`
- Modify: `pyproject.toml`
- Test: `tests/test_gamma_atmosphere_runner.py`
- Test: `tests/test_gamma_atmosphere_cli.py`
- Test: `tests/test_reuse.py`

**Interfaces:**
- Produces: `run_gamma_atmosphere(plan, *, command_runner=None, progress_sink=None) -> GammaAtmosphereRunSummary`.
- Produces CLI: `geodesy-analysis-gamma-atmosphere --config PATH [--case NAME] [--dry-run]`.
- Publishes: `atmosphere_manifest.json`, `provenance.json`, per-pair corrected phase, applicable atmosphere/diff parameters, logs, and `FIGURES/ATMOSPHERE/<METHOD>/*.bmp`.
- `none` records the detrended raster as an external project-relative product reference and does not copy it into the stage output.
- Extends: `classify_analysis_output(..., project_root: Path | None = None)` to validate optional `required_external_products` while preserving all existing callers.

- [ ] **Step 1: Write a fake GAMMA runner and failing command-contract tests**

Assert exact command sequences for all methods: `none`; `create_diff_par/atm_mod_2d/atm_sim_2d/sub_phase`; polygon `poly_mask` outside/inside plus `float_math`; and FSPF followed by atmosphere commands. Assert the protected polygon interior merge flags match the legacy script.

- [ ] **Step 2: Run runner tests and confirm failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_gamma_atmosphere_runner.py`

Expected: FAIL because `run_gamma_atmosphere` does not exist.

- [ ] **Step 3: Implement transactional execution and validation**

Use `atomic_output_directories(figures, science)`, validate each float32 output size and finite count, publish schema version 2 with complete local/external required-product and figure inventories, and preserve failed logs using the established runner pattern. Validate the `none` method's referenced detrended rasters without copying them.

- [ ] **Step 4: Add reuse, mismatch, partial-failure, and quicklook-repair tests**

Assert matching output skips, changed parameters fail without mutation, a forced later-pair failure publishes nothing, and deleting one BMP invokes only the relevant display command.

- [ ] **Step 5: Implement the CLI and entry point**

Dry-run JSON must expose case, method, all input/output/figure/log paths, grid, pair count, and selected pairs.

- [ ] **Step 6: Run the focused atmosphere suite**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_gamma_atmosphere_config.py tests/test_gamma_atmosphere_plan.py tests/test_gamma_atmosphere_runner.py tests/test_gamma_atmosphere_cli.py tests/test_gamma_quicklooks.py tests/test_reuse.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/geodesy_analysis/insar/atmosphere src/geodesy_analysis/common/reuse.py src/geodesy_analysis/insar/common/gamma_quicklooks.py pyproject.toml tests/test_gamma_atmosphere_runner.py tests/test_gamma_atmosphere_cli.py tests/test_gamma_quicklooks.py tests/test_reuse.py
git commit -m "feat: run GAMMA atmosphere correction"
```

### Task 4: Build the Shared Time-series Input Contract

**Files:**
- Create: `src/geodesy_analysis/insar/time_series/__init__.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/__init__.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/common.py`
- Test: `tests/test_gamma_time_series_common.py`

**Interfaces:**
- Produces: `GammaTimeSeriesInputs` with atmosphere lineage, ordered selected records, acquisition dates, reference date, grid, MLI assets, radar height, lookup table, map DEM/parameter, and source digests.
- Produces: `load_gamma_time_series_inputs(*, project_root: Path, atmosphere_manifest: Path, pair_list: Path | None, lookup_table: Path | None, map_dem: Path | None, map_dem_parameter: Path | None) -> GammaTimeSeriesInputs`.
- Produces: `write_gamma_diff_tab(inputs: GammaTimeSeriesInputs, destination: Path) -> Path`, `write_gamma_rmli_tab(inputs, destination) -> Path`, and `write_gamma_itab(inputs, destination) -> Path`.
- Compatibility rule: prefer declared interferogram-manifest asset fields; require an explicit CFG override when an older manifest lacks lookup/map assets; never scan the geocoding directory.

- [ ] **Step 1: Write failing manifest/network/table tests**

Assert deterministic atmosphere-to-baseline lineage, temporal baselines from four-column network records, pair-list subset order, complete pair enforcement, correct `diff_tab`/`RMLI_tab`/`itab`, and old-manifest lookup override behavior.

- [ ] **Step 2: Run the common tests and confirm failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_gamma_time_series_common.py`

Expected: FAIL because the shared contract does not exist.

- [ ] **Step 3: Implement read-only preparation**

Require explicit files, validate sizes/grids/dates, hash every manifest and selected pair list, and write tables only into a caller-supplied staging directory.

- [ ] **Step 4: Add Review Focus failures**

Add tests proving a missing selected pair, duplicate/zero temporal baseline, symlinked lookup, and explicit asset conflicting with a new manifest all fail before table writing.

- [ ] **Step 5: Run focused tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_gamma_time_series_common.py tests/test_network.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/geodesy_analysis/insar/time_series src/geodesy_analysis/insar/network.py tests/test_gamma_time_series_common.py tests/test_network.py
git commit -m "feat: prepare GAMMA time-series inputs"
```

### Task 5: Add GAMMA Stacking

**Files:**
- Create: `src/geodesy_analysis/insar/time_series/gamma/stacking/__init__.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/stacking/models.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/stacking/config.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/stacking/plan.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/stacking/publication.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/stacking/runner.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/stacking/cli.py`
- Modify: `pyproject.toml`
- Test: `tests/test_gamma_stacking.py`
- Test: `tests/test_gamma_stacking_cli.py`

**Interfaces:**
- Produces: `load_gamma_stacking_config(path: Path, *, case_name: str | None = None) -> tuple[GammaStackingCase, ...]`.
- Produces: `build_gamma_stacking_plan(case: GammaStackingCase) -> GammaStackingPlan`.
- Produces: `run_gamma_stacking(plan: GammaStackingPlan, *, command_runner=None, progress_sink=None) -> GammaStackingRunSummary`.
- Produces CLI: `geodesy-analysis-gamma-stacking`.
- CFG requires atmosphere manifest and reference range/azimuth; exposes reference window width/height, optional pair list, lookup/map asset overrides, output/figure directories, quicklook range, and colormap.
- Publishes `TIMESERIES/STACKING/timeseries_manifest.json` with mean phase rate, uncertainties, radar/geocoded LOS velocity, pair network, units, reference window, commands, and lineage.

- [ ] **Step 1: Write failing loader/plan/command tests**

Assert strict numeric bounds, method-centric paths, complete selected network, exact `stacking -> dispmap -> geocode_back` commands, configurable reference window, and no `.atm.unw`/`.fill` filename assumptions.

- [ ] **Step 2: Run and confirm failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_gamma_stacking.py`

Expected: FAIL because the workflow does not exist.

- [ ] **Step 3: Implement config, plan, signature, runner, and manifest**

Use the shared input contract, transactional science/figure publication, exact float raster size validation, and stage-local GAMMA quicklooks.

- [ ] **Step 4: Add reuse/failure/figure-repair tests**

Cover missing network pair before command execution, forced `stacking` and late `geocode_back` failures, signature mismatch, completed skip, and quicklook-only repair.

- [ ] **Step 5: Implement and test CLI dry-run**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_gamma_stacking.py tests/test_gamma_stacking_cli.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/geodesy_analysis/insar/time_series/gamma/stacking pyproject.toml tests/test_gamma_stacking.py tests/test_gamma_stacking_cli.py
git commit -m "feat: migrate GAMMA stacking"
```

### Task 6: Add Single-pair GAMMA DInSAR

**Files:**
- Create: `src/geodesy_analysis/insar/time_series/gamma/dinsar/__init__.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/dinsar/models.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/dinsar/config.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/dinsar/plan.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/dinsar/publication.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/dinsar/runner.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/dinsar/cli.py`
- Modify: `pyproject.toml`
- Test: `tests/test_gamma_dinsar.py`
- Test: `tests/test_gamma_dinsar_cli.py`

**Interfaces:**
- Produces: `load_gamma_dinsar_config(path: Path, *, case_name: str | None = None) -> tuple[GammaDinsarCase, ...]`.
- Produces: `build_gamma_dinsar_plan(case: GammaDinsarCase) -> GammaDinsarPlan`.
- Produces: `run_gamma_dinsar(plan: GammaDinsarPlan, *, command_runner=None, progress_sink=None) -> GammaDinsarRunSummary`.
- Produces CLI: `geodesy-analysis-gamma-dinsar`.
- CFG requires exactly one `pair = YYYYMMDD-YYYYMMDD` plus atmosphere manifest; optional explicit geocoding assets and output/figure overrides.
- Publishes cumulative LOS displacement with `method = gamma_dinsar` and `deformation_quantity = cumulative_displacement`; never labels the direct `dispmap` output as velocity.

- [ ] **Step 1: Write failing semantic and command tests**

Reject missing/multiple/unknown pairs; assert one corrected phase is passed to `dispmap`; assert radar/geocoded outputs and manifest quantity/units are displacement, not mean velocity.

- [ ] **Step 2: Run and confirm failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_gamma_dinsar.py`

Expected: FAIL because the workflow does not exist.

- [ ] **Step 3: Implement config, plan, signature, runner, and manifest**

Reuse common geometry preparation but do not create a multi-row `diff_tab`; run and validate one explicit pair transactionally.

- [ ] **Step 4: Add reuse/failure/figure-repair tests**

Cover forced command failure, incomplete/mismatched output preservation, skip, and quicklook-only repair.

- [ ] **Step 5: Implement and test CLI**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_gamma_dinsar.py tests/test_gamma_dinsar_cli.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/geodesy_analysis/insar/time_series/gamma/dinsar pyproject.toml tests/test_gamma_dinsar.py tests/test_gamma_dinsar_cli.py
git commit -m "feat: migrate single-pair GAMMA DInSAR"
```

### Task 7: Add GAMMA `mb` SBAS/ISBAS Processing

**Files:**
- Create: `src/geodesy_analysis/insar/time_series/gamma/mb/__init__.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/mb/models.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/mb/config.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/mb/plan.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/mb/publication.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/mb/runner.py`
- Create: `src/geodesy_analysis/insar/time_series/gamma/mb/cli.py`
- Modify: `pyproject.toml`
- Test: `tests/test_gamma_mb.py`
- Test: `tests/test_gamma_mb_cli.py`

**Interfaces:**
- Produces: `load_gamma_mb_config(path: Path, *, case_name: str | None = None) -> tuple[GammaMbCase, ...]`.
- Produces: `build_gamma_mb_plan(case: GammaMbCase) -> GammaMbPlan`.
- Produces: `run_gamma_mb(plan: GammaMbPlan, *, command_runner=None, progress_sink=None) -> GammaMbRunSummary`.
- Produces CLI: `geodesy-analysis-gamma-mb`.
- CFG exposes `mb_mode`, reference range/azimuth/width/height, `gamma`, `dtmax`, `generate_mean_geocoded`, `generate_displacement`, `generate_geocoded_displacement`, display range/colormap, optional `visdt_pwr`, optional pair list, asset overrides, and output/figure directories.
- Publishes mean velocity separately from cumulative `DISPLACEMENT/` and `DISPLACEMENT_GEO/`; writes large `TS_*.diff` and `TS_tpf_*.tpf` directly below `INTERMEDIATE/`.

- [ ] **Step 1: Write failing strict-loader and plan tests**

Cover conditional executable requirement, positive numeric constraints, generation-flag combinations, pair/date/itab consistency, output subdirectories, and explicit metadata quantities/units.

- [ ] **Step 2: Run and confirm failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_gamma_mb.py`

Expected: FAIL because the workflow does not exist.

- [ ] **Step 3: Add exact fake-command contract tests**

Assert `mb -> tpf_2d -> ts_rate -> dispmap`, optional mean geocoding, optional `mk_dispmap_2d`, optional `mk_geo_data_all`, final mask geocoding, and that no hard-coded `/opt/GAMMA_*` or home path occurs.

- [ ] **Step 4: Implement config, plan, execution, validation, and publication**

Keep intermediate files in their declared destination from creation, validate epoch/date counts, publish schema-v2 manifest/provenance, and use transactional output/figures.

- [ ] **Step 5: Add reuse/failure/figure-repair tests**

Force early `mb` and late epoch-geocoding failures, assert no partial publication, then cover skip, mismatch preservation, and missing-quicklook repair.

- [ ] **Step 6: Implement and test CLI**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_gamma_mb.py tests/test_gamma_mb_cli.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/geodesy_analysis/insar/time_series/gamma/mb pyproject.toml tests/test_gamma_mb.py tests/test_gamma_mb_cli.py
git commit -m "feat: migrate GAMMA mb processing"
```

### Task 8: Reorganize Analysis CFGs and Prepare Gansu Runtime Handoff

**Files:**
- Move: `config_examples/analysis/gamma_baseline.cfg` -> `config/GAMMA_mb/gamma_baseline.cfg`
- Move: `config_examples/analysis/gamma_geocoding.cfg` -> `config/GAMMA_mb/gamma_geocoding.cfg`
- Move: `config_examples/analysis/gamma_interferogram.cfg` -> `config/GAMMA_mb/gamma_interferogram.cfg`
- Move: `config_examples/analysis/insar_filtering.cfg` -> `config/GAMMA_mb/insar_filtering.cfg`
- Move: `config_examples/analysis/gamma_mcf_unwrapping.cfg` -> `config/GAMMA_mb/gamma_mcf_unwrapping.cfg`
- Move: `config_examples/analysis/gamma_quad_detrending.cfg` -> `config/GAMMA_mb/gamma_quad_detrending.cfg`
- Create: `config/GAMMA_mb/gamma_atmosphere.cfg`
- Create: `config/GAMMA_mb/gamma_dinsar.cfg`
- Create: `config/GAMMA_mb/gamma_stacking.cfg`
- Create: `config/GAMMA_mb/gamma_sbas_mb.cfg`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/workflows/gamma_insar.md`
- Move: `../Gansu_Jishishan_LT1/config/2analysis/gamma_baseline.cfg` -> `../Gansu_Jishishan_LT1/config/GAMMA_mb/gamma_baseline.cfg`
- Move: `../Gansu_Jishishan_LT1/config/2analysis/gamma_geocoding.cfg` -> `../Gansu_Jishishan_LT1/config/GAMMA_mb/gamma_geocoding.cfg`
- Move: `../Gansu_Jishishan_LT1/config/2analysis/gamma_interferogram.cfg` -> `../Gansu_Jishishan_LT1/config/GAMMA_mb/gamma_interferogram.cfg`
- Move: `../Gansu_Jishishan_LT1/config/2analysis/insar_filtering.cfg` -> `../Gansu_Jishishan_LT1/config/GAMMA_mb/insar_filtering.cfg`
- Move: `../Gansu_Jishishan_LT1/config/2analysis/gamma_mcf_unwrapping.cfg` -> `../Gansu_Jishishan_LT1/config/GAMMA_mb/gamma_mcf_unwrapping.cfg`
- Move: `../Gansu_Jishishan_LT1/config/2analysis/gamma_quad_detrending.cfg` -> `../Gansu_Jishishan_LT1/config/GAMMA_mb/gamma_quad_detrending.cfg`
- Create: `../Gansu_Jishishan_LT1/config/GAMMA_mb/{gamma_atmosphere,gamma_dinsar,gamma_stacking,gamma_sbas_mb}.cfg`
- Create: `../Gansu_Jishishan_LT1/config/GAMMA_mb/REAL_DATA_TESTING.md`
- Modify: `tests/test_config_examples.py`
- Modify: `tests/test_architecture.py`

**Interfaces:**
- Repository configs live only under `config/GAMMA_mb/`; no `config_examples/analysis/` copy remains.
- Gansu Analysis configs live only under `config/GAMMA_mb/`; runtime CFGs expose every upstream manifest, compatibility lookup override where needed, output, figure, and log path.
- Handoff document contains commands but does not run them.

- [ ] **Step 1: Update failing path/documentation tests**

Assert every packaged CFG uses the required path-contract headings, parses from an unrelated CWD, derives the approved method roots, and no README/pyproject/test reference remains to `config_examples/analysis` or `config/2analysis`.

- [ ] **Step 2: Run and confirm failure**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q tests/test_config_examples.py tests/test_architecture.py`

Expected: FAIL on the old paths and missing new CFGs.

- [ ] **Step 3: Move configs and update packaging/docs**

Use `apply_patch` for content edits and a non-destructive rename for tracked files. Keep bilingual README structure and the approved flat `GAMMA_mb` category.

- [ ] **Step 4: Add Gansu path-only runtime configs and handoff commands**

Use the existing S1 manifests, explicit current lookup assets for pre-upgrade manifests, and new method-centric outputs. Do not execute external GAMMA science.

- [ ] **Step 5: Run the complete focused Analysis gate**

Run:

```bash
/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q \
  tests/test_network.py tests/test_product_layout.py tests/test_reuse.py \
  tests/test_config_examples.py tests/test_gamma_atmosphere_config.py \
  tests/test_gamma_atmosphere_plan.py tests/test_gamma_atmosphere_runner.py \
  tests/test_gamma_atmosphere_cli.py tests/test_gamma_time_series_common.py \
  tests/test_gamma_stacking.py tests/test_gamma_stacking_cli.py \
  tests/test_gamma_dinsar.py tests/test_gamma_dinsar_cli.py \
  tests/test_gamma_mb.py tests/test_gamma_mb_cli.py
git diff --check
```

Expected: all selected tests PASS and `git diff --check` is silent.

- [ ] **Step 6: Commit repository and project changes separately**

```bash
git add config pyproject.toml README.md docs tests src
git commit -m "docs: expose GAMMA postprocessing workflows"
```

Record the Gansu project changes in its own repository only if it is a Git worktree; otherwise leave them as an explicit uncommitted project handoff and report that state.

### Task 9: Final Analysis Review and Delivery Check

**Files:**
- Review only: all files changed by Tasks 1-8

**Interfaces:**
- Consumes all preceding task outputs.
- Produces a handoff summary listing commands, configs, unexecuted real-data tests, and legacy scripts retained for comparison.

- [ ] **Step 1: Inspect repository status and commit boundaries**

Confirm pre-existing unrelated modifications remain untouched and every new commit contains only its task scope.

- [ ] **Step 2: Run compile and focused tests once**

Run:

```bash
/home/yilun/miniconda3/envs/envInSAR/bin/python -m compileall -q src/geodesy_analysis
/home/yilun/miniconda3/envs/envInSAR/bin/python -m pytest -q \
  tests/test_gamma_atmosphere_config.py tests/test_gamma_atmosphere_plan.py \
  tests/test_gamma_atmosphere_runner.py tests/test_gamma_atmosphere_cli.py \
  tests/test_gamma_time_series_common.py tests/test_gamma_stacking.py \
  tests/test_gamma_dinsar.py tests/test_gamma_mb.py tests/test_config_examples.py
git diff --check
```

Expected: compile succeeds, selected tests PASS, diff check silent.

- [ ] **Step 3: Verify no real project products were written**

Check that only CFG/Markdown files changed below `Gansu_Jishishan_LT1` and no new `ATMOSPHERE`, `TIMESERIES`, `FIGURES`, or `LOG` product was produced.

- [ ] **Step 4: Record delivery status**

Report that fake-command and synthetic contracts passed, real-data scientific parity is pending user execution, and legacy entry points remain available.
