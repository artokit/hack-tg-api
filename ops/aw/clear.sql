\set ON_ERROR_STOP on

DELETE FROM public.aw_mock_samples;

SELECT count(*) AS remaining_mock_rows FROM aw_mock.samples;
