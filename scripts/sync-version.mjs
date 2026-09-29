// Keeps the Python project version in step with package.json.
//
// Changesets only knows how to bump package.json, so after `changeset version`
// this script copies the new version into pyproject.toml (which the PyInstaller
// spec reads), into openvchange/__init__.py (which the app shows), and into the
// root entries of package-lock.json.
//
//   node scripts/sync-version.mjs          write the version
//   node scripts/sync-version.mjs --check  exit 1 if anything is out of step

import { existsSync, readFileSync, writeFileSync } from "node:fs";

const root = new URL("../", import.meta.url);
const check = process.argv.includes("--check");

const read = (name) => readFileSync(new URL(name, root), "utf8");
const write = (name, text) => writeFileSync(new URL(name, root), text);

const version = JSON.parse(read("package.json")).version;
const stale = [];

// --- pyproject.toml ---------------------------------------------------------
// Rewrite the `version = "..."` line inside [tool.poetry] (or [project]),
// leaving every other byte, including line endings, untouched.
{
  // Splitting on a captured newline keeps the separators at the odd indexes.
  const parts = read("pyproject.toml").split(/(\r?\n)/);
  let section = "";
  let found = false;

  for (let i = 0; i < parts.length && !found; i += 2) {
    const header = parts[i].match(/^\s*\[([^\[\]]+)\]\s*(#.*)?$/);
    if (header) {
      section = header[1].trim();
      continue;
    }
    if (section !== "tool.poetry" && section !== "project") continue;

    const line = parts[i].match(/^(\s*version\s*=\s*)(["'])(.*?)\2(.*)$/);
    if (!line) continue;

    found = true;
    if (line[3] !== version) {
      stale.push(`pyproject.toml has ${line[3]}`);
      parts[i] = `${line[1]}${line[2]}${version}${line[2]}${line[4]}`;
      if (!check) write("pyproject.toml", parts.join(""));
    }
  }

  if (!found) {
    console.error("sync-version: no version field found in pyproject.toml");
    process.exit(1);
  }
}

// --- openvchange/__init__.py ------------------------------------------------
// The version the app shows about itself.
{
  const name = "openvchange/__init__.py";
  const text = read(name);
  const line = text.match(/^(__version__\s*=\s*)(["'])(.*?)\2/m);
  if (!line) {
    console.error(`sync-version: no __version__ found in ${name}`);
    process.exit(1);
  }
  if (line[3] !== version) {
    stale.push(`${name} has ${line[3]}`);
    if (!check) write(name, text.replace(line[0], `${line[1]}${line[2]}${version}${line[2]}`));
  }
}

// --- package-lock.json ------------------------------------------------------
if (existsSync(new URL("package-lock.json", root))) {
  const lock = JSON.parse(read("package-lock.json"));
  const rootPackage = lock.packages?.[""];

  if (lock.version !== version || (rootPackage && rootPackage.version !== version)) {
    stale.push(`package-lock.json has ${lock.version}`);
    lock.version = version;
    if (rootPackage) rootPackage.version = version;
    if (!check) write("package-lock.json", `${JSON.stringify(lock, null, 2)}\n`);
  }
}

if (check && stale.length > 0) {
  console.error(`Version mismatch: package.json has ${version}, but:`);
  for (const item of stale) console.error(`  - ${item}`);
  console.error("Run `node scripts/sync-version.mjs` to fix.");
  process.exit(1);
}

if (check) {
  console.log(`Versions are in step at ${version}`);
} else if (stale.length > 0) {
  console.log(`Synced version ${version} (was: ${stale.join("; ")})`);
} else {
  console.log(`Version ${version} already in step`);
}
