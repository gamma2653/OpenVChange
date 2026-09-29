# Changesets

This folder is managed by [Changesets](https://changesets.dev), which tracks
the OpenVChange version and changelog.

## Adding a changeset

Any change that users would notice should ship with a changeset. Run:

```bash
npm run changeset
```

Pick a bump type and write a one-line summary. That creates a Markdown file in
this folder; commit it along with your change. You can also write the file by
hand, using any file name ending in `.md`:

```markdown
---
"openvchange": patch
---

Fix crackle when the pitch slider crosses zero.
```

Use `patch` for fixes, `minor` for new features, and `major` for breaking
changes.

## What happens next

The release workflow collects pending changesets into a version pull request.
Merging that pull request bumps the version, updates `CHANGELOG.md`, and
publishes a GitHub release with the Windows executable attached.
