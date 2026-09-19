## MODIFIED Requirements

### Requirement: Preserved output contract

When generation succeeds, the tree SHALL appear under
`twrp-device-tree/device/<manufacturer>/<codename>/` in the output directory,
the build-from-source wiki README SHALL be fetched into that folder, and all
`.git` directories inside the generated tree SHALL be removed before the dump
finishes.

#### Scenario: Tree lands in the expected location
- **WHEN** generation succeeds and the device is identified
- **THEN** the tree is found at `twrp-device-tree/device/<manufacturer>/<codename>/`

#### Scenario: Wiki README fetched and repositories stripped
- **WHEN** generation succeeds
- **THEN** the wiki README is present in the tree folder and no `.git`
  directory remains under `twrp-device-tree/`