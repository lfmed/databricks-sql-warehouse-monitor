# Databricks SQL Warehouse Monitor

Monitoramento de um SQL Warehouse específico usando **system tables** do Databricks:
volume de queries, fila, concorrência, escalonamento de clusters, falhas, latência e custo.

## Conteúdo

| Caminho | Descrição |
|---|---|
| `dashboard/monitoramento_sql_warehouse.lvdash.json` | AI/BI Dashboard pronto para importar |
| `dashboard/LEIA-ME.md` | Pré-requisitos, importação e leitura do dashboard |
| `monitoramento_warehouse.sql` | Queries avulsas (SQL Editor / Alerts) com `:warehouse_id` e `:dias` |
| `scripts/datasets.py` | SQL dos datasets do dashboard (fonte da verdade) |
| `scripts/build_dashboard.py` | Gera o `.lvdash.json` a partir de `datasets.py` |
| `scripts/test_datasets.py` | Executa os datasets via Databricks CLI para validação |

## Uso rápido

1. Databricks → **Dashboards** → **Create dashboard ▾** → **Import dashboard from file** → selecione o `.lvdash.json`.
2. Escolha um SQL Warehouse para executar o dashboard e publique.
3. Selecione o **Warehouse** e o **Período** nos filtros.

Requer system tables habilitadas e `SELECT` em `system.query`, `system.compute` e `system.billing`.

## Desenvolvimento

```bash
# editar queries em scripts/datasets.py e regenerar o JSON
python3 scripts/build_dashboard.py

# testar os datasets (requer Databricks CLI autenticado)
python3 scripts/test_datasets.py <profile> <warehouse_id_execucao> "<nome | warehouse_id>" 2026-01-01 2026-01-07
```

## Indicadores do semáforo

| Indicador | OK | Atenção |
|---|---|---|
| % queries com fila | < 5% | < 15% |
| Fila p95 | < 5 s | < 30 s |
| Espera média (enfileiradas) | < 10 s | < 60 s |
| % falhas | < 2% | < 5% |
| Duração p95 | < 30 s | < 120 s |
| Espera por compute | < 2 s | < 10 s |
| % com spill | < 5% | < 15% |
| Clusters | abaixo do máximo | no máximo (crítico se houver fila) |

Limites ajustáveis em `scripts/datasets.py` (`ds_saude`).
