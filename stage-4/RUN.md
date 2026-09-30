# Stage 4

Build and run the API and browser app together from this directory (Docker required):

```sh
docker build -t tablekeeper-stage-4 . && docker run --rm --name tablekeeper-stage-4 -p 8104:8104 -e PORT=8104 tablekeeper-stage-4
```

Open `http://localhost:8104/` to book, `http://localhost:8104/lookup` to view a reservation,
and use the Service recovery navigation when signed in as a restaurant manager. API requests
and compiled assets share this origin. The service binds to `0.0.0.0`; `PORT` defaults to
`8080`. Runtime dependencies and timezone data are bundled in the image; it needs no outbound
network access. Stop it with Ctrl+C.
