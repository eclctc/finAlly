# Review: changes since `819a6f7` (`Adding initial workflow`)

## Findings

### [P1] Grant pull request write access before enabling inline comments

`.github/workflows/claude-code-review.yml` now invokes the review plugin with `--comment` and allows `mcp__github_inline_comment__create_inline_comment`, but this job only grants `pull-requests: read` and `issues: read` (lines 22–26). The `GITHUB_TOKEN` therefore cannot create the requested inline review comments. Grant the minimum write permission required by the comment API, typically `pull-requests: write`; pull requests from forks may still receive a read-only token under GitHub's fork security rules.

Reference: [claude-code-review.yml](../.github/workflows/claude-code-review.yml#L22).

## Other changes

The change in `.github/workflows/claude.yml` only updates an example in a comment from `Bash(gh pr:*)` to `Bash(gh pr *)`; it does not affect workflow behavior.
