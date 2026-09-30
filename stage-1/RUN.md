# Stage 1

Build and start the API from this directory (Docker required):

```sh
docker build -t tablekeeper-stage-1 . && docker run --rm --name tablekeeper-stage-1 -p 8102:8102 -e PORT=8102 tablekeeper-stage-1
```

The service listens on `0.0.0.0`; `PORT` defaults to `8080`. For the command above, check
`http://localhost:8102/health`. Stop it with Ctrl+C. Dependencies and timezone data are
installed into the image at build time; the running service does not need outbound network
access.
