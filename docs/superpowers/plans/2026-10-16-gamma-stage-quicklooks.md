# GAMMA Stage Quicklooks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore stage-owned GAMMA intensity, phase, coherence, filtered, and MCF quicklooks while exposing safe configurable visualization directories and backfilling the Jishishan project without recomputing scientific rasters.

**Architecture:** Each existing Analysis case owns a resolved `visualization_dir`. Runners call GAMMA DISP immediately after validating their scientific products, publish flat BMP inventories, and record project-relative quicklook paths in the stage manifest. Existing schema-v2 scientific outputs without quicklooks enter an additive repair path that reads but never rewrites scientific rasters.

**Tech Stack:** Python 3.10+, dataclasses, pathlib, JSON manifests, unittest, GAMMA DISP (`raspwr`, `rasmph`, `rasdt_pwr`), envInSAR.

**Spec:** `docs/superpowers/specs/2026-10-16-gamma-stage-quicklooks-design.md`

## Global Constraints

- Modify only `/mnt/beegfs/procesados/yiluntan/Geodesy-Analysis` and the matching `/mnt/beegfs/procesados/yiluntan/Gansu_Jishishan_LT1` project files.
- Treat `/mnt/beegfs/procesados/yiluntan/GAMMA-InSAR` as read-only migration evidence; do not modify Geodesy-Visualization.
- Use the existing interferogram, filtering, and GAMMA MCF CFG/CLI entry points; add no visualization CLI, visualization CFG, picture-type case, or run ID.
- Default quicklooks are required, flat by stage/method, and generated in envInSAR with the legacy GAMMA DISP arguments and color maps.
- Explicit `visualization_dir` must resolve inside the bound case root and must not overlap the case's scientific output or declared input path.
- Existing Gansu scientific rasters are read-only during backfill; only CFG, manifest/provenance metadata, logs, and `VISUALIZATION/` products may change.
- Run only focused unit modules plus the real Gansu quicklook commands; do not rerun unrelated repository/environment suites.
- Merge all implementation commits into `main` and push Geodesy-Analysis once at the end.

## Review Focus

- A relative, absolute, symlinked, or cross-case `visualization_dir` must resolve inside the active case and fail before any command runs; Task 1 adds this test.
- A complete legacy scientific manifest with no quicklook fields must trigger visualization-only repair, with zero scientific GAMMA commands; Tasks 3–5 add this test.
- A partial visualization directory may be repaired only when every existing entry belongs to the expected flat filename inventory for the matching scientific manifest; any unexpected content must conflict and remain untouched; Tasks 3–5 add this test.
- A GAMMA DISP command that exits successfully without producing a nonempty BMP must fail completion and preserve logs; Tasks 2–5 add this test.
- Flat acquisition/pair filenames must remain unique and no visualization `pairs/` directory may appear; Tasks 3–5 add this assertion.

---

### Task 1: Configuration and path contract

**Files:**
- Modify: `src/geodesy_analysis/common/case_paths.py`
- Modify: `src/geodesy_analysis/insar/interferogram_generation/gamma/models.py`
- Modify: `src/geodesy_analysis/insar/interferogram_generation/gamma/config.py`
- Modify: `src/geodesy_analysis/insar/interferogram_generation/gamma/cli.py`
- Modify: `src/geodesy_analysis/insar/filtering/models.py`
- Modify: `src/geodesy_analysis/insar/filtering/config.py`
- Modify: `src/geodesy_analysis/insar/filtering/cli.py`
- Modify: `src/geodesy_analysis/insar/unwrapping/gamma/mcf/models.py`
- Modify: `src/geodesy_analysis/insar/unwrapping/gamma/mcf/config.py`
- Modify: `src/geodesy_analysis/insar/unwrapping/gamma/mcf/cli.py`
- Test: `tests/test_case_paths.py`
- Test: `tests/test_gamma_interferogram_config.py`
- Test: `tests/test_filtering_config.py`
- Test: `tests/test_gamma_mcf_config.py`

