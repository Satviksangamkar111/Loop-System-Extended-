// Preload for the confined ABAP-to-JavaScript run: `node --require <this file>`.
//
// What it does: replaces the outbound-networking entry points (net, tls, dns,
// dns/promises, http, https, http2, dgram, global fetch / WebSocket /
// XMLHttpRequest when present) with functions that throw
// "network is blocked in the ABAP sandbox ...".
//
// What it is NOT: a security boundary. It runs inside the same process as the
// model-written code, so code that reaches the untouched internals (for example
// process.binding, a native addon, or a re-import of a saved reference) can
// still open a socket. Node's --permission model does not cover the network,
// so this is defence in depth only. The real boundary is an OS firewall rule
// or a container with no network: see docs/sap/SANDBOX_NETWORK.md.
//
// Kept CommonJS and dependency-free so `--require` can load it before any user
// code. It does not touch fs, timers, console or stdio, so local work still runs.
"use strict";

const MSG = "network is blocked in the ABAP sandbox (outbound networking is disabled for model-written code)";

function blocked() {
  return new Error(MSG);
}

function throwNow() {
  throw blocked();
}

function rejectNow() {
  return Promise.reject(blocked());
}

function replace(obj, name, fn) {
  if (!obj) return;
  try {
    Object.defineProperty(obj, name, { value: fn, writable: false, configurable: false });
  } catch (_e) {
    try {
      obj[name] = fn;
    } catch (_e2) {
      /* non-writable on this runtime: nothing more we can do here */
    }
  }
}

function safeRequire(name) {
  try {
    return require(name);
  } catch (_e) {
    return undefined;
  }
}

const net = safeRequire("net");
if (net) {
  replace(net, "connect", throwNow);
  replace(net, "createConnection", throwNow);
  if (net.Socket && net.Socket.prototype) replace(net.Socket.prototype, "connect", throwNow);
}

const tls = safeRequire("tls");
if (tls) {
  replace(tls, "connect", throwNow);
}

// dns.promises is the same object as require("dns/promises") (a lazy getter),
// so one pass over each covers both spellings.
const DNS_QUERIES = ["lookup", "resolve", "resolve4", "resolve6", "resolveAny", "resolveCname",
  "resolveMx", "resolveNaptr", "resolveNs", "resolvePtr", "resolveSoa", "resolveSrv",
  "resolveTxt", "reverse"];

const dns = safeRequire("dns");
if (dns) {
  for (const name of DNS_QUERIES) replace(dns, name, throwNow);
  replace(dns, "getServers", throwNow);
  replace(dns, "setServers", throwNow);
}

const dnsPromises = safeRequire("dns/promises");
if (dnsPromises) {
  for (const name of DNS_QUERIES) replace(dnsPromises, name, rejectNow);
}

for (const modName of ["http", "https", "http2"]) {
  const mod = safeRequire(modName);
  if (!mod) continue;
  replace(mod, "request", throwNow);
  replace(mod, "get", throwNow);
  if (modName === "http2") replace(mod, "connect", throwNow);
}

const dgram = safeRequire("dgram");
if (dgram) {
  replace(dgram, "createSocket", throwNow);
}

if (typeof globalThis.fetch === "function") replace(globalThis, "fetch", rejectNow);
if (typeof globalThis.WebSocket === "function") replace(globalThis, "WebSocket", throwNow);
if (typeof globalThis.XMLHttpRequest === "function") replace(globalThis, "XMLHttpRequest", throwNow);
