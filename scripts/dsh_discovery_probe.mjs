// Loaded by the installed Desktop Electron executable in Node mode, after the guard.
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { join, relative, resolve, sep } from 'node:path';
import { pathToFileURL } from 'node:url';

const [runtime, root] = process.argv.slice(2);
assert(globalThis.__ohStoryDshGuard, 'offline guard must be preloaded');
assert.equal(resolve(root), resolve(process.env.OH_STORY_DSH_PROBE_ROOT));
const load = name => import(pathToFileURL(join(runtime, 'node_modules', '@deepseek-ai', name, 'lib/index.js')).href);
const { Context } = await load('cordis');
const { SkillRegistry, renderSkillContent } = await load('dsh-skill');
const filesystem = await load('dsh-skill-filesystem');
const { SystemPrompt } = await load('dsh-system-prompt');
const { ToolRuntime } = await load('dsh-tools');
const skillToolPlugin = await load('dsh-tool-skill');
const { SessionProjectionRegistry } = await load('dsh-session-projection');
const { AgentPresetRegistry } = await load('dsh-agent-preset-registry');
const homes = await load('dsh-home-paths');
const names = ['story-deslop', 'story-long-write'];
const cwd = join(root, 'workspace');
const shared = join(root, 'home', '.agents', 'skills');
const bundled = join(root, 'bundled-skills');
const custom = join(root, 'custom-skills');
const sha256 = value => createHash('sha256').update(value).digest('hex');
function isolated(path) {
  const child = relative(root, path);
  assert(child !== '..' && !child.startsWith('..' + sep) && !child.includes(':'));
}
async function context(config = {}) {
  const ctx = new Context();
  await ctx.plugin(SkillRegistry);
  await ctx.plugin(filesystem, { watch: false, ...config });
  return ctx;
}
async function catalog(ctx, expectedSource) {
  const observed = await ctx.skills.snapshot({ cwd });
  assert.equal(observed.complete, true);
  assert.deepEqual(observed.skills.map(s => s.name), names);
  for (const skill of observed.skills) {
    isolated(skill.path);
    assert.equal(skill.source, expectedSource);
    assert.equal(skill.invocation.userInvocable, true);
    assert.equal(skill.invocation.modelInvocable, true);
  }
  return observed.skills.map(({ name, source, provider, path }) => ({ name, source, provider, path }));
}
async function copySkills(target) {
  await fs.mkdir(target, { recursive: true });
  for (const name of names) await fs.cp(join(shared, name), join(target, name), { recursive: true });
}

