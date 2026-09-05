# Running the demo in GitHub Codespaces

A guided walkthrough for reviewing the fuel planner without installing
anything. A Codespace is a disposable development machine that GitHub runs in
the browser; everything below happens inside it and disappears when you delete
it.

Roughly 10 minutes, most of it waiting for the first build.

---

## What you will end up with

Four containers, started by one command:

| Service | What it is |
|---|---|
| `app` | The planner itself, on port 8000 |
| `db` | PostgreSQL, holding operations, predictions and the catalogs |
| `mlflow` | The model store, on port 5000 |
| `seed` | Runs once, fills the empty database, exits |

The database arrives populated: locations, the fleet, a sample of historical
journeys, and a trained model already promoted to active. You can make a
prediction as soon as the page loads.

---

## Step 1 — Open the Codespace

On the repository page: **Code ▾ → Codespaces → New with options…**

Set **Branch** to `develop`, leave the rest as offered, and click **Create
codespace**.

The branch matters. `main` does not yet have the demo setup.

## Step 2 — Wait for the setup to finish

The Codespace opens a terminal and runs its own setup first: it writes a `.env`
file with a generated database password, then builds the container images.
That build takes about five minutes the first time and is not repeated.

You will know it is done when the terminal prints:

```
Ready. Start the stack with:

    docker compose up
```

## Step 3 — Start the stack

In the Codespace terminal:

```bash
docker compose up
```

Leave this running — it is the application's log. The first start migrates the
database and seeds it, so give it a minute. You are looking for two lines:

```
seed-1  |   1110 lokasi dan 23 kendaraan dimuat.
seed-1  |   Model MDL-… dipromosikan menjadi aktif.
```

After those, the seed container exits. That is expected: it has one job.

## Step 4 — Open the application

A notification offers to open port 8000 in your browser. If you miss it, use
the **Ports** tab at the bottom of the Codespace window and click the globe
icon next to port 8000.

Sign in with:

- **Username:** `admin`
- **Password:** `angber-demo-2026`

These are demo credentials for a disposable machine, written into the
Codespace's own `.env`. They are not in the repository and are not used
anywhere else.

## Step 5 — Make a prediction

Go to **Buat Prediksi** in the sidebar and fill in one operation:

1. **Kendaraan** — pick `Prime Mover — Truck`. The list is the real fleet, 23
   vehicles across Crane, Truck, Forklift and Vacuum Truck.
2. **Aktivitas** — pick `Angkut dan lifting`. A **Jam lifting** field appears;
   enter `3.5`.
3. **Rute & pemberhentian** — pick `POOL LIMAU` as the departure point and
   `KM-001` as the stop. The map above draws the route between them. Use
   **+ Tambah pemberhentian** to add more stops, and drag the ⠿ handle to
   reorder them.
4. **Sumber jarak** — choose `Input manual` and enter `64` km. (See *Known
   limits* below for why the automatic route distance is unavailable in the
   demo.)
5. **Simpan operasi harian**, then **Buat estimasi kebutuhan BBM**.

You should see roughly **51 L estimated** and **56 L recommended allocation** —
the recommendation adds a 5 L safety margin.

Worth trying next: the same journey with `0` extra lifting hours, or at half
the distance, to see which inputs move the number and by how much.

---

## What is already in the database

| | Count | Where it comes from |
|---|---|---|
| Locations | 1110 | The `Data Lokasi` sheet, with coordinates |
| Vehicles | 23 | The `Dim_Kendaraan` sheet, with the alias map from `Peta_Nama_Sumber` |
| Historical journeys | 9 | A small sample shipped with the application |
| Trained model | 1, active | Trained from those 9 journeys during seeding |

---

## Known limits of this demo

These are properties of the sample data, not faults to report:

- **Road distances are unavailable.** The route map draws, but the kilometre
  figure needs a Google Maps API key, which is not shipped. Choose `Input
  manual` and type a distance. To enable it, put a key in `.env` as
  `FUEL_PREDICTOR_GOOGLE_MAPS_API_KEY=…` and restart with `docker compose up -d`.
- **The vehicle does not change the estimate.** The nine sample journeys do not
  record which vehicle drove them, so the model has no vehicle signal to learn
  from. Real history with the vehicle column would change this — that is
  precisely what Level 1 in the [data roadmap](prd/prediction-data-roadmap.md)
  is about.
- **The uncertainty range is always ±1 L.** It is the model's training
  residual, not a measure of how unusual your inputs are, so it stays narrow
  even for a journey far longer than anything in the sample.
- **Nine journeys is not a trained system.** Accuracy figures from this demo
  mean nothing. What it shows is the path working end to end.

---

## Stopping, restarting, resetting

```bash
# Stop, keeping the data
docker compose down

# Start again — the seed step sees the existing model and does nothing
docker compose up

# Wipe everything and seed from scratch
docker compose down -v && docker compose up
```

Deleting the Codespace itself (github.com/codespaces) removes all of it.

---

## If something goes wrong

**The page does not load.** Check the Ports tab: port 8000 must be listed. If
`docker compose up` is still printing startup lines, wait for
`Application startup complete`.

**`POSTGRES_PASSWORD` error on start.** The `.env` file is missing. Re-run
`bash .devcontainer/setup.sh`.

**The seed container reports an error.** Read it with
`docker compose logs seed`. To try again:
`docker compose run --rm seed python -m fuel_predictor seed-demo --force`.

**Sign-in is rejected.** Confirm the credentials in `.env` match what you are
typing; the account is created from those values the first time the app starts.
If you changed them afterwards, run `docker compose down -v && docker compose up`.
