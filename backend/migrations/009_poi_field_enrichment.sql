-- Preserve source truth while promoting available POI metadata into queryable columns.
-- Unknown commercial fields remain explicitly marked as unknown instead of fabricated.
ALTER TABLE pois ADD COLUMN IF NOT EXISTS opening_hours TEXT;
ALTER TABLE pois ADD COLUMN IF NOT EXISTS recommended_duration_min INTEGER;
ALTER TABLE pois ADD COLUMN IF NOT EXISTS field_provenance JSONB NOT NULL DEFAULT '{}'::jsonb;

WITH normalized AS (
    SELECT
        poi_id,
        COALESCE(NULLIF(BTRIM(district), ''), NULLIF(BTRIM(raw->>'district'), ''), NULLIF(BTRIM(raw #>> '{osm_tags,addr:district}'), ''), NULLIF(BTRIM(raw #>> '{osm_tags,is_in:district}'), '')) AS district_value,
        COALESCE(NULLIF(BTRIM(business_area), ''), NULLIF(BTRIM(raw->>'business_area'), ''), NULLIF(BTRIM(raw #>> '{osm_tags,addr:subdistrict}'), ''), NULLIF(BTRIM(raw #>> '{osm_tags,addr:neighbourhood}'), ''), NULLIF(BTRIM(raw #>> '{osm_tags,addr:place}'), '')) AS business_area_value,
        COALESCE(
            NULLIF(BTRIM(address), ''),
            NULLIF(BTRIM(raw->>'address'), ''),
            NULLIF(BTRIM(raw #>> '{osm_tags,addr:full}'), ''),
            NULLIF(CONCAT_WS('', raw #>> '{osm_tags,addr:street}', raw #>> '{osm_tags,addr:housenumber}'), '')
        ) AS address_value,
        COALESCE(NULLIF(BTRIM(opening_hours), ''), NULLIF(BTRIM(raw->>'opening_hours'), ''), NULLIF(BTRIM(raw->>'osm_opening_hours'), ''), NULLIF(BTRIM(raw #>> '{osm_tags,opening_hours}'), '')) AS opening_hours_value,
        CASE
            WHEN COALESCE(raw->>'recommended_duration_min', '') ~ '^[0-9]+$'
                THEN (raw->>'recommended_duration_min')::INTEGER
            ELSE recommended_duration_min
        END AS duration_value
    FROM pois
)
UPDATE pois AS poi
SET
    district = normalized.district_value,
    business_area = normalized.business_area_value,
    address = normalized.address_value,
    opening_hours = normalized.opening_hours_value,
    recommended_duration_min = normalized.duration_value,
    field_provenance = jsonb_strip_nulls(jsonb_build_object(
        'district', CASE WHEN normalized.district_value IS NULL THEN 'unknown' ELSE 'source' END,
        'business_area', CASE WHEN normalized.business_area_value IS NULL THEN 'unknown' ELSE 'source' END,
        'address', CASE WHEN normalized.address_value IS NULL THEN 'unknown' ELSE 'source' END,
        'opening_hours', CASE WHEN normalized.opening_hours_value IS NULL THEN 'unknown' ELSE 'source' END,
        'recommended_duration_min', CASE WHEN normalized.duration_value IS NULL THEN 'unknown' ELSE 'source' END,
        'rating', CASE WHEN poi.rating = 0 THEN 'unknown' ELSE 'source' END,
        'price_per_person', CASE WHEN poi.price_per_person = 0 THEN 'unknown' ELSE 'source' END,
        'queue_wait_min', CASE WHEN poi.queue_wait_min = 0 THEN 'unknown_or_zero' ELSE 'source' END
    )),
    updated_at = NOW()
FROM normalized
WHERE poi.poi_id = normalized.poi_id;

CREATE INDEX IF NOT EXISTS pois_district_category_opening_idx
    ON pois (district, category) WHERE opening_hours IS NOT NULL;
