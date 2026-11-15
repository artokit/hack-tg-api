\if :{?apply}
\else
    \set apply false
\endif
\if :{?retained}
\else
    \set retained '[]'
\endif

BEGIN;

WITH historical_jobs AS (
    SELECT DISTINCT ON (coalesce(file_id, id))
        coalesce(file_id, id) AS id,
        created_at AS accepted_at,
        nullif(format, 'url') AS format,
        size_bytes
    FROM rag_jobs
    WHERE import_event_id IS NULL
      AND created_at < :'before'::timestamptz
      AND status <> 'skipped'
    ORDER BY coalesce(file_id, id), created_at, id
), retained_originals AS (
    SELECT DISTINCT ON (original.id)
        original.id,
        original.accepted_at,
        original.format,
        original.size_bytes
    FROM jsonb_to_recordset(:'retained'::jsonb) AS original(
        id uuid, accepted_at timestamptz, format text, size_bytes integer
    )
    WHERE original.accepted_at < :'before'::timestamptz
      AND original.format IN ('pdf', 'docx', 'md')
      AND original.size_bytes > 0
      AND EXISTS (
          SELECT 1
          FROM rag_jobs AS job
          CROSS JOIN LATERAL jsonb_array_elements(job.cleanup) AS artifact
          WHERE job.source_kind = 'file'
            AND job.status = 'succeeded'
            AND artifact->>'file_id' = original.id::text
      )
      AND NOT EXISTS (SELECT 1 FROM rag_jobs WHERE file_id = original.id)
    ORDER BY original.id, original.accepted_at
), inserted AS (
    INSERT INTO rag_import_events (id, accepted_at, format, size_bytes)
    SELECT id, accepted_at, format, size_bytes FROM historical_jobs
    UNION ALL
    SELECT id, accepted_at, format, size_bytes FROM retained_originals
    ON CONFLICT (id) DO NOTHING
    RETURNING size_bytes
)
SELECT count(*) AS added_uploads, count(size_bytes) AS known_sizes,
       coalesce(sum(size_bytes), 0) AS added_bytes
FROM inserted;

\if :apply
    COMMIT;
\else
    ROLLBACK;
\endif
