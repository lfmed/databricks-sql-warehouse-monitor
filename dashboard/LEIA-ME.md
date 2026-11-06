# Dashboard: Monitoramento de SQL Warehouse

Arquivo: `monitoramento_sql_warehouse.lvdash.json` (AI/BI Dashboard)

## Pré-requisitos
- System tables habilitadas: `system.query`, `system.compute`, `system.billing`.
- Quem for visualizar (ou o dono, se publicado com credenciais embutidas) precisa de
  `SELECT` em `system.query.history`, `system.compute.warehouses`,
  `system.compute.warehouse_events`, `system.billing.usage` e `system.billing.list_prices`.

## Como importar
1. Workspace > **Dashboards** > seta ao lado de **Create dashboard** > **Import dashboard from file**.
2. Selecione o `.lvdash.json`.
3. No dashboard, escolha um SQL Warehouse para executar as queries (serverless recomendado).
4. **Publish**.

Ou via CLI:
```bash
databricks lakeview create --display-name "Monitoramento de SQL Warehouse" \
  --warehouse-id <WAREHOUSE_PARA_RODAR> \
  --serialized-dashboard "$(cat monitoramento_sql_warehouse.lvdash.json)"
```

## Uso
- Filtro **Warehouse** (formato `nome | id`) e **Periodo** (padrão: últimos 7 dias).
- Enquanto nenhum warehouse estiver selecionado, os widgets ficam vazios.

## O que mostra
| Bloco | Leitura |
|---|---|
| KPIs | Queries, % com fila, espera média na fila, pico de concorrência, % falhas, custo |
| Semáforo | 🟢 OK / 🟡 Atenção / 🔴 Crítico para fila, falhas, latência, clusters, spill |
| Queries x enfileiradas | Picos de enfileiradas = falta de capacidade |
| Tempo de fila | Espera média e máxima por hora |
| Concorrência | Máximo de queries simultâneas (fila + execução) |
| Clusters x máximo | Encostou no máximo + fila → aumentar `max_clusters` |
| Custo diário | DBUs × preço de lista (não reflete descontos contratuais) |
| Top queries / usuários | Quem e o que consome e espera mais |

## Ajustar limites do semáforo
Edite o dataset **Semaforo de saude** (cláusulas `CASE WHEN ...`).

## Notas
- `waiting_at_capacity_duration_ms` = fila por warehouse cheio;
  `waiting_for_compute_duration_ms` = espera por start/scale up.
- System tables têm latência de alguns minutos; para tempo real use a aba Monitoring do warehouse.
