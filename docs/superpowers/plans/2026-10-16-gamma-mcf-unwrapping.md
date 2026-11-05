# GAMMA MCF Unwrapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a GAMMA MCF unwrapping workflow that consumes one explicit filtering manifest, generates a validated mask/reference point, and atomically publishes unwrapped pair products.

**Architecture:** A stage-specific planner validates the filtering manifest and grid, a mask module reuses the repository's existing numerical mask functions, and a GAMMA MCF runner publishes one normalized unwrapping manifest. The output directory defaults from the current unwrapping method and never embeds the upstream filtering method.

**Tech Stack:** Python 3.10+, NumPy, Pillow optional mask I/O, GAMMA `mcf`, `unittest`, CFG/JSON manifests.

**Spec:** `docs/superpowers/specs/2026-10-16-filtering-unwrapping-design.md`

## Global Constraints

- Consume exactly one complete `filtering_manifest.json`; never infer the filtering method from a directory name.
- Support only GAMMA MCF in this plan; do not add SNAPHU or other unwrapping methods.
- Omitted `output_dir` maps from the filtering manifest's nearest `ANALYSIS` ancestor to sibling `UNWRAPPING/GAMMA_MCF`; an explicit project-confined path overrides it.
- Do not add a `run_id` or nest the upstream filtering method below `GAMMA_MCF`.
- Preserve the legacy MCF argv contract and make mask/reference provenance explicit.
- Keep quicklook rendering and atmospheric correction out of this plan.
- Run Python checks with `/home/yilun/miniconda3/envs/envInSAR/bin/python`.

## Review Focus

- A filtering manifest whose source pair/grid differs from its interferogram manifest must fail before mask creation; pinned in Task 1.
- An automatic reference point must be finite and inside the final mask, including ties; pinned in Task 2.
- A manual reference point outside the raster or final mask must be rejected; pinned in Task 2.
- Empty masks must fail with a clear error instead of invoking `mcf`; pinned in Task 2.
- An existing complete output from a different filtering manifest must report a conflict without automatic renaming; pinned in Task 3.

---

### Task 1: Add GAMMA MCF configuration and manifest planning

**Files:**
- Create: `src/geodesy_analysis/insar/unwrapping/__init__.py`
- Create: `src/geodesy_analysis/insar/unwrapping/gamma/__init__.py`
- Create: `src/geodesy_analysis/insar/unwrapping/gamma/mcf/__init__.py`
- Create: `src/geodesy_analysis/insar/unwrapping/gamma/mcf/models.py`
- Create: `src/geodesy_analysis/insar/unwrapping/gamma/mcf/config.py`
- Create: `src/geodesy_analysis/insar/unwrapping/gamma/mcf/plan.py`
- Create: `src/geodesy_analysis/insar/unwrapping/gamma/mcf/publication.py`
- Create: `tests/test_gamma_mcf_config.py`
- Create: `tests/test_gamma_mcf_plan.py`

**Interfaces:**
- Produces: `GammaMcfCase`, `FilteringManifest`, `UnwrappingPair`, and `GammaMcfPlan` frozen dataclasses.
- Produces: `load_gamma_mcf_config(path: Path) -> tuple[GammaMcfCase, ...]`.
- Produces: `build_gamma_mcf_plan(case: GammaMcfCase) -> GammaMcfPlan`.
- Produces: `unwrapping_input_signature(plan: GammaMcfPlan) -> str`.

- [ ] **Step 1: Write configuration tests**

Cover required filtering manifest, MCF mode `0..3`, automatic/manual reference modes, manual coordinates, mask thresholds, optional external mask, automatic output mapping from the filtering manifest's case-local `ANALYSIS` ancestor, required explicit output when that ancestor is absent, explicit output override, unknown keys, and project-boundary rejection.

