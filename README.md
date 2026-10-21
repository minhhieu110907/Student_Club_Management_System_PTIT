# Student Club Management System

Day 01 infrastructure foundation for the SCMS local Docker demo.

## Run the stack

Copy the example configuration before the first run:

```powershell
Copy-Item .env.example .env
```

Replace the example passwords in `.env`, then run:

```powershell
docker compose config
docker compose up -d --build
docker compose ps
```

Open <http://localhost:8080>. The API health endpoint is available through
Nginx at <http://localhost:8080/api/v1/health>.

## Verification

```powershell
Invoke-WebRequest http://localhost:8080/ -UseBasicParsing
Invoke-RestMethod http://localhost:8080/api/v1/health
docker compose ps
docker volume inspect scms_mysql_data
```

The named MySQL volume survives container recreation. To verify persistence,
create known data, recreate the containers without adding `--volumes` (or `-v`)
to `docker compose down`, and confirm the data still exists. Schema migrations
and seed data are intentionally deferred to Day 02.

Stop the stack without deleting database data:

```powershell
docker compose down
```
