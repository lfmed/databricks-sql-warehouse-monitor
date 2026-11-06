"""SQL dos datasets do dashboard de monitoramento de SQL Warehouse.

Parametros de dashboard:
  :warehouse      -> STRING no formato "nome | warehouse_id" (vem do filtro) ou so o id
  :periodo.min/.max -> DATE RANGE
"""

WH_ID = "TRIM(SUBSTRING_INDEX(:warehouse, '|', -1))"

FILTRO_Q = f"""compute.warehouse_id = {WH_ID}
  AND start_time >= :periodo.min
  AND start_time < DATE_ADD(:periodo.max, 1)"""

DATASETS = {}

DATASETS["ds_warehouses"] = """SELECT CONCAT(warehouse_name, ' | ', warehouse_id) AS warehouse
FROM system.compute.warehouses
QUALIFY ROW_NUMBER() OVER (PARTITION BY warehouse_id ORDER BY change_time DESC) = 1
  AND delete_time IS NULL
ORDER BY 1"""

DATASETS["ds_config"] = f"""SELECT warehouse_name, warehouse_id, warehouse_type, warehouse_size,
       min_clusters, max_clusters, auto_stop_minutes, warehouse_channel AS channel
FROM system.compute.warehouses
WHERE warehouse_id = {WH_ID}
QUALIFY ROW_NUMBER() OVER (PARTITION BY warehouse_id ORDER BY change_time DESC) = 1"""

DATASETS["ds_hora"] = f"""SELECT
  DATE_TRUNC('HOUR', start_time)                                    AS hora,
  COUNT(*)                                                          AS queries,
  COUNT_IF(execution_status = 'FAILED')                             AS falhas,
  COUNT_IF(execution_status = 'CANCELED')                           AS canceladas,
  COUNT_IF(COALESCE(waiting_at_capacity_duration_ms, 0) > 0)        AS enfileiradas,
  SUM(COALESCE(waiting_at_capacity_duration_ms, 0)) / 1000          AS fila_total_s,
  SUM(COALESCE(waiting_for_compute_duration_ms, 0)) / 1000          AS espera_compute_total_s,
  SUM(total_duration_ms) / 1000                                     AS duracao_total_s,
  PERCENTILE_APPROX(COALESCE(waiting_at_capacity_duration_ms, 0), 0.95) / 1000 AS fila_p95_s,
  MAX(COALESCE(waiting_at_capacity_duration_ms, 0)) / 1000          AS fila_max_s,
  PERCENTILE_APPROX(total_duration_ms, 0.95) / 1000                 AS duracao_p95_s,
  COUNT_IF(from_result_cache)                                       AS cache_hits,
  COUNT_IF(spilled_local_bytes > 0)                                 AS com_spill
FROM system.query.history
WHERE {FILTRO_Q}
GROUP BY 1
ORDER BY 1"""

# Pico de queries simultaneas (fila + execucao) por hora
DATASETS["ds_concorrencia"] = f"""WITH q AS (
  SELECT start_time, end_time
  FROM system.query.history
  WHERE {FILTRO_Q}
    AND end_time IS NOT NULL
),
ev AS (
  SELECT start_time AS ts, 1 AS d FROM q
  UNION ALL
  SELECT end_time AS ts, -1 AS d FROM q
),
corr AS (
  SELECT ts, SUM(d) OVER (ORDER BY ts, d ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS ativas
  FROM ev
)
SELECT DATE_TRUNC('HOUR', ts) AS hora, MAX(ativas) AS pico_concorrencia
FROM corr
WHERE ts < DATE_ADD(:periodo.max, 1)
GROUP BY 1
ORDER BY 1"""

# Escalonamento: numero de clusters ao longo do tempo
DATASETS["ds_clusters"] = f"""SELECT e.event_time, e.event_type, e.cluster_count,
       c.max_clusters
FROM system.compute.warehouse_events e
LEFT JOIN (
  SELECT warehouse_id, max_clusters
  FROM system.compute.warehouses
  WHERE warehouse_id = {WH_ID}
  QUALIFY ROW_NUMBER() OVER (PARTITION BY warehouse_id ORDER BY change_time DESC) = 1
) c ON e.warehouse_id = c.warehouse_id
WHERE e.warehouse_id = {WH_ID}
  AND e.event_time >= :periodo.min
  AND e.event_time < DATE_ADD(:periodo.max, 1)
ORDER BY e.event_time"""