**Interfaces:**
- Produces: `resolve_case_visualization_output(paths, value, *, scientific_output, inputs) -> Path` and a `visualization_dir: Path` field on `GammaInterferogramCase`, `FilteringCase`, and `GammaMcfCase`.
- Defaults: `VISUALIZATION/INTERFEROGRAM_GENERATION/GAMMA`, `VISUALIZATION/FILTERING/<METHOD>`, and `VISUALIZATION/UNWRAPPING/GAMMA_MCF` below `case_root`.

- [ ] **Step 1: Write failing configuration tests**

  Add assertions for all three default directories, explicit in-case overrides, CLI dry-run summaries, rejection of project/case escapes and symlink escapes, and rejection when visualization overlaps the scientific output or an input.

- [ ] **Step 2: Run configuration tests and verify failure**

  Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_case_paths tests.test_gamma_interferogram_config tests.test_filtering_config tests.test_gamma_mcf_config -v`

  Expected: FAIL because the case models and parsers do not expose `visualization_dir`.

- [ ] **Step 3: Implement the path resolver and CFG fields**

  Accept optional `visualization_dir`, derive the method/stage default, resolve it with case containment and symlink checks, reject overlap, and include it in CLI plan summaries.

- [ ] **Step 4: Run configuration tests**

  Expected: all selected modules PASS.

- [ ] **Step 5: Commit**

  Commit message: `Expose GAMMA quicklook output directories`

### Task 2: Shared GAMMA quicklook command contract

**Files:**
- Create: `src/geodesy_analysis/insar/common/gamma_quicklooks.py`
- Create: `tests/test_gamma_quicklooks.py`

**Interfaces:**
- Produces: `mli_quicklook_command(data: Path, width: int, output: Path) -> tuple[str, ...]`.
- Produces: `wrapped_phase_quicklook_command(data: Path, width: int, output: Path, *, nonlocal_mode: bool = False) -> tuple[str, ...]`.
- Produces: `coherence_quicklook_command(data: Path, width: int, output: Path, *, background: Path | None) -> tuple[str, ...]`.
- Produces: `unwrapped_phase_quicklook_command(data: Path, width: int, output: Path) -> tuple[str, ...]`.
- Produces: `require_nonempty_quicklook(path: Path, label: str) -> Path`.

- [ ] **Step 1: Write failing exact-command tests**

  Pin `gray.cm`, `rmg.cm`, and `cc.cm`, the legacy positional `-` arguments, explicit destination paths, NL-InSAR's `rasdt_pwr` phase branch, and rejection of missing/empty BMP outputs.

- [ ] **Step 2: Run and verify failure**

  Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_quicklooks -v`

  Expected: FAIL because the module does not exist.

- [ ] **Step 3: Implement pure command builders and validation**

  Keep this module free of manifest, CFG, Matplotlib, and subprocess ownership; runners remain responsible for execution and logging.

- [ ] **Step 4: Run the quicklook tests**

  Expected: PASS.

- [ ] **Step 5: Commit**

  Commit message: `Define GAMMA quicklook command contracts`

### Task 3: Interferogram intensity, phase, and coherence quicklooks

**Files:**
- Modify: `src/geodesy_analysis/insar/interferogram_generation/gamma/runner.py`
- Modify: `src/geodesy_analysis/insar/interferogram_generation/gamma/publication.py`
- Modify: `tests/test_gamma_interferogram_runner.py`

**Interfaces:**
- Consumes: Task 1's `GammaInterferogramCase.visualization_dir` and Task 2's command builders.
- Produces: manifest `visualization_dir_project_path`, per-MLI `quicklook_project_path`, `average_mli_quicklook_project_path`, and pair `quicklooks` containing `phase_project_path` and `coherence_project_path`.

- [ ] **Step 1: Replace the tests that prohibit/ignore quicklooks**

  Assert command order includes one `raspwr` per date plus `ave_mli`, then `rasmph` and `rasdt_pwr` per pair; assert the flat BMP names and manifest project paths; assert no `pairs/` directory below visualization.

