'use strict';

// Preloaded before any installed DSH module. This is a regression guard for a
// model-free probe, not a security sandbox for arbitrary hostile native code.
const fs = require('node:fs');
const path = require('node:path');
const { fileURLToPath } = require('node:url');
const { syncBuiltinESMExports } = require('node:module');

const root = process.env.OH_STORY_DSH_PROBE_ROOT;
if (!root || !path.isAbsolute(root)) throw new Error('Explicit isolated probe root required');
const normalize = value => path.resolve(value).toLowerCase();
const inside = (value, parent) => value === parent || value.startsWith(parent + path.sep);
const privateRoots = JSON.parse(process.env.OH_STORY_DSH_PRIVATE_ROOTS || '[]').map(normalize);
const isolated = normalize(root);
const evidence = { network_attempts: 0, subprocess_attempts: 0, protected_read_attempts: 0, outside_write_attempts: 0 };
globalThis.__ohStoryDshGuard = evidence;

function filename(value) {
  if (value instanceof URL) return fileURLToPath(value);
  if (Buffer.isBuffer(value)) return value.toString();
  return typeof value === 'string' ? value : undefined;
}
function check(value, write) {
  const name = filename(value);
  if (name === undefined) return; // stdout/stderr and already-open file descriptors
  const full = normalize(name);
  if (privateRoots.some(parent => inside(full, parent))) {
    evidence.protected_read_attempts++;
    throw new Error('Probe blocked access to a real user configuration/Skills directory');
  }
  if (write && !inside(full, isolated)) {
    evidence.outside_write_attempts++;
    throw new Error('Probe blocked a filesystem write outside its isolated root');
  }
}
function wrap(object, key, indices, write = false) {
  const original = object[key];
  if (typeof original !== 'function') return;
  object[key] = function (...args) {
    for (const index of indices) check(args[index], write);
    return Reflect.apply(original, this, args);
  };
  Object.assign(object[key], original);
  if (typeof original.native === 'function') {
    object[key].native = function (...args) {
      for (const index of indices) check(args[index], write);
      return Reflect.apply(original.native, this, args);
    };
  }
}
for (const api of [fs, fs.promises]) {
  for (const name of ['readFile', 'readdir', 'opendir', 'stat', 'lstat', 'realpath', 'access', 'readlink', 'exists', 'watch', 'watchFile']) {
    wrap(api, name, [0]);
    wrap(api, name + 'Sync', [0]);
  }
  for (const name of ['writeFile', 'appendFile', 'mkdir', 'mkdtemp', 'rm', 'rmdir', 'unlink', 'truncate', 'chmod', 'utimes']) {
    wrap(api, name, [0], true);
    wrap(api, name + 'Sync', [0], true);
  }
  for (const name of ['rename', 'copyFile', 'cp', 'link', 'symlink']) {
    wrap(api, name, [0, 1], true);
    wrap(api, name + 'Sync', [0, 1], true);
  }
  for (const key of ['open', 'openSync']) {
    const original = api[key];
    if (!original) continue;
    api[key] = function (name, flags, ...rest) {
      const write = typeof flags === 'number'
        ? Boolean(flags & (fs.constants.O_WRONLY | fs.constants.O_RDWR | fs.constants.O_CREAT | fs.constants.O_TRUNC | fs.constants.O_APPEND))
        : /[wa+]/.test(String(flags));
      check(name, write);
      return Reflect.apply(original, this, [name, flags, ...rest]);
    };
  }
}
wrap(fs, 'createReadStream', [0]);
wrap(fs, 'createWriteStream', [0], true);
function forbid(object, keys, counter) {
  for (const key of keys) if (typeof object[key] === 'function') {
    object[key] = function () {
      evidence[counter]++;
      throw new Error(`Offline probe forbids ${counter}`);
    };
  }
}
for (const module of ['node:http', 'node:https']) forbid(require(module), ['request', 'get'], 'network_attempts');
forbid(require('node:net'), ['connect', 'createConnection', 'createServer'], 'network_attempts');
forbid(require('node:net').Socket.prototype, ['connect'], 'network_attempts');
forbid(require('node:tls'), ['connect', 'createServer'], 'network_attempts');
forbid(require('node:dgram'), ['createSocket'], 'network_attempts');
forbid(require('node:child_process'), ['spawn', 'spawnSync', 'exec', 'execSync', 'execFile', 'execFileSync', 'fork'], 'subprocess_attempts');
globalThis.fetch = () => { evidence.network_attempts++; throw new Error('Offline probe forbids fetch'); };
syncBuiltinESMExports();
if (process.env.OH_STORY_DSH_GUARD_REPORT) {
  process.on('exit', () => fs.writeFileSync(process.env.OH_STORY_DSH_GUARD_REPORT, JSON.stringify(evidence)));
}
