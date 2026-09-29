// Extracts one version's section from CHANGELOG.md for use as release notes.
//
//   node scripts/release-notes.mjs <version> [output-file]
//
// Prints to stdout when no output file is given. Falls back to a generic line
// if the changelog has no section for that version.

import { existsSync, readFileSync, writeFileSync } from "node:fs";

const [version, outFile] = process.argv.slice(2);
if (!version) {
  console.error("usage: node scripts/release-notes.mjs <version> [output-file]");
  process.exit(1);
}

const changelog = new URL("../CHANGELOG.md", import.meta.url);
let notes = "";

if (existsSync(changelog)) {
  const lines = readFileSync(changelog, "utf8").split(/\r?\n/);
  const start = lines.findIndex((line) => line.trim() === `## ${version}`);
  if (start !== -1) {
    const rest = lines.slice(start + 1);
    const end = rest.findIndex((line) => /^## /.test(line));
    notes = (end === -1 ? rest : rest.slice(0, end)).join("\n").trim();
  }
}

if (!notes) notes = `Release v${version}.`;
notes += "\n";

if (outFile) {
  writeFileSync(outFile, notes);
  console.log(`Wrote release notes for ${version} to ${outFile}`);
} else {
  process.stdout.write(notes);
}
