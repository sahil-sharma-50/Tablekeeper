# Stage 2

Build the browser application and API together from this directory (Docker required):

```sh
docker build -t tablekeeper-stage-2 . && docker run --rm --name tablekeeper-stage-2 -p 8102:8102 -e PORT=8102 tablekeeper-stage-2
```

Open `http://localhost:8102/` for reservations, `/signup` or `/login` for account access, and
`/lookup` to find a reservation. The API and compiled browser assets share this origin. The
service listens on `0.0.0.0`; `PORT` defaults to `8080`. Stop it with Ctrl+C. Dependencies and
timezone data are installed into the image at build time; the running service does not need
outbound network access.
