-- =====================================================================
-- MONITORAMENTO DE UM SQL WAREHOUSE ESPECIFICO - Databricks System Tables
-- =====================================================================
-- Parametros (funcionam no SQL Editor, AI/BI Dashboards e Alerts):
--   :warehouse_id  -> ID do warehouse (ex.: 'abc123def4567890')
--   :dias          -> janela de analise em dias (ex.: 7)
--
-- Tabelas usadas (precisam estar habilitadas e com SELECT concedido):
--   system.query.history          -> queries, duracao, fila, cache, I/O
--   system.compute.warehouse_events -> start/stop/scale up/scale down
--   system.compute.warehouses     -> configuracao (size, min/max clusters)
--   system.billing.usage / list_prices -> DBUs e custo estimado
--
-- Observacao: system tables tem latencia de alguns minutos. Para estado
-- em tempo real (queries em fila agora), use a API de Warehouses /
-- Query History ou a aba "Monitoring" do warehouse.
-- =====================================================================


-- ---------------------------------------------------------------------
-- 1) KPIs RESUMO DO PERIODO
-- ---------------------------------------------------------------------
SELECT
  COUNT(*)                                                        AS total_queries,
  COUNT_IF(execution_status = 'FINISHED')                         AS finalizadas,
  COUNT_IF(execution_status = 'FAILED')                           AS falhas,
  COUNT_IF(execution_status = 'CANCELED')                         AS canceladas,
  ROUND(100 * COUNT_IF(execution_status = 'FAILED') / COUNT(*), 2) AS pct_falha,
  COUNT(DISTINCT executed_by)                                     AS usuarios_distintos,

  -- Duracao total (segundos)
  ROUND(AVG(total_duration_ms) / 1000, 2)                         AS duracao_media_s,
  ROUND(PERCENTILE_APPROX(total_duration_ms, 0.50) / 1000, 2)     AS duracao_p50_s,
  ROUND(PERCENTILE_APPROX(total_duration_ms, 0.90) / 1000, 2)     AS duracao_p90_s,
  ROUND(PERCENTILE_APPROX(total_duration_ms, 0.99) / 1000, 2)     AS duracao_p99_s,

  -- FILA: espera por capacidade (warehouse cheio) + espera por compute (start/scale)
  COUNT_IF(COALESCE(waiting_at_capacity_duration_ms, 0) > 0)      AS queries_enfileiradas_capacidade,
  ROUND(100 * COUNT_IF(COALESCE(waiting_at_capacity_duration_ms, 0) > 0) / COUNT(*), 2)
                                                                  AS pct_queries_enfileiradas,
  ROUND(AVG(COALESCE(waiting_at_capacity_duration_ms, 0)) / 1000, 2)  AS fila_capacidade_media_s,
  ROUND(PERCENTILE_APPROX(COALESCE(waiting_at_capacity_duration_ms, 0), 0.95) / 1000, 2)
                                                                  AS fila_capacidade_p95_s,
  ROUND(MAX(COALESCE(waiting_at_capacity_duration_ms, 0)) / 1000, 2)  AS fila_capacidade_max_s,
  COUNT_IF(COALESCE(waiting_for_compute_duration_ms, 0) > 0)      AS queries_esperando_compute,
  ROUND(AVG(COALESCE(waiting_for_compute_duration_ms, 0)) / 1000, 2)  AS espera_compute_media_s,

  -- Eficiencia
  ROUND(100 * COUNT_IF(from_result_cache) / COUNT(*), 2)          AS pct_result_cache,
  ROUND(AVG(read_io_cache_percent), 2)                            AS media_io_cache_pct,
  ROUND(SUM(read_bytes) / POW(1024, 4), 3)                        AS tb_lidos,
  ROUND(SUM(spilled_local_bytes) / POW(1024, 3), 2)               AS gb_spill,
  COUNT_IF(spilled_local_bytes > 0)                               AS queries_com_spill
FROM system.query.history
WHERE compute.warehouse_id = :warehouse_id
  AND start_time >= DATEADD(DAY, -CAST(:dias AS INT), CURRENT_TIMESTAMP());


