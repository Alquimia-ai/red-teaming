// Conventional Commits with a mandatory scope. Releases are cut per app, so a commit without a
// scope is a change nobody can attribute to a release. The enum lists every workspace member plus
// the cross-cutting scopes; `tests/guards/test_scopes.py` fails when a member is missing here.
module.exports = {
  extends: ["@commitlint/config-conventional"],
  rules: {
    "scope-enum": [
      2,
      "always",
      [
        // apps
        "api",
        "runner",
        "cli",
        // packages
        "contracts",
        "settings",
        "secrets",
        "store",
        "dispatch",
        "delivery",
        "knowledge",
        "judges",
        "target",
        "catalogue",
        "probes",
        "engine",
        // cross-cutting
        "deploy",
        "docs",
        "ci",
        "deps",
        "repo",
        "skills",
      ],
    ],
    "scope-empty": [2, "never"],
    "header-max-length": [2, "always", 100],
  },
  ignores: [
    // release-please's own commits on main carry the branch as scope
    (commit) => /^chore\(main\): release/.test(commit),
  ],
};
