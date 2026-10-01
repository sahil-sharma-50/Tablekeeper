# Stage 4

Build and run the API and browser app together from this directory (Docker required):

```sh
docker build -t tablekeeper . && docker run --rm --name tablekeeper -p 127.0.0.1:8104:8104 -e PORT=8104 tablekeeper
```

Open `http://localhost:8104/` to book, `http://localhost:8104/lookup` to view a reservation,
and use the Service recovery navigation when signed in as a restaurant manager. API requests
and compiled assets share this origin. The service binds to `0.0.0.0`; `PORT` defaults to
`8080`. The `0.0.0.0` URL in Uvicorn's log is the container's listen address; use `localhost`
or `127.0.0.1` in your browser. For a PowerShell launch that also displays `localhost` in the
log, see the root [README.md](../README.md#start-the-final-product). Runtime dependencies
and timezone data are bundled in the image; it needs no outbound network access.
Stop it with Ctrl+C or `docker stop tablekeeper`.
