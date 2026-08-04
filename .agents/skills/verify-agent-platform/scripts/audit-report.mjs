#!/usr/bin/env node

import { readFile } from "node:fs/promises";

const headers = [
  "Capability",
  "Implementation",
  "Command",
  "Expected",
  "Observed",
  "Status",
  "Remaining gap",
];

function cells(line) {
  if (!line.trim().startsWith("|") || !line.trim().endsWith("|")) return null;
  return line.trim().slice(1, -1).split("|").map((cell) => cell.trim());
}

export function audit(markdown) {
  const lines = markdown.split(/\r?\n/);
  const header = lines.findIndex((line) =>
    JSON.stringify(cells(line)) === JSON.stringify(headers)
  );
  if (header < 0) return ["missing verification table"];

  const errors = [];
  const seen = new Set();
  const rows = [];
  for (let index = header + 2; index < lines.length; index += 1) {
    const row = cells(lines[index]);
    if (!row) break;
    rows.push(row);
    if (row.length !== headers.length) {
      errors.push(`line ${index + 1}: expected ${headers.length} columns`);
      continue;
    }
    const [id, implementation, command, expected, observed, status, gap] = row;
    if (!/^CAP-\d{3,}$/.test(id)) errors.push(`line ${index + 1}: invalid capability ID`);
    if (seen.has(id)) errors.push(`line ${index + 1}: duplicate ${id}`);
    seen.add(id);
    for (const [label, value] of [
      ["implementation", implementation],
      ["command", command],
      ["expected", expected],
      ["observed", observed],
    ]) {
      if (!value || /(?:<[^>]+>|\b(?:todo|tbd)\b)/i.test(value)) {
        errors.push(`${id || `line ${index + 1}`}: incomplete ${label}`);
      }
    }
    if (!["PASS", "FAIL", "SKIPPED"].includes(status)) {
      errors.push(`${id}: invalid status`);
    }
    if (status === "PASS" && gap.toLowerCase() !== "none") {
      errors.push(`${id}: PASS has a remaining gap`);
    }
  }
  if (rows.length === 0) errors.push("verification table has no capability rows");
  return [...new Set(errors)];
}

export async function main(argv = process.argv.slice(2)) {
  if (argv.length !== 1) {
    process.stderr.write("Usage: audit-report.mjs <report.md>\n");
    return 2;
  }
  const errors = audit(await readFile(argv[0], "utf8"));
  if (errors.length) {
    for (const error of errors) process.stderr.write(`verification audit: ${error}\n`);
    return 1;
  }
  process.stdout.write("Verification report structure passed\n");
  return 0;
}

if (process.argv[1]?.endsWith("audit-report.mjs")) {
  process.exitCode = await main();
}
