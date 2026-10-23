# Real OpenClaw Gateway transport regression

`tests/integration/test_openclaw_gateway_http.py` starts the locked OpenClaw
Gateway, loads the built Aivan plugin and calls an actual Aivan Core process.
It does not replace Gateway execution with the SDK registration harness.

Prepare the normal locked plugin dependencies and build, using the Node version
supported by `integrations/openclaw-aivan-plugin/package.json`. In an isolated
development environment, run:

```sh
export RUN_OPENCLAW_GATEWAY_INTEGRATION_TESTS=1
export AIVAN_OPENCLAW_NODE="$(command -v node)"
python -m pytest -q tests/integration/test_openclaw_gateway_http.py
```

`AIVAN_OPENCLAW_PLUGIN_DIR` may select an already built, revision-verified plugin
directory with its locked `node_modules`; otherwise the repository plugin is
used. `AIVAN_OPENCLAW_PYTHON` may select the prepared application Python runtime.
The Core source always comes from the test checkout. The peer SDK version must
match the committed npm lock. No runtime or dependency is downloaded by the test.

The test creates private Gateway state/configuration and an ephemeral bearer
credential. It binds only loopback on unused ports, configures no IM/email
accounts or model turn, and allows only the health/dashboard tools. It verifies
unauthenticated denial, actual plugin-to-Core health, unavailable approval tools
and an unreachable-Core error after Core shutdown. Both processes are stopped
and the credential-bearing configuration is removed, including on test failure.
Do not use a live channel account or an existing Gateway state directory.

This is a bounded transport regression. Its temporary local Core control SQLite
file does not demonstrate provider migration, CTYun MySQL, business persistence,
real IM/email delivery, model inference, approval execution or public UI. Those
results must be reported separately. Without the explicit run flag, pytest
reports this optional test as skipped, not as live integration passed.
