# Triage Labels

The skills speak in terms of five canonical triage roles. This file maps those
roles to the actual label strings used in this repo's issue tracker.

| Canonical role    | Label in our tracker | Meaning                                   |
| ----------------- | -------------------- | ----------------------------------------- |
| `needs-triage`    | `needs-triage`       | Maintainer needs to evaluate this issue   |
| `needs-info`      | `needs-info`         | Waiting on reporter for more information  |
| `ready-for-agent` | `ready`              | Fully specified, ready for an AFK agent   |
| `ready-for-human` | `planned`            | Maintainer will implement this personally |
| `wontfix`         | `wontfix`            | Will not be actioned                      |

When a skill mentions a role (e.g. "apply the AFK-ready triage label"), use the
corresponding label string from this table.

Note: this is a public repo with no external contributors yet. When
contributors arrive, consider remapping `ready-for-human` to GitHub's stock
`help wanted` label for its contributor-discovery mechanics.
