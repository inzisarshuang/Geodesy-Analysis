# Explicit Execution and Repository Cleanup Implementation Plan

**Spec:** `../specs/2026-11-20-explicit-execution-and-cleanup-design.md`

## Global constraints

- Work in the existing repositories because they contain user-approved,
  uncommitted refactor work; do not discard or overwrite unrelated changes.
- Use `envInSAR` for Preprocessing, Analysis, and DataAdapter tests and
  `envPlot` for Visualization tests.
- Do not modify `Gansu_Jishishan_LT1` or legacy scientific result directories.
- Do not push remote branches as part of this plan.

## Task 1: Close Preprocessing repository integrity

1. Add a failing clean-tree/package inventory test proving every imported
   workflow module and packaged CFG exists.
2. Complete the new `download/` and `preprocess/` example paths, TOPS burst
   module tracking, and documentation references.
3. Run the focused Preprocessing tests and then the complete suite.

## Task 2: Make Analysis baseline and interferogram explicit runs

1. Change tests so a second valid invocation executes commands and replaces
   the prior output, while a failed replacement preserves it.
2. Verify the tests fail because the runners currently skip or reject.
3. Implement staging, backup, replacement, and rollback without reuse gates.
4. Run focused runner and CLI tests.

## Task 3: Apply explicit execution to remaining Analysis workflows

1. Add or update runner tests for filtering, MCF unwrapping, quadratic
   detrending, atmosphere, DInSAR, stacking, and GAMMA mb.
2. Verify each representative test fails on the old skip/conflict behavior.
3. Remove reuse gates and publish validated replacements transactionally.
4. Run all Analysis tests.

## Task 4: Finish CFG and repository documentation cleanup

1. Add exact command/dry-run/path/replacement headers and parameter comments
   to Analysis CFG files.
2. Finish DataAdapter boundary documentation.
3. Replace repository-facing numbered Visualization config paths with
   `config/visualization/`; do not move project data.
4. Verify config parsers and documentation contract tests.

## Task 5: Final review and handoff

1. Run `git diff --check` and repository status checks.
2. Run each repository's full test suite once in its designated environment.
3. Review the final diffs for accidental project-data changes, stale numbered
   paths, skip/conflict behavior, and untracked imported modules.
4. Report commits that are ready, but do not push without a separate explicit
   request.
