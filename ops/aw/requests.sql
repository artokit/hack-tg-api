WITH event_flags AS (
    SELECT
        event.request_id,
        event.role,
        event.event_key,
        (to_jsonb(event)->>'has_answer')::boolean AS has_answer,
        (to_jsonb(event)->>'has_clarification')::boolean AS has_clarification
    FROM public.bars_telegram_request_events AS event
), event_counts AS (
    SELECT
        request_id,
        count(*) FILTER (WHERE role = 'assistant' AND has_answer IS TRUE) AS answer_count,
        count(*) FILTER (WHERE role = 'assistant' AND has_clarification IS TRUE) AS clarification_count,
        count(*) FILTER (
            WHERE role = 'assistant' AND (has_answer IS NULL OR has_clarification IS NULL)
        ) AS unknown_reply_count,
        bool_or(event_key LIKE 'handoff:%') AS has_handoff_event
    FROM event_flags
    GROUP BY request_id
), request_data AS (
    SELECT
        coalesce(saved.id, runtime.id)::text AS request_id,
        nullif(btrim(coalesce(saved.category_id, runtime.outcome->>'category_id')), '') AS category_id,
        coalesce(saved.opened_at, runtime.opened_at) AT TIME ZONE 'UTC' AS opened_at_utc,
        coalesce(saved.closed_at, runtime.closed_at) AT TIME ZONE 'UTC' AS closed_at_utc,
        coalesce(saved.is_resolved, (runtime.outcome->>'is_resolved')::boolean) AS is_resolved,
        coalesce(saved.close_reason, runtime.outcome->>'close_reason') AS close_reason,
        coalesce(jsonb_typeof(runtime.outcome->'handoff') = 'object', false)
            OR coalesce(events.has_handoff_event, false) AS has_handoff,
        coalesce((to_jsonb(runtime)->>'tracks_response_metrics')::boolean, false)
            AND coalesce(events.unknown_reply_count, 0) = 0 AS response_metrics_complete,
        coalesce(events.answer_count, 0)::integer AS recorded_answers,
        coalesce(events.clarification_count, 0)::integer AS recorded_clarifications,
        (to_jsonb(runtime)->>'kb_search_count')::integer AS kb_search_count
    FROM public.support_requests AS saved
    FULL JOIN public.bars_telegram_requests AS runtime ON runtime.id = saved.id
    LEFT JOIN event_counts AS events ON events.request_id = coalesce(saved.id, runtime.id)
), outcomes AS (
    SELECT
        *,
        is_resolved IS TRUE AND close_reason = 'confirmed' AND NOT has_handoff AS bot_resolved
    FROM request_data
)
SELECT
    request_id,
    category_id,
    opened_at_utc,
    closed_at_utc,
    is_resolved,
    close_reason,
    CASE category_id
        WHEN 'access' THEN 'Доступ и авторизация'
        WHEN 'navigation' THEN 'Интерфейс и навигация'
        WHEN 'search_filters' THEN 'Поиск и фильтры'
        WHEN 'documents_records' THEN 'Документы и записи'
        WHEN 'business_processes' THEN 'Бизнес-процессы и согласование'
        WHEN 'employees_contacts' THEN 'Сотрудники и контакты'
        WHEN 'other' THEN 'Прочее'
        ELSE coalesce(category_id, CASE WHEN closed_at_utc IS NULL
            THEN 'Открыто — категория ещё не определена' ELSE 'Тема не указана' END)
    END AS topic,
    1 AS request_count,
    has_handoff::integer AS escalation_count,
    CASE WHEN bot_resolved THEN 1 ELSE 0 END AS bot_resolved_count,
    CASE close_reason
        WHEN 'operator_requested' THEN 'Пользователь запросил оператора'
        WHEN 'rag_exhausted' THEN 'Бот не нашёл решение (RAG)'
        WHEN 'confirmed' THEN 'Решение подтверждено'
        WHEN 'thanks' THEN 'Благодарность пользователя'
        WHEN 'feedback_timeout' THEN 'Нет оценки пользователя'
        WHEN 'clarification_timeout' THEN 'Нет ответа на уточнение'
        WHEN 'details_timeout' THEN 'Нет дополнительных деталей'
        WHEN 'technical_timeout' THEN 'Технический таймаут'
        WHEN 'handoff_failed' THEN 'Ошибка передачи оператору'
        WHEN 'delivery_failed' THEN 'Ошибка доставки ответа'
        WHEN 'user_closed' THEN 'Пользователь закрыл обращение'
        WHEN 'user_requested' THEN 'Закрыто по просьбе пользователя'
        WHEN 'spam' THEN 'Спам'
        ELSE coalesce(close_reason, 'Обращение открыто')
    END AS close_reason_label,
    CASE WHEN bot_resolved THEN 100.0::double precision ELSE 0.0 END AS bot_resolved_percent,
    100.0::double precision * has_handoff::integer AS escalation_percent,
    response_metrics_complete,
    CASE WHEN response_metrics_complete THEN recorded_answers END AS answer_count,
    CASE WHEN response_metrics_complete THEN recorded_clarifications END AS clarification_count,
    CASE WHEN response_metrics_complete THEN 100.0::double precision ELSE 0.0 END
        AS response_metrics_coverage_percent,
    CASE WHEN response_metrics_complete THEN
        CASE WHEN bot_resolved AND recorded_answers = 1 AND recorded_clarifications = 0
            THEN 100.0::double precision ELSE 0.0 END
    END AS first_answer_resolved_percent,
    kb_search_count,
    CASE WHEN kb_search_count IS NOT NULL THEN 100.0::double precision ELSE 0.0 END
        AS kb_search_coverage_percent,
    CASE WHEN kb_search_count IS NOT NULL THEN
        CASE WHEN bot_resolved AND kb_search_count = 1
            THEN 100.0::double precision ELSE 0.0 END
    END AS first_kb_search_resolved_percent
FROM outcomes
WHERE close_reason IS DISTINCT FROM 'reset'
