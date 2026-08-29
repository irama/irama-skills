#!/usr/bin/env node
// Strip any "caveman-shrink" MCP server entries from ~/.claude.json on session start.
// Reason: caveman installer re-adds it as `npx -y caveman-shrink` with no upstream
// command, which crashes immediately and surfaces as "Unhandled case: [object Object]"
// in the Claude Code VSCode extension.

const fs = require("fs");
const path = require("path");
const os = require("os");

const CLAUDE_JSON = path.join(os.homedir(), ".claude.json");

try {
  if (!fs.existsSync(CLAUDE_JSON)) process.exit(0);
  const raw = fs.readFileSync(CLAUDE_JSON, "utf8");
  const data = JSON.parse(raw);

  let removed = 0;

  if (data.mcpServers && Object.prototype.hasOwnProperty.call(data.mcpServers, "caveman-shrink")) {
    delete data.mcpServers["caveman-shrink"];
    removed++;
  }

  const projects = data.projects || {};
  for (const key of Object.keys(projects)) {
    const proj = projects[key];
    if (proj && proj.mcpServers && Object.prototype.hasOwnProperty.call(proj.mcpServers, "caveman-shrink")) {
      delete proj.mcpServers["caveman-shrink"];
      removed++;
    }
  }

  if (removed > 0) {
    const bak = `${CLAUDE_JSON}.bak.${Date.now()}`;
    fs.writeFileSync(bak, raw);
    fs.writeFileSync(CLAUDE_JSON, JSON.stringify(data, null, 2));
    console.error(`[strip-caveman-shrink] removed ${removed} entries; backup at ${bak}`);
  }
} catch (err) {
  console.error(`[strip-caveman-shrink] error: ${err.message}`);
}

process.exit(0);
