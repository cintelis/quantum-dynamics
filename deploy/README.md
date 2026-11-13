# Hosting the dashboard publicly

This is how https://qtumdynamics.com runs: one container on a Linux VM, reached through a Cloudflare Tunnel.

```
browser ──https──> Cloudflare (your domain) ── tunnel ──> cloudflared ──> dashboard
                                               (the VM dials out; no open port)
```

Nothing is published on the VM. The dashboard container has no internet access, runs read-only as a non-root
user, and is capped at 4 CPUs and 6 GB (`QUANTUM_CPUS`, `QUANTUM_MEMORY` in `.env`).

## Who can use it

- `/` is a public landing page with a sign-up form (name, email, organisation, role, interest).
- Signing up sets a signed cookie (`QUANTUM_SESSION_KEY`) and opens every other page. There are no passwords and
  emails are not verified, so a person is identified by that cookie, never by the email they typed.
- Each sign-up is one line in `output/runs/.registrations.jsonl` (in the `runs` volume).
- `/admin` lists the sign-ups and downloads them as CSV after you enter `QUANTUM_ADMIN_KEY`. An admin can delete
  any saved run; everyone else only the runs they made.
- Sign-ups are limited to 5 an hour per address, with a hidden field that catches simple bots.

## 1. Cloudflare

1. Zero Trust → Networks → Tunnels → Create a tunnel → Cloudflared. Copy the token (the string after `--token`);
   don't run the install command, the container does that. Keep the token private.
2. Public hostname: your domain, service `HTTP`, URL `dashboard:8765`. Add `www` the same way if you want it.
3. Turn on SSL/TLS → Edge Certificates → Always Use HTTPS (the sign-in cookie is HTTPS-only).

## 2. The VM

```bash
cd ~/quantum/deploy
cp .env.example .env && nano .env            # tunnel token, two random keys, your domain
docker compose up -d --build                 # first build ~5-10 min (installs CUDA-Q)
docker compose ps                            # dashboard "healthy", cloudflared "running"
docker compose exec dashboard python seed_runs.py   # example runs for the Load list (~30 s)
```

From Windows, `.\deploy\push.ps1 -Up` copies this folder to the VM, rebuilds and restarts (set `QUANTUM_VM` and
`QUANTUM_VM_KEY` in `.env`). Saved runs and sign-ups are kept across rebuilds (volume `quantum_runs`).

## Good to know

- One simulation at a time for everybody; a second Run shows "Another run is in progress".
- Everyone signed in sees everyone's saved runs, with the name they signed up with.
- CPU only. The GPU backend reports itself unavailable; big GPU runs use `aws/gpu.ps1`.
- Logs: `docker compose logs -f dashboard` · stop: `docker compose down` (runs kept) · remove runs too: `down -v`.
- Back up the volume now and then: `docker run --rm -v quantum_runs:/r -v $PWD:/b alpine tar czf /b/runs.tgz -C /r .`
