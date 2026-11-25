# Explicit Execution and Repository Cleanup Design

**Date:** 2026-11-20

## Goal

When a user invokes a formal processing command, the command performs the
requested work. Existing outputs, matching input signatures, or matching
parameters must not silently turn that invocation into a skip and must not
block a changed run. Validation errors are reserved for conditions that can
make the requested result invalid: missing inputs, invalid parameters,
incompatible grids, malformed manifests, unsafe paths, or failed external
commands.

## Execution contract

1. `--dry-run` validates and reports a plan without creating products.
2. A formal run always executes its scientific command chain.
3. Input signatures remain in manifests as provenance only.
4. A run writes to a unique sibling staging path.
5. Products are validated before publication.
6. Publication replaces the previous result transactionally. If publication
   fails, the previous result is restored.
7. Failed calculations never replace the previous valid result; diagnostic
   logs are retained separately.
8. The code never creates implicit `main`, `test`, or `run_id` directories.
   Users may choose another `output_dir` when they want to retain two runs.

Acquisition commands may reuse a verified downloaded source object because
the remote object itself is the requested result. This is idempotent download
behavior, not parameter-signature result reuse. Processing and conversion
workflows always recompute when formally invoked.

## Repository cleanup

### Geodesy-Preprocessing

- Complete the `config_examples/download/` and
  `config_examples/preprocess/` migration and remove numbered example paths.
- Track the TOPS burst preparation module and its tests so a clean clone is
  importable.
- Keep the current SAOCOM, Sentinel-1, NISAR, progress, and GAMMA compatibility
  fixes as independently testable changes.
- Remove processing-stage skip/conflict gates that prevent an explicit rerun;
  publish replacements through staging and rollback.

### Geodesy-Analysis

- Remove `ReuseState` decisions from formal runners. Existing manifests may be
  read as upstream inputs, but not as permission to skip or reject a run.
- Apply transactional replacement consistently to baseline, interferogram,
  filtering, unwrapping, detrending, atmosphere, DInSAR, stacking, and GAMMA
  mb outputs, including companion figure/geocoding directories.
- Retain signatures and parameter values in provenance so two runs can be
  compared after publication.
- Complete every CFG header with the exact command, dry-run form, path
  contract, overwrite behavior, and parameter comments.

### Geodesy-DataAdapter

- Retain the existing fast, atomic-overwrite behavior.
- Finish documentation alignment for `data2canonical/` and `data2defsour/`.

### Geodesy-Visualization

- Retain the completed Figure/Panel/Layer workflow migration and direct
  overwrite behavior.
- Remove numbered `config/4visualization/` references from repository-facing
  documentation without moving the current Gansu project.
- Do not restore a public list/batch option.

## Verification

- Behavior changes are developed with failing tests first.
- Focused tests run in `envInSAR` for Preprocessing and Analysis and in
  `envPlot` for Visualization.
- Each repository receives one final full test run after focused tests pass.
- The Gansu project and legacy GAMMA outputs remain untouched in this phase.