- [ ] **Step 2: Run configuration tests and verify they fail**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_mcf_config -v`

Expected: FAIL because the loader is not defined.

- [ ] **Step 3: Implement models and strict configuration**

Use the repository's existing CFG pattern. Default `reference_mode=auto`; when output is omitted, locate the filtering manifest's nearest ancestor named `ANALYSIS` and append `UNWRAPPING/GAMMA_MCF`. Require explicit output when no such ancestor exists, and require both reference coordinates only for `manual`.

- [ ] **Step 4: Write manifest planning tests**

Assert pair order, normalized filtered-interferogram/coherence paths, dimensions, MLI/hgt inputs needed by mask generation, filtering method provenance, input digest, and failures for malformed schema/status, missing products, size mismatch, or inconsistent upstream interferogram identity.

- [ ] **Step 5: Implement `build_gamma_mcf_plan` and signature helpers**

Resolve all paths from the filtering manifest and its immediate interferogram manifest. Do not scan sibling folders. Hash the filtering manifest, mask inputs, reference settings, MCF mode, and pair identities.

- [ ] **Step 6: Run focused config and plan tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_mcf_config tests.test_gamma_mcf_plan -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/geodesy_analysis/insar/unwrapping tests/test_gamma_mcf_config.py tests/test_gamma_mcf_plan.py
git commit -m "Plan GAMMA MCF unwrapping"
```

### Task 2: Build the final mask and resolve the reference point

**Files:**
- Create: `src/geodesy_analysis/insar/unwrapping/gamma/mcf/mask.py`
- Modify: `src/geodesy_analysis/insar/masking.py`
- Create: `tests/test_gamma_mcf_mask.py`
- Modify: `tests/test_masking.py`

**Interfaces:**
- Consumes: `GammaMcfPlan` from Task 1 and the existing `coherence_mask`, amplitude-statistics, mask-combination, topographic-mask, and image-I/O functions.
- Produces: `build_unwrapping_mask(plan: GammaMcfPlan, output_dir: Path) -> MaskProducts`.
- Produces: `select_reference_point(mean_coherence: np.ndarray, mask: np.ndarray) -> tuple[int, int, float]` using zero-based `(range, azimuth, coherence)` internally.
- Produces: `resolve_reference_point(plan: GammaMcfPlan, mask_products: MaskProducts) -> ReferencePoint`.

- [ ] **Step 1: Write mask and reference tests**

Cover coherence-only mask, configured boolean combination, explicit external mask, grid mismatch, empty mask, deterministic first maximum in a tie, automatic masked maximum, valid manual point, and rejection of out-of-range or masked manual points.

- [ ] **Step 2: Run focused mask tests and verify they fail**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_masking tests.test_gamma_mcf_mask -v`

Expected: FAIL because the workflow-level mask functions are not defined.

- [ ] **Step 3: Implement workflow-level mask generation**

Reuse numerical functions from `insar.masking`; add only small general helpers there if they are independently useful. Publish a GAMMA-readable 8-bit BMP final mask plus binary/statistical mask metadata under staging `mask/`.

- [ ] **Step 4: Implement automatic and manual reference resolution**

Automatic mode selects the highest finite mean coherence inside the final mask. Manual CFG coordinates are converted to the exact GAMMA `mcf` coordinates only after bounds and mask checks. Record both zero-based internal and command coordinates.

- [ ] **Step 5: Run focused mask tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_masking tests.test_gamma_mcf_mask -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/geodesy_analysis/insar/masking.py src/geodesy_analysis/insar/unwrapping/gamma/mcf/mask.py tests/test_masking.py tests/test_gamma_mcf_mask.py
git commit -m "Build MCF masks and reference points"
```

### Task 3: Implement atomic GAMMA MCF execution and publication

**Files:**
- Create: `src/geodesy_analysis/insar/unwrapping/gamma/mcf/runner.py`
- Create: `tests/test_gamma_mcf_runner.py`

**Interfaces:**
- Consumes: `GammaMcfPlan`, `build_unwrapping_mask`, `resolve_reference_point`, `SubprocessCommandRunner`, and `unwrapping_input_signature`.
- Produces: `mcf_command(pair: UnwrappingPair, plan: GammaMcfPlan, mask: Path, reference: ReferencePoint, output: Path) -> tuple[str, ...]`.
- Produces: `run_gamma_mcf(plan: GammaMcfPlan, *, command_runner: object | None = None, progress_sink: Callable[[str], object] | None = None) -> GammaMcfRunSummary`.