DATASETS["ds_custo"] = f"""SELECT
  u.usage_date                                         AS dia,
  SUM(u.usage_quantity)                                AS dbus,
  SUM(u.usage_quantity * COALESCE(p.pricing.effective_list.default, p.pricing.default)) AS custo_usd
FROM system.billing.usage u
LEFT JOIN system.billing.list_prices p
  ON  u.sku_name   = p.sku_name
  AND u.cloud      = p.cloud
  AND u.usage_unit = p.usage_unit
  AND u.usage_start_time >= p.price_start_time
  AND (p.price_end_time IS NULL OR u.usage_start_time < p.price_end_time)
WHERE u.usage_metadata.warehouse_id = {WH_ID}
  AND u.usage_date >= :periodo.min
  AND u.usage_date <= :periodo.max
GROUP BY 1
ORDER BY 1"""

# Semaforo de saude: um indicador por linha com status
DATASETS["ds_saude"] = f"""WITH q AS (
  SELECT * FROM system.query.history
  WHERE {FILTRO_Q}
),
m AS (
  SELECT
    COUNT(*) AS n,
    COUNT_IF(COALESCE(waiting_at_capacity_duration_ms, 0) > 0) / NULLIF(COUNT(*), 0) AS pct_fila,
    PERCENTILE_APPROX(COALESCE(waiting_at_capacity_duration_ms, 0), 0.95) / 1000 AS fila_p95_s,
    COALESCE(AVG(CASE WHEN waiting_at_capacity_duration_ms > 0 THEN waiting_at_capacity_duration_ms END), 0) / 1000 AS fila_media_s,
    COUNT_IF(execution_status = 'FAILED') / NULLIF(COUNT(*), 0) AS pct_falha,
    PERCENTILE_APPROX(total_duration_ms, 0.95) / 1000 AS duracao_p95_s,
    AVG(COALESCE(waiting_for_compute_duration_ms, 0)) / 1000 AS espera_compute_media_s,
    COUNT_IF(spilled_local_bytes > 0) / NULLIF(COUNT(*), 0) AS pct_spill
  FROM q
),
cl AS (
  SELECT MAX(cluster_count) AS max_atingido
  FROM system.compute.warehouse_events
  WHERE warehouse_id = {WH_ID}
    AND event_time >= :periodo.min AND event_time < DATE_ADD(:periodo.max, 1)
),
cfg AS (
  SELECT max_clusters FROM system.compute.warehouses
  WHERE warehouse_id = {WH_ID}
  QUALIFY ROW_NUMBER() OVER (PARTITION BY warehouse_id ORDER BY change_time DESC) = 1
),
ind AS (
  SELECT 1 AS ordem, '% de queries que entraram na fila' AS indicador,
         CONCAT(FORMAT_NUMBER(pct_fila * 100, 1), '%') AS valor,
         CASE WHEN pct_fila < 0.05 THEN 0 WHEN pct_fila < 0.15 THEN 1 ELSE 2 END AS nivel,
         'OK < 5% | Atencao < 15%' AS referencia FROM m
  UNION ALL
  SELECT 2, 'Tempo de fila p95',
         CONCAT(FORMAT_NUMBER(fila_p95_s, 1), ' s'),
         CASE WHEN fila_p95_s < 5 THEN 0 WHEN fila_p95_s < 30 THEN 1 ELSE 2 END,
         'OK < 5 s | Atencao < 30 s' FROM m
  UNION ALL
  SELECT 3, 'Espera media (so queries enfileiradas)',
         CONCAT(FORMAT_NUMBER(fila_media_s, 1), ' s'),
         CASE WHEN fila_media_s < 10 THEN 0 WHEN fila_media_s < 60 THEN 1 ELSE 2 END,
         'OK < 10 s | Atencao < 60 s' FROM m
  UNION ALL
  SELECT 4, 'Uso de clusters (max atingido / max config.)',
         CONCAT(COALESCE(cl.max_atingido, 0), ' / ', COALESCE(cfg.max_clusters, 0)),
         CASE WHEN COALESCE(cl.max_atingido, 0) < COALESCE(cfg.max_clusters, 0) THEN 0
              WHEN m.pct_fila >= 0.05 THEN 2 ELSE 1 END,
         'Bateu no teto + fila = aumentar max clusters' FROM m CROSS JOIN cl CROSS JOIN cfg
  UNION ALL
  SELECT 5, '% de queries com falha',
         CONCAT(FORMAT_NUMBER(pct_falha * 100, 2), '%'),
         CASE WHEN pct_falha < 0.02 THEN 0 WHEN pct_falha < 0.05 THEN 1 ELSE 2 END,
         'OK < 2% | Atencao < 5%' FROM m
  UNION ALL
  SELECT 6, 'Duracao total p95',
         CONCAT(FORMAT_NUMBER(duracao_p95_s, 1), ' s'),
         CASE WHEN duracao_p95_s < 30 THEN 0 WHEN duracao_p95_s < 120 THEN 1 ELSE 2 END,
         'OK < 30 s | Atencao < 120 s' FROM m
  UNION ALL
  SELECT 7, 'Espera media por compute (start/scale)',
         CONCAT(FORMAT_NUMBER(espera_compute_media_s, 2), ' s'),
         CASE WHEN espera_compute_media_s < 2 THEN 0 WHEN espera_compute_media_s < 10 THEN 1 ELSE 2 END,
         'OK < 2 s | Atencao < 10 s' FROM m
  UNION ALL
  SELECT 8, '% de queries com spill em disco',
         CONCAT(FORMAT_NUMBER(pct_spill * 100, 1), '%'),
         CASE WHEN pct_spill < 0.05 THEN 0 WHEN pct_spill < 0.15 THEN 1 ELSE 2 END,
         'OK < 5% | Atencao < 15% (avaliar tamanho)' FROM m
)
SELECT ordem, indicador, valor, referencia,
       CASE nivel WHEN 0 THEN '🟢 OK' WHEN 1 THEN '🟡 Atencao' ELSE '🔴 Critico' END AS status
FROM ind
ORDER BY ordem"""