-- ---------------------------------------------------------------------
-- 2) SERIE TEMPORAL POR HORA (volume, fila, latencia)
--    Ideal para grafico de linhas no dashboard
-- ---------------------------------------------------------------------
SELECT
  DATE_TRUNC('HOUR', start_time)                                  AS hora,
  COUNT(*)                                                        AS queries,
  COUNT_IF(execution_status = 'FAILED')                           AS falhas,
  COUNT_IF(COALESCE(waiting_at_capacity_duration_ms, 0) > 0)      AS queries_enfileiradas,
  ROUND(AVG(COALESCE(waiting_at_capacity_duration_ms, 0)) / 1000, 2) AS fila_media_s,
  ROUND(PERCENTILE_APPROX(COALESCE(waiting_at_capacity_duration_ms, 0), 0.95) / 1000, 2) AS fila_p95_s,
  ROUND(AVG(COALESCE(waiting_for_compute_duration_ms, 0)) / 1000, 2) AS espera_compute_media_s,
  ROUND(PERCENTILE_APPROX(execution_duration_ms, 0.50) / 1000, 2) AS execucao_p50_s,
  ROUND(PERCENTILE_APPROX(execution_duration_ms, 0.95) / 1000, 2) AS execucao_p95_s,
  ROUND(PERCENTILE_APPROX(total_duration_ms, 0.95) / 1000, 2)     AS duracao_total_p95_s
FROM system.query.history
WHERE compute.warehouse_id = :warehouse_id
  AND start_time >= DATEADD(DAY, -CAST(:dias AS INT), CURRENT_TIMESTAMP())
GROUP BY 1
ORDER BY 1;


-- ---------------------------------------------------------------------
-- 3) PICO DE CONCORRENCIA POR HORA
--    Queries ativas simultaneamente (em fila + executando)
-- ---------------------------------------------------------------------
WITH q AS (
  SELECT start_time, end_time
  FROM system.query.history
  WHERE compute.warehouse_id = :warehouse_id
    AND start_time >= DATEADD(DAY, -CAST(:dias AS INT), CURRENT_TIMESTAMP())
    AND end_time IS NOT NULL
),
eventos AS (
  SELECT start_time AS ts,  1 AS delta FROM q
  UNION ALL
  SELECT end_time   AS ts, -1 AS delta FROM q
),
corrente AS (
  SELECT ts,
         SUM(delta) OVER (ORDER BY ts, delta ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS concorrentes
  FROM eventos
)
SELECT DATE_TRUNC('HOUR', ts) AS hora,
       MAX(concorrentes)      AS pico_queries_concorrentes
FROM corrente
GROUP BY 1
ORDER BY 1;


-- ---------------------------------------------------------------------
-- 4) EVENTOS DO WAREHOUSE (start/stop/scale up/scale down)
-- ---------------------------------------------------------------------
SELECT
  event_time,
  event_type,          -- STARTING, RUNNING, SCALED_UP, SCALED_DOWN, STOPPING, STOPPED
  cluster_count
FROM system.compute.warehouse_events
WHERE warehouse_id = :warehouse_id
  AND event_time >= DATEADD(DAY, -CAST(:dias AS INT), CURRENT_TIMESTAMP())
ORDER BY event_time DESC;

-- 4b) Resumo de escalonamento por dia
SELECT
  DATE(event_time)                         AS dia,
  COUNT_IF(event_type = 'SCALED_UP')       AS scale_ups,
  COUNT_IF(event_type = 'SCALED_DOWN')     AS scale_downs,
  COUNT_IF(event_type = 'STARTING')        AS starts,
  MAX(cluster_count)                       AS max_clusters_atingido
FROM system.compute.warehouse_events
WHERE warehouse_id = :warehouse_id
  AND event_time >= DATEADD(DAY, -CAST(:dias AS INT), CURRENT_TIMESTAMP())
GROUP BY 1
ORDER BY 1;


-- ---------------------------------------------------------------------
-- 5) CONFIGURACAO ATUAL DO WAREHOUSE
--    (compare max_clusters com max_clusters_atingido da query 4b:
--     se bate no teto e ha fila -> aumentar max_clusters)
-- ---------------------------------------------------------------------
SELECT
  warehouse_id, warehouse_name, warehouse_type, warehouse_size,
  warehouse_channel, min_clusters, max_clusters, auto_stop_minutes,
  change_time
FROM system.compute.warehouses
WHERE warehouse_id = :warehouse_id
QUALIFY ROW_NUMBER() OVER (PARTITION BY warehouse_id ORDER BY change_time DESC) = 1;


