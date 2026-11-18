# ABAP sandbox: network containment

The ABAP unit tests run model-written ABAP, transpiled to JavaScript, under
`node --permission` (read-only, no child processes, no write outside the run
folder). Node's permission model does **not** cover network access, so there are
two layers for the network:

1. **Preload guard (defence in depth, not a boundary).**
   `scripts/source/net_guard_preload.js` is loaded with `node --require` in the
   transpile, test-run and lint steps (`scripts/source/abap_transpile_run.py`).
   It replaces `net`, `tls`, `dns`, `dns/promises`, `http`, `https`, `http2`,
   `dgram`, and the global `fetch`, `WebSocket` and `XMLHttpRequest` with
   functions that throw `network is blocked in the ABAP sandbox ...`.
   The guard runs in the same process as the model-written code, so it can be
   bypassed by code that reaches the untouched internals. Treat it as a tripwire
   that stops the ordinary routes, nothing more.

2. **The real boundary: an OS firewall rule or a container with no network.**
   Use one of these on the machine that runs the loops.

## Option A: Windows Firewall rule for node.exe (run as Administrator)

Find the node.exe that the runner uses:

```
where node
```

Add an outbound block for that program (replace the path with the output above):

```
netsh advfirewall firewall add rule name="ABAP sandbox node block" dir=out action=block program="C:\Program Files\nodejs\node.exe" enable=yes
```

Verify the rule exists:

```
netsh advfirewall firewall show rule name="ABAP sandbox node block"
```

Check that outbound TCP from node.exe fails (run it, then expect a timeout or
permission error instead of `connected`):

```
node -e "require('net').connect(443,'example.com').on('connect',()=>console.log('connected')).on('error',e=>console.log(e.code))"
```

Remove the rule:

```
netsh advfirewall firewall delete rule name="ABAP sandbox node block"
```

Caveats:

- The rule blocks every node.exe on the machine. If anything else on this
  machine uses Node for model calls or other network work, it is blocked too.
  Check that first, or use a dedicated node.exe copy for the sandbox.
- Name resolution for a per-program rule is done by the Windows DNS client
  service, not by node.exe, so the rule may not stop a lookup. The rule stops
  the connection itself, which is what matters.
- This was written, not run against a live machine. Verify the check command
  above on the target machine before relying on it.

## Option B: container with no network

```
docker run --rm --network none -v "<work folder>:/work" -w /work <node image> node --permission ...
```

`--network none` removes every network interface except loopback, which is the
strongest option when Docker is available.

## Limits

- The preload is not a boundary. A determined attacker who controls the
  generated code may find another route (native addons, `process.binding`, and
  so on). Node's permission model does not add a network switch in this version.
- The preload only throws inside the node process it is loaded into. A child
  process would not get it, but child processes are already refused by
  `--permission`.