- [ ] **Step 1: Write exact MCF command tests**

Assert the legacy order `<filtered-int> <filtered-coh> <mask> <unwrapped> <width> <mode> 0 0 - - 1 1 - <range-ref> <azimuth-ref>` for automatic and manual reference modes.

- [ ] **Step 2: Write publication and recovery tests**

Use a fake command runner to assert per-pair logs, product validation, normalized `pairs/<pair>/pair.tflt.filt.unw`, mask/reference provenance, schema-v1 manifest, progress, atomic failure behavior, matching-output skip, and differing-input conflict.

- [ ] **Step 3: Run runner tests and verify they fail**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_mcf_runner -v`

Expected: FAIL because runner functions are not defined.

- [ ] **Step 4: Implement command construction and atomic execution**

Generate the mask/reference once per batch, execute one `mcf` per manifest pair, require each unwrapped raster to match the expected float32 byte size, and preserve failure logs without publishing partial results.

- [ ] **Step 5: Publish provenance and `unwrapping_manifest.json`**

Record immediate `filtering_manifest`, its digest and method, MCF mode, mask products/statistics, reference selection, pair products, command logs, and `status=complete`.

- [ ] **Step 6: Run focused runner tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_mcf_runner -v`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/geodesy_analysis/insar/unwrapping/gamma/mcf/runner.py tests/test_gamma_mcf_runner.py
git commit -m "Run GAMMA MCF unwrapping"
```

### Task 4: Add the public CLI, Gansu configuration, and one real-pair check

**Files:**
- Create: `src/geodesy_analysis/insar/unwrapping/gamma/mcf/cli.py`
- Create: `tests/test_gamma_mcf_cli.py`
- Create: `config_examples/gamma_mcf_unwrapping.cfg`
- Modify: `pyproject.toml`
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/workflows/gamma_insar.md`
- Create outside repository: `Gansu_Jishishan_LT1/S1/ASCENDING_128/config/analysis/gamma_mcf_unwrapping.cfg`

**Interfaces:**
- Consumes: config, plan, mask, and runner interfaces from Tasks 1–3.
- Produces: installed command `geodesy-analysis-gamma-mcf --config PATH --case NAME [--dry-run]`.

- [ ] **Step 1: Write CLI tests**

Assert case selection, all-case execution, dry-run without mask/output creation, unknown case exit code, resolved default output, and concise summary.

- [ ] **Step 2: Run CLI tests and verify they fail**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_gamma_mcf_cli -v`

Expected: FAIL because the CLI is not defined.

- [ ] **Step 3: Implement CLI, package entry point, example CFG, and workflow docs**

Follow existing Analysis CLI conventions. Document automatic/manual reference coordinates, MCF modes, optional output override, output roles, logs, restart behavior, and completion checks.

- [ ] **Step 4: Add the Gansu MCF CFG**

Point it at the completed Gansu NL-InSAR `filtering_manifest.json`, omit `output_dir` to exercise `ANALYSIS/UNWRAPPING/GAMMA_MCF`, and use the migrated radar-height and MLI assets through manifests rather than duplicate paths.

- [ ] **Step 5: Run only focused unwrapping tests**

Run: `/home/yilun/miniconda3/envs/envInSAR/bin/python -m unittest tests.test_masking tests.test_gamma_mcf_config tests.test_gamma_mcf_plan tests.test_gamma_mcf_mask tests.test_gamma_mcf_runner tests.test_gamma_mcf_cli -v`

Expected: PASS.

- [ ] **Step 6: Run Gansu dry-run and one real MCF pair**

Use `envInSAR`; check only manifest status, selected reference location, pair count, declared unwrapped-file existence/size, and finite-value count. Do not run atmospheric correction, visualization, preprocessing, or unrelated repository suites.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml README.md config_examples docs src/geodesy_analysis/insar/unwrapping tests/test_gamma_mcf_cli.py
git commit -m "Expose GAMMA MCF unwrapping"
```
