# Vercel deployment

Live demo: **https://tablekeeper-band.vercel.app/**.

This separate hosting adapter serves the Stage 4 frontend and API without editing the judged stage snapshots. It replaces the existing state-storage functions with shared Postgres transactions. Accounts, sessions and reservations survive function restarts and deployments. One locked state row serializes writes for this small demo; larger deployments should partition storage. Public evaluation reset, import and export routes are removed.

The database receives [Nobu (Demo)](../stage-4/demo/multi-day-demo.json) only when first initialized. Existing state is preserved. The restaurant opens every day from 17:00 to 22:00 in Europe/Berlin. Guests create their own accounts. The seeded manager can sign in with **manager@tablekeeper.example** and **TablekeeperDemo2026!**. This is a shared public demo with sample data and public manager access, not a real restaurant service.

## Deploy

From the repository root, authenticate the Vercel CLI and link the existing project:

```sh
npx --yes vercel link --project tablekeeper-band
```

Connect a Postgres database through the project's Vercel Storage settings or marketplace integration. Set `DATABASE_URL` for Production to the provider's connection string with TLS enabled. The adapter requires this variable; it does not fall back to temporary storage. For Neon, the CLI can create and connect the free database after the account owner accepts the provider terms:

```sh
npx --yes vercel integration add neon --name tablekeeper-band-db --plan free_v3 --metadata region=iad1 --metadata auth=false --environment production --no-env-pull
npx --yes vercel deploy --prod
```

[vercel.json](../vercel.json) selects FastAPI, [pyproject.toml](../pyproject.toml) pins Python 3.12 and dependencies, and [build.py](build.py) builds the existing frontend. [.vercelignore](../.vercelignore) excludes earlier snapshots and local/private materials from deployment uploads. Keep `.vercel/` metadata and database credentials out of Git.

## Verify

```sh
python vercel/check.py https://tablekeeper-band.vercel.app
```

The check verifies pages, assets, the seeded manager, authorization, availability, guest signup, booking, idempotent retry, lookup, cancellation and blocked evaluation controls. It leaves a random test account and a cancelled reservation in the shared demo.

For storage regression checks, provide `TABLEKEEPER_TEST_DATABASE_URL` pointing to a **disposable local Postgres database**, install the dependencies listed in the root pyproject, then run:

```sh
python vercel/test_store.py
```

This checks concurrent writes, rollback and persistence in a fresh process. Use the unchanged Docker snapshots and their documented runbooks for challenge evaluation. Hosting checks do not replace the organizers' hidden tests.
