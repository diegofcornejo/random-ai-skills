---
description: "Group pending changes into semantic commits and push the current branch."
---

Load the `random-commit` skill explicitly by ID with the skill tool and follow its instructions exactly.

Optional context for commit messages: $ARGUMENTS

If the `random-commit` skill is not available, stop and tell the user to install it:
`npx skills add https://github.com/diegofcornejo/skills --skill random-commit`
