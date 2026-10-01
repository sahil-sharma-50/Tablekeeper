# Opt-in Stage 3 multi-day demonstration

This stage uses its own labeled fixture at `stage-3/demo/multi-day-demo.json`. It is not loaded automatically. It contains no users or reservations; the demo restaurant is open every day from 17:00 to 22:00 Europe/Berlin time, with three single tables and one declared pair. Sign up normally for visitor flows. No manager account is seeded, and signing up does not grant manager access.

From the repository root, build and run this stage in a disposable, loopback-only container. Port 8105 was free when this runbook was prepared; if it is occupied, substitute another free host port in both commands and the URL.

```powershell
docker build -t tablekeeper-stage-3-demo .\stage-3
docker run --rm -d --name tablekeeper-stage-3-demo -p 127.0.0.1:8105:8080 tablekeeper-stage-3-demo
$body = Get-Content -Raw .\stage-3\demo\multi-day-demo.json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8105/_test/reset -ContentType 'application/json' -Body $body
```

Open `http://localhost:8105/`. The reset replaces all data in this disposable container only; never send it to a shared preview or QA service. Stop it with `docker stop tablekeeper-stage-3-demo`; Docker removes it automatically.