const report = { engine: { node: process.versions.node, electron: process.versions.electron }, cases: [] };
assert.equal(homes.resolveDshHome(), join(root, 'home', '.dsh'));
assert.equal(homes.resolveAgentsHome(), join(root, 'home', '.agents'));
let ctx = await context();
try {
  const inspector = new filesystem.FileSystemSkillProvider(ctx, {
    signal: new AbortController().signal, invalidate() {},
  }, { watch: false });
  report.scan_roots = await inspector.roots(cwd);
  report.scan_roots.forEach(r => isolated(r.path));
  await inspector.dispose();
  report.cases.push({ case: 'shared-user-home-discovery', skills: await catalog(ctx, 'user-agents') });
  await ctx.plugin(SystemPrompt);
  await ctx.plugin(ToolRuntime);
  // Apply the installed skill tool directly: no Agent/Session, profile, LLM or
  // working-directory service is created. The tool's agent-less read path uses
  // the same registry and returns the actual model-facing instruction payload.
  skillToolPlugin.apply(ctx);
  const tool = ctx.tools.get('skill');
  assert(tool);
  report.loaded = [];
  for (const name of names) {
    const definition = await ctx.skills.get(name, { cwd });
    const result = await tool.execute({ name }, { signal: new AbortController().signal });
    assert.equal(result.content, definition.content);
    assert(result.content.length > 5000);
    assert(renderSkillContent(definition).includes('<skill_content'));
    const fallback = name === 'story-long-write'
      ? result.content.includes('报告 fallback 并 solo/direct 执行')
      : result.content.includes('由主会话直接改');
    assert(fallback, 'fallback contract must be present in the actually loaded instructions');
    report.loaded.push({ name, resourceBase: result.resourceBase, body_characters: result.content.length,
      body_sha256: sha256(result.content), raw_skill_sha256: sha256(await fs.readFile(definition.path)),
      fallback_contract_loaded: fallback });
  }
  await assert.rejects(tool.execute({ name: 'story-import' }, { signal: new AbortController().signal }), /unknown/);
  report.cases.push({ case: 'unbundled-skill-rejected', name: 'story-import' });
  assert.equal(ctx.get('llm'), undefined);
  assert.equal(ctx.get('agents'), undefined);
  assert.equal(ctx.get('subagents'), undefined);
  assert.equal(ctx.tools.get('oh_story_role'), undefined);
  assert.equal(ctx.tools.get('invoke_subagent'), undefined);
  await ctx.plugin(SessionProjectionRegistry);
  // Read-only registry construction; no Loader/preset mount is performed and
  // resolve/readDocument on an unknown id fail before an Agent can be created.
  const presets = new AgentPresetRegistry(ctx, { default: 'unregistered', selectedDefault: { get() {} } });
  assert.deepEqual(await presets.list(), []);
  const errors = [];
  for (const id of ['narrative-writer', 'story-architect', 'story-explorer', 'story-continuity', 'story-researcher']) {
    try { await presets.resolve(id); assert.fail('professional preset unexpectedly available'); }
    catch (error) {
      assert.match(error.message, /Unknown agent preset/);
      assert.equal(error.code, 'agent-preset/not-found');
      errors.push({ id, code: error.code, message: error.message });
    }
  }
  report.professional_agents = { roster: [], lookup_errors: errors, llm_service_present: false,
    subagent_service_present: false, automatic_model_fallback: 'not tested: no model or agent execution',
    interpretation: 'DSH rejects unknown presets; solo/direct is a loaded Skill instruction, not automatic runtime routing.' };
} finally { await ctx.fiber.dispose(); }

await copySkills(bundled);
ctx = await context({ bundledSkillDir: bundled });
try {
  report.cases.push({ case: 'user-agents-over-bundled', skills: await catalog(ctx, 'user-agents') });
  for (const name of names) ctx.skills.register({ name, description: 'Offline precedence fixture', source: 'runtime', content: 'Fixture runtime skill.' });
  const skills = await ctx.skills.list({ cwd });
  assert(skills.every(s => s.source === 'runtime'));
  report.cases.push({ case: 'runtime-over-user-agents', sources: skills.map(s => ({ name: s.name, source: s.source })) });
} finally { await ctx.fiber.dispose(); }

await copySkills(custom);
ctx = await context({ customSkillDirs: [custom] });
try { report.cases.push({ case: 'custom-over-user-agents', skills: await catalog(ctx, 'custom') }); }
finally { await ctx.fiber.dispose(); }

await copySkills(join(root, 'home', '.dsh', 'skills'));
ctx = await context();
try { report.cases.push({ case: 'user-dsh-over-user-agents', skills: await catalog(ctx, 'user-dsh') }); }
finally { await ctx.fiber.dispose(); }

await copySkills(join(cwd, '.agents', 'skills'));
ctx = await context();
try { report.cases.push({ case: 'project-agents-over-user-roots', skills: await catalog(ctx, 'project-agents') }); }
finally { await ctx.fiber.dispose(); }

await copySkills(join(cwd, '.dsh', 'skills'));
ctx = await context();
try { report.cases.push({ case: 'project-dsh-over-project-agents', skills: await catalog(ctx, 'project-dsh') }); }
finally { await ctx.fiber.dispose(); }

ctx = await context({ includeDefaultRoots: false, customSkillDirs: [shared] });
try {
  report.cases.push({ case: 'explicit-custom-roots-only', skills: await catalog(ctx, 'custom') });
} finally { await ctx.fiber.dispose(); }
report.guard = globalThis.__ohStoryDshGuard;
assert(Object.values(report.guard).every(value => value === 0), 'probe attempted a forbidden operation');
report.status = 'passed';
console.log(JSON.stringify(report, null, 2));
