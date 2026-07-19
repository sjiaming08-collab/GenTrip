# OSM Data Acquisition

GenTrip can use OpenStreetMap as a broad, local POI source. The download step
does not modify PostGIS or the checked-in fixture dataset.

Download the Shanghai Geofabrik extract:

```powershell
python scripts/download_osm_extract.py
```

The extract is written to `data/osm/shanghai-latest.osm.pbf`, with a manifest
next to it containing the source URL, MD5 checksum, timestamp, coordinate
reference system, and license notice. The script validates the official
Geofabrik MD5 checksum before it atomically replaces the final file.

To replace a corrupted or obsolete local file deliberately:

```powershell
python scripts/download_osm_extract.py --force
```

For a different Geofabrik extract, provide the directory and region prefix:

```powershell
python scripts/download_osm_extract.py --base-url https://download.geofabrik.de/asia/china --region zhejiang
```

OSM coordinates are WGS84 (`EPSG:4326`). Keep this as the PostGIS storage
coordinate system, and convert only at interfaces that require GCJ-02. Before
presenting or redistributing data, show the required OpenStreetMap attribution
and review the ODbL obligations for the intended use.

The next, separate implementation step is to import selected OSM tags into a
normalized POI table. That importer is now available and never overwrites
`backend/fixtures/pois.json`:

```powershell
$env:DATABASE_URL = 'postgresql://gentrip:gentrip@localhost:5432/gentrip'
$env:REDIS_URL = 'redis://localhost:6379/0'
D:\conda3\envs\GenTrip\python.exe backend/scripts/import_osm_pbf.py
```

Use `--dry-run` to inspect the qualifying POI count before writing PostGIS.
Only named POIs in supported categories are imported. Their source is `osm`,
and no rating, price, queue, or live opening claim is inferred from OSM tags.