DATASETS["ds_top_queries"] = f"""SELECT
  statement_id,
  start_time                                                   AS inicio,
  executed_by                                                  AS usuario,
  COALESCE(client_application, '-')                            AS aplicacao,
  execution_status                                             AS status,
  ROUND(COALESCE(waiting_at_capacity_duration_ms, 0) / 1000, 1) AS fila_s,
  ROUND(COALESCE(waiting_for_compute_duration_ms, 0) / 1000, 1) AS espera_compute_s,
  ROUND(COALESCE(execution_duration_ms, 0) / 1000, 1)          AS execucao_s,
  ROUND(total_duration_ms / 1000, 1)                           AS total_s,
  ROUND(COALESCE(read_bytes, 0) / POW(1024, 3), 2)             AS gb_lidos,
  ROUND(COALESCE(spilled_local_bytes, 0) / POW(1024, 3), 2)    AS gb_spill,
  LEFT(statement_text, 200)                                    AS query
FROM system.query.history
WHERE {FILTRO_Q}
ORDER BY total_duration_ms DESC
LIMIT 100"""

DATASETS["ds_usuarios"] = f"""SELECT
  executed_by                                                  AS usuario,
  COALESCE(client_application, '-')                            AS aplicacao,
  COUNT(*)                                                     AS queries,
  COUNT_IF(execution_status = 'FAILED')                        AS falhas,
  COUNT_IF(COALESCE(waiting_at_capacity_duration_ms, 0) > 0)   AS enfileiradas,
  ROUND(SUM(COALESCE(waiting_at_capacity_duration_ms, 0)) / 60000, 1) AS minutos_em_fila,
  ROUND(SUM(COALESCE(total_task_duration_ms, 0)) / 3600000, 2) AS horas_cpu,
  ROUND(PERCENTILE_APPROX(total_duration_ms, 0.95) / 1000, 1)  AS duracao_p95_s
FROM system.query.history
WHERE {FILTRO_Q}
GROUP BY ALL
ORDER BY horas_cpu DESC
LIMIT 200"""


def for_test(sql: str, warehouse: str, dmin: str, dmax: str) -> str:
    return (sql.replace(":periodo.min", f"DATE'{dmin}'")
               .replace(":periodo.max", f"DATE'{dmax}'")
               .replace(":warehouse", f"'{warehouse}'"))
