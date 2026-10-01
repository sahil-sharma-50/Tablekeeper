# Opt-in Stage 4 multi-day demonstration

The recommended quickstart from the repository root is `docker compose up --build -d`, then open `http://localhost:8104/`. The root [README](../../README.md#ready-to-use-local-demo) includes the manager credentials and stop commands. Compose loads the fixture after the service is healthy, and preserves any existing state. The instructions below cover manual fixture loading.

This stage uses its own labeled fixture at `stage-4/demo/multi-day-demo.json`. It is not loaded automatically. The sample restaurant, **Nobu (Demo)**, is open every day from 17:00 to 22:00 Europe/Berlin time, with three single tables and one declared pair. The name and opening hours are demonstration data, not a connection to a real restaurant. No reservations are seeded. Sign up normally for visitor flows; signing up does not grant manager access.

The fixture includes one manager explicitly authorized for this restaurant. Use these public, local-demo credentials on the normal sign-in page:

| Field | Value |
| --- | --- |
| Email | `manager@tablekeeper.example` |
| Password | `TablekeeperDemo2026!` |

After signing in, choose **Nobu (Demo)** and open **Service recovery**. Create a guest reservation first to demonstrate a seating move.

From the repository root, build and run this stage in a disposable, loopback-only container. Port 8106 was free when this runbook was prepared; if it is occupied, substitute another free host port in both commands and the URL.

```powershell
docker build -t tablekeeper .\stage-4
docker run --rm -d --name tablekeeper-demo -p 127.0.0.1:8106:8080 tablekeeper
$body = Get-Content -Raw .\stage-4\demo\multi-day-demo.json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8106/_test/reset -ContentType 'application/json' -Body $body
```

Open `http://localhost:8106/`. The reset replaces all data in this disposable container only; never send it to a service containing data you need to keep. Stop it with `docker stop tablekeeper-demo`; Docker removes it automatically.

If your fresh local container is already running on port 8104, load the same fixture there instead. Run from the repository root in another PowerShell terminal:

```powershell
$body = Get-Content -Raw .\stage-4\demo\multi-day-demo.json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8104/_test/reset -ContentType 'application/json' -Body $body
```

This reset deletes existing users, sessions and reservations. Use it only for disposable demo state. Refresh the page afterwards; the fixture must be loaded again after a container restart.