- [ ] **Step 2: Add legacy repair and failure tests**

  Start from a valid complete manifest without quicklook fields, rerun with a fake runner, and assert only DISP commands execute and science file bytes remain unchanged. Also assert an omitted BMP fails and unrelated existing visualization content conflicts.

- [ ] **Step 3: Run the interferogram runner tests and verify failure**

  Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_interferogram_runner -v`

- [ ] **Step 4: Implement new-run and repair publication**

  Generate all acquisition MLI, `ave_mli`, pair phase, and pair coherence BMPs in the configured flat directory. Treat the manifest write as the final completion marker and preserve existing scientific rasters during repair.

- [ ] **Step 5: Run the interferogram tests**

  Expected: PASS.

- [ ] **Step 6: Commit**

  Commit message: `Restore GAMMA interferogram quicklooks`

### Task 4: Filtering phase and coherence quicklooks

**Files:**
- Modify: `src/geodesy_analysis/insar/filtering/runner.py`
- Modify: `src/geodesy_analysis/insar/filtering/publication.py`
- Modify: `tests/test_filtering_runner.py`

**Interfaces:**
- Consumes: Task 1's `FilteringCase.visualization_dir` and Task 2's builders.
- Produces: flat `<pair>.tflt.filt.bmp` and `<pair>.coh.filt.bmp`, plus manifest pair `quicklooks` project paths.

- [ ] **Step 1: Write failing three-method visualization tests**

  Pin BM3D/ADF `rasmph` and `ave_mli`-backed coherence commands, NL-InSAR's two background-free `rasdt_pwr` commands, flat filenames, and manifest paths.

- [ ] **Step 2: Add repair, partial-directory, and missing-BMP tests**

  Assert a legacy completed filter output runs only two DISP commands per pair, does not alter `pair.tflt.filt`, `pair.coh.filt`, or `coh_ave.coh`, rejects unrelated visualization content, and preserves failure logs.

- [ ] **Step 3: Run and verify failure**

  Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_filtering_runner -v`

- [ ] **Step 4: Implement method-aware quicklook execution and publication**

  Read `ave_mli` from the interferogram manifest for GAMMA methods, generate the flat inventory, validate nonempty files, and update manifest/provenance last.

- [ ] **Step 5: Run the filtering tests**

  Expected: PASS.

- [ ] **Step 6: Commit**

  Commit message: `Restore filtering quicklooks`

### Task 5: GAMMA MCF unwrapped quicklooks

**Files:**
- Modify: `src/geodesy_analysis/insar/unwrapping/gamma/mcf/runner.py`
- Modify: `src/geodesy_analysis/insar/unwrapping/gamma/mcf/publication.py`
- Modify: `tests/test_gamma_mcf_runner.py`

**Interfaces:**
- Consumes: Task 1's `GammaMcfCase.visualization_dir` and Task 2's unwrapped command builder.
- Produces: flat `<pair>.tflt.filt.unw.bmp` and pair `quicklook_project_path` in `unwrapping_manifest.json`.

- [ ] **Step 1: Write failing new-run and legacy-repair tests**

  Assert every `mcf` is followed by `rasdt_pwr`, BMPs are flat/nonempty, the existing Analysis `mask/final.mask.bmp` remains the sole mask, and repair invokes no `mcf` commands or scientific writes.

- [ ] **Step 2: Add missing-BMP and conflicting-directory tests**

  Assert DISP success without output fails completion, logs survive, and unrelated visualization content is never overwritten.

- [ ] **Step 3: Run and verify failure**

  Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_mcf_runner -v`

- [ ] **Step 4: Implement MCF quicklook generation and repair**

  Use the validated unwrapped float raster, publish one flat BMP per pair, and atomically update manifest/provenance after visualization succeeds.

- [ ] **Step 5: Run the MCF tests**

  Expected: PASS.

- [ ] **Step 6: Commit**

  Commit message: `Restore GAMMA MCF quicklooks`

### Task 6: Public configuration and ownership documentation

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/workflows/gamma_insar.md`
- Modify: `docs/superpowers/specs/2026-10-16-gamma-stage-quicklooks-design.md`
- Modify: `config_examples/gamma_interferogram.cfg`
- Modify: `config_examples/insar_filtering.cfg`
- Modify: `config_examples/gamma_mcf_unwrapping.cfg`
- Modify: `tests/test_architecture.py`
- Modify: `tests/test_config_examples.py`

