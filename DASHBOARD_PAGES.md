# Public dashboard

Public URL: https://richettigr-star.github.io/Stock-Signals-Bot/

`index.html` is a read-only dashboard. Each refresh resolves the current `main`
commit, then reads the portfolio, monitor, watchdog, signal state, outbox, cadence
and daily health JSON files at that immutable commit. It refreshes every two
minutes independently of Pages deployments and never sends Telegram messages or
changes trading state. The public GitHub API can be rate-limited; fetch failures
are displayed explicitly and previous data retains its original timestamps.

In repository **Settings → Pages → Build and deployment**, select **GitHub
Actions**. `.github/workflows/pages.yml` deploys only `index.html` and `.nojekyll`,
on dashboard changes or manual dispatch. No trading secrets are passed to it.
The dashboard reads JSON already public in this repository; this is not a private
account portal. To validate a deployment, open the public URL, verify that the
data-load banner succeeds and compare the displayed commit and heartbeat with
`main`. A working HTML response alone does not establish fresh bot data.

The previous URL returned HTTP 404 because Pages was disabled (no publishing
branch selected) and the repository had no `index.html` or deployment workflow.
`build_dashboard.py` generated only `dashboard.md`; that remains the saved
repository snapshot. No scanner, exit, stop, position or notification logic is
changed by the public dashboard.
