# Opt-in multi-day demonstration

`multi-day-demo.json` is a labeled demonstration fixture. It is not loaded automatically and has no seeded users or reservations. Visitors can create their own account through the normal sign-up page.

Run it in a disposable container on port 8103 from the repository root:

```powershell
docker build -t tablekeeper-stage-2 .\stage-2
docker run --rm -d --name tablekeeper-demo -p 8103:8080 tablekeeper-stage-2
$body = Get-Content -Raw .\stage-2\demo\multi-day-demo.json
Invoke-RestMethod -Method Post -Uri http://localhost:8103/_test/reset -ContentType 'application/json' -Body $body
```

The reset replaces all state in that container. Never send it to the shared preview or QA service. Open `http://localhost:8103/`, choose a date, and sign up normally. The restaurant is open 17:00 to 22:00 every weekday in Europe/Berlin time; it has three single tables and one declared two-table combination. Stop the disposable container with `docker stop tablekeeper-demo`.