-- ---------------------------------------------------------------------
-- 6) TOP 50 QUERIES COM MAIOR FILA / MAIS LENTAS
-- ---------------------------------------------------------------------
SELECT
  statement_id,
  executed_by,
  client_application,
  execution_status,
  start_time,
  ROUND(COALESCE(waiting_at_capacity_duration_ms, 0) / 1000, 1) AS fila_s,
  ROUND(COALESCE(waiting_for_compute_duration_ms, 0) / 1000, 1) AS espera_compute_s,
  ROUND(compilation_duration_ms / 1000, 1)                       AS compilacao_s,
  ROUND(execution_duration_ms / 1000, 1)                         AS execucao_s,
  ROUND(total_duration_ms / 1000, 1)                             AS total_s,
  ROUND(read_bytes / POW(1024, 3), 2)                            AS gb_lidos,
  ROUND(spilled_local_bytes / POW(1024, 3), 2)                   AS gb_spill,
  LEFT(statement_text, 300)                                      AS query_trecho
FROM system.query.history
WHERE compute.warehouse_id = :warehouse_id
  AND start_time >= DATEADD(DAY, -CAST(:dias AS INT), CURRENT_TIMESTAMP())
ORDER BY total_duration_ms DESC   -- troque para waiting_at_capacity_duration_ms DESC para ver fila
LIMIT 50;


-- ---------------------------------------------------------------------
-- 7) CONSUMO POR USUARIO / APLICACAO
-- ---------------------------------------------------------------------
SELECT
  executed_by,
  client_application,
  COUNT(*)                                                     AS queries,
  COUNT_IF(execution_status = 'FAILED')                        AS falhas,
  ROUND(SUM(total_task_duration_ms) / 3600000, 2)              AS horas_task_cpu,
  ROUND(SUM(COALESCE(waiting_at_capacity_duration_ms, 0)) / 60000, 1) AS minutos_em_fila,
  ROUND(PERCENTILE_APPROX(total_duration_ms, 0.95) / 1000, 2)  AS duracao_p95_s,
  ROUND(SUM(read_bytes) / POW(1024, 3), 2)                     AS gb_lidos
FROM system.query.history
WHERE compute.warehouse_id = :warehouse_id
  AND start_time >= DATEADD(DAY, -CAST(:dias AS INT), CURRENT_TIMESTAMP())
GROUP BY ALL
ORDER BY horas_task_cpu DESC;


-- ---------------------------------------------------------------------
-- 8) CUSTO DIARIO (DBUs e US$ estimado a preco de lista)
-- ---------------------------------------------------------------------
SELECT
  u.usage_date,
  u.sku_name,
  ROUND(SUM(u.usage_quantity), 2)                                AS dbus,
  ROUND(SUM(u.usage_quantity * p.pricing.default), 2)            AS custo_lista_usd
FROM system.billing.usage u
LEFT JOIN system.billing.list_prices p
  ON  u.sku_name   = p.sku_name
  AND u.cloud      = p.cloud
  AND u.usage_unit = p.usage_unit
  AND u.usage_start_time >= p.price_start_time
  AND (p.price_end_time IS NULL OR u.usage_start_time < p.price_end_time)
WHERE u.usage_metadata.warehouse_id = :warehouse_id
  AND u.usage_date >= DATE_SUB(CURRENT_DATE(), CAST(:dias AS INT))
GROUP BY ALL
ORDER BY u.usage_date;


-- ---------------------------------------------------------------------
-- 9) QUERY PARA ALERTA (Databricks SQL Alert) - ultimos 15 minutos
--    Ex.: disparar quando fila_p95_s > 30 ou pct_falha > 5
-- ---------------------------------------------------------------------
SELECT
  COUNT(*)                                                                 AS queries_15min,
  COUNT_IF(COALESCE(waiting_at_capacity_duration_ms, 0) > 0)               AS enfileiradas_15min,
  ROUND(PERCENTILE_APPROX(COALESCE(waiting_at_capacity_duration_ms, 0), 0.95) / 1000, 2) AS fila_p95_s,
  ROUND(100 * COUNT_IF(execution_status = 'FAILED') / NULLIF(COUNT(*), 0), 2) AS pct_falha
FROM system.query.history
WHERE compute.warehouse_id = :warehouse_id
  AND start_time >= CURRENT_TIMESTAMP() - INTERVAL 15 MINUTES;
