# Deployment (demo)

A deliberately small, cheap setup for demonstrations. It is **not** a production architecture; see "Going to production" at the end.

```
Browser ──https──▶ Vercel (Next.js dashboard)
                      │  /api/*  is proxied server-side
                      ▼
              https://<ip>.sslip.io        AWS EC2 (one t3.micro, ap-south-1)
                      │                      ┌───────────────────────────────┐
                      └──────────────────────▶ Caddy (HTTPS, auto-certificate)│
                                             │   └▶ FastAPI (Docker)          │
                                             │        └▶ PostgreSQL 18 (Docker, volume)
                                             └───────────────────────────────┘
```

| Part | Where | Notes |
|---|---|---|
| Dashboard | Vercel project `salon-voice` → https://salon-voice.vercel.app | Demo mode (`NEXT_PUBLIC_API_MOCKS=true`): every page works on sample data |
| API | EC2 `salon-demo` behind Caddy → `https://<ip>.sslip.io` (docs at `/docs`) | Real backend: sign-in, business, locations, team |
| Database | PostgreSQL in a Docker volume on the same server | Single copy, no backups |
| Code | GitHub `Tehman700/salon-voice-booking` | The server pulls from here |

`<ip>.sslip.io` is a free DNS name that resolves to the IP written in it (`43-205-17-140.sslip.io` → `43.205.17.140`), which lets Caddy get a real Let's Encrypt certificate without owning a domain. The browser never talks to the API directly: Vercel proxies `/api/*` to it, so the login cookie stays first-party.

## Cost (ap-south-1, on-demand)
| Item | ≈ per month |
|---|---|
| t3.micro (1 GB) | $7.6 |
| Public IPv4 address (Elastic IP) | $3.7 |
| 12 GB gp3 disk | $1.1 |
| Vercel (Hobby) | $0 |
| **Total** | **≈ $12** (about $0.40/day) |

`bash infra/ec2/teardown.sh --yes` removes everything and stops the charges. If AWS has capacity, `INSTANCE_TYPE=t4g.micro` is about $1.5/month cheaper.

## Everyday commands
All from the repo root, with the AWS CLI logged in. Nothing needs SSH: the server is managed through AWS Systems Manager.

| Task | Command |
|---|---|
| Create the server | `GIT_REF=main bash infra/ec2/provision.sh --wait` |
| Deploy new code | `GIT_REF=main bash infra/ec2/update.sh` |
| Run something on the server | `bash infra/ec2/remote.sh 'docker logs salon-api-1 --tail 50'` |
| Container status | `bash infra/ec2/remote.sh 'docker ps'` |
| Bootstrap log | `bash infra/ec2/remote.sh 'tail -n 50 /var/log/salon-bootstrap.log'` |
| Create demo logins | `bash infra/ec2/remote.sh "cd /opt/salon/repo/infra/ec2 && docker compose --env-file /opt/salon/.env exec -T -e SEED_PASSWORD='<10+ chars>' api python -m app.scripts.seed --allow-remote"` |
| Deploy the dashboard | `cd frontend && vercel deploy --prod --yes` |
| Switch dashboard to the real backend | `vercel env add NEXT_PUBLIC_API_MOCKS production --force` (value `false`), then redeploy |
| Remove the AWS demo | `bash infra/ec2/teardown.sh --yes` |

Secrets (`DB_PASSWORD`, `JWT_SECRET`) are generated on the server at first boot into `/opt/salon/.env` and never leave it or enter the repo. `ENVIRONMENT=staging` makes the API require a strong `JWT_SECRET` and use `Secure` cookies.

## What the demo does not have
- **No backups.** The database lives on one disk. Re-seed if you lose it.
- **One server, no failover.** A reboot interrupts the API for about a minute; containers restart by themselves.
- **No login rate limiting** yet, and the API docs are public. Fine for a demo, not for real customers.
- **No email.** Invitation links are shown in the Team page until the notifications module exists.
- **The dashboard is in demo mode** on Vercel because services, staff, bookings, customers and calls don't exist in the backend yet. As each backend module lands, the matching dashboard pages switch to real data, and `NEXT_PUBLIC_API_MOCKS` can be turned off.

## Going to production
Keep the same code; change the hosting: ECS Fargate (or a larger EC2 behind a load balancer) for the API, RDS PostgreSQL with automated backups, a real domain with ACM/CloudFront, Secrets Manager, GitHub OIDC deploys instead of the `update.sh` script, and rate limiting in front of `/auth/*`.