**Interfaces:**
- Documents: Analysis owns GAMMA DISP quality-control quicklooks; Geodesy-Visualization owns publication/cartographic figures.
- Documents: all default/manual `visualization_dir` values and flat inventories.

- [ ] **Step 1: Write failing public-contract assertions**

  Replace the blanket no-rendering assertions with the narrower rule: no Matplotlib/PyGMT/geodesy_visualization dependency, while all three example CFGs expose or document `visualization_dir` and no quicklook `pairs/` layout appears.

- [ ] **Step 2: Run and verify failure**

  Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_architecture tests.test_config_examples -v`

- [ ] **Step 3: Update docs and examples**

  Mark the spec approved, explain stage-owned GAMMA quicklooks and future-stage rule, and remove statements that Analysis creates no images.

- [ ] **Step 4: Run documentation contract tests and `git diff --check`**

  Expected: PASS and no whitespace errors.

- [ ] **Step 5: Commit**

  Commit message: `Document stage-owned GAMMA quicklooks`

### Task 7: Gansu project backfill in envInSAR

**Files:**
- Modify: `/mnt/beegfs/procesados/yiluntan/Gansu_Jishishan_LT1/S1/ASCENDING_128/config/analysis/gamma_interferogram.cfg`
- Modify: `/mnt/beegfs/procesados/yiluntan/Gansu_Jishishan_LT1/S1/ASCENDING_128/config/analysis/insar_filtering.cfg`
- Modify: `/mnt/beegfs/procesados/yiluntan/Gansu_Jishishan_LT1/S1/ASCENDING_128/config/analysis/gamma_mcf_unwrapping.cfg`
- Create: corresponding BMP inventories under the configured `VISUALIZATION/` directories
- Modify: existing stage manifest/provenance JSON only through the repair-capable runners

**Interfaces:**
- Consumes: Tasks 3–5 installed/editable Analysis CLIs and current complete scientific manifests.
- Produces: user-editable project CFG directory entries and nonempty real GAMMA BMPs without scientific recomputation.

- [ ] **Step 1: Add explicit `visualization_dir` to the three Gansu CFGs**

  Use the standard stage/method paths from the spec, including one path in each filtering case.

- [ ] **Step 2: Record scientific file checksums and run the three CLIs**

  Use `/home/yilun/miniconda3/envs/envInSAR/bin/geodesy-analysis-*` and the existing CFGs. The command logs must show visualization repair only for the already complete stages.

- [ ] **Step 3: Verify real outputs and immutability**

  Check every expected BMP exists and is nonempty, no visualization `pairs/` directory exists, manifests contain project-relative quicklook paths, and the recorded scientific checksums did not change.

### Task 8: Focused final verification and delivery

**Files:**
- Verify only; commit any final plan checkbox/document status updates with the implementation.

**Interfaces:**
- Produces: clean Geodesy-Analysis `main`, remote `origin/main` at the same final commit, and a local Gansu project synchronized with that code.

- [ ] **Step 1: Run the focused regression set**

  Run the configuration, quicklook, three runner, architecture, and config-example unittest modules listed above with envInSAR. Expected: all PASS.

- [ ] **Step 2: Inspect repository and project diffs**

  Run `git diff --check`, confirm no unrelated repository paths changed, and list Gansu CFG/BMP/manifest changes.

- [ ] **Step 3: Commit remaining repository changes on `main`**

  Confirm `git status --short --branch` reports `main` and no uncommitted repository changes.

- [ ] **Step 4: Push once and verify**

  Push Geodesy-Analysis `main` to `origin`, then compare local `HEAD` with `origin/main`.
