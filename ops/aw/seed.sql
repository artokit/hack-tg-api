\set ON_ERROR_STOP on

BEGIN;

INSERT INTO public.aw_mock_samples (id, recorded_at, series, value)
SELECT
    'demo:' || series || ':' || hour_index,
    date_trunc('hour', now()) - (239 - hour_index) * interval '1 hour',
    series,
    10 + ((hour_index * 17 + series_index * 23) % 91)
FROM generate_series(0, 239) AS hours(hour_index)
CROSS JOIN (VALUES ('demo_a', 0), ('demo_b', 1)) AS series_data(series, series_index)
ON CONFLICT (id) DO UPDATE SET
    recorded_at = EXCLUDED.recorded_at,
    series = EXCLUDED.series,
    value = EXCLUDED.value;

COMMIT;

SELECT count(*) AS mock_rows, min(recorded_at), max(recorded_at) FROM aw_mock.samples;
