CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS pois (
    poi_id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    source_poi_id TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    district TEXT,
    business_area TEXT,
    address TEXT,
    location GEOGRAPHY(POINT, 4326),
    rating REAL NOT NULL DEFAULT 0,
    price_per_person INTEGER NOT NULL DEFAULT 0,
    queue_wait_min INTEGER NOT NULL DEFAULT 0,
    is_open BOOLEAN NOT NULL DEFAULT TRUE,
    raw JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (source, source_poi_id)
);

CREATE INDEX IF NOT EXISTS pois_location_gix ON pois USING GIST (location);
CREATE INDEX IF NOT EXISTS pois_category_district_idx ON pois (category, district);
CREATE INDEX IF NOT EXISTS pois_open_rating_idx ON pois (is_open, rating DESC);
