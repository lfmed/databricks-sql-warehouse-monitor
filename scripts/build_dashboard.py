"""Gera dashboard/monitoramento_sql_warehouse.lvdash.json a partir de scripts/datasets.py"""
import json, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from datasets import DATASETS

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dashboard", "monitoramento_sql_warehouse.lvdash.json")

P_WH = {"keyword": "warehouse", "displayName": "warehouse", "dataType": "STRING",
        "defaultSelection": {"values": {"dataType": "STRING", "values": [{"value": ""}]}}}
P_DT = {"keyword": "periodo", "displayName": "periodo", "dataType": "DATE", "complexType": "RANGE",
        "defaultSelection": {"range": {"dataType": "DATE",
                                       "min": {"value": "now-7d/d"}, "max": {"value": "now/d"}}}}

DISPLAY = {
    "ds_warehouses": "Lista de warehouses",
    "ds_config": "Configuracao do warehouse",
    "ds_hora": "Metricas por hora",
    "ds_concorrencia": "Concorrencia por hora",
    "ds_clusters": "Eventos de escalonamento",
    "ds_custo": "Custo diario",
    "ds_saude": "Semaforo de saude",
    "ds_top_queries": "Top queries",
    "ds_usuarios": "Por usuario",
}

MEASURES = {
    "ds_hora": [
        {"displayName": "m_total_queries", "expression": "SUM(`queries`)"},
        {"displayName": "m_pct_fila", "expression": "SUM(`enfileiradas`) * 1.0 / NULLIF(SUM(`queries`), 0)"},
        {"displayName": "m_espera_media_fila", "expression": "COALESCE(SUM(`fila_total_s`) / NULLIF(SUM(`enfileiradas`), 0), 0)"},
        {"displayName": "m_pct_falha", "expression": "SUM(`falhas`) * 1.0 / NULLIF(SUM(`queries`), 0)"},
        {"displayName": "m_duracao_media", "expression": "SUM(`duracao_total_s`) / NULLIF(SUM(`queries`), 0)"},
    ]
}


def lines(sql):
    return [l + "\n" for l in sql.split("\n")]


datasets = []
for name, sql in DATASETS.items():
    ds = {"name": name, "displayName": DISPLAY[name], "queryLines": lines(sql)}
    params = []
    if ":warehouse" in sql:
        params.append(P_WH)
    if ":periodo" in sql:
        params.append(P_DT)
    if params:
        ds["parameters"] = params
    if name in MEASURES:
        ds["columns"] = MEASURES[name]
    datasets.append(ds)

PARAM_DS = [d["name"] for d in datasets if "parameters" in d]
DATE_DS = [d["name"] for d in datasets if any(p["keyword"] == "periodo" for p in d.get("parameters", []))]


def pos(x, y, w, h):
    return {"x": x, "y": y, "width": w, "height": h}


def text(name, md_lines, p):
    return {"widget": {"name": name, "multilineTextboxSpec": {"lines": md_lines}}, "position": p}


def q(ds, fields, disagg=False, orders=None):
    query = {"datasetName": ds, "fields": [{"name": n, "expression": e} for n, e in fields],
             "disaggregated": disagg}
    if orders:
        query["orders"] = orders
    return [{"name": "main_query", "query": query}]


def frame(title, desc=None):
    f = {"showTitle": True, "title": title}
    if desc:
        f["description"] = desc
        f["showDescription"] = True
    return f


NUM0 = {"type": "number", "abbreviation": "compact", "decimalPlaces": {"type": "max", "places": 1}}
PCT = {"type": "number-percent", "decimalPlaces": {"type": "max", "places": 1}}
SEC = {"type": "number-plain", "decimalPlaces": {"type": "max", "places": 1}, "suffix": " s"}
USD = {"type": "number-currency", "currencyCode": "USD", "abbreviation": "compact",
       "decimalPlaces": {"type": "max", "places": 1}}

DAY_HORA = ("daily(hora)", 'DATE_TRUNC("DAY", `hora`)')


def counter_measure(name, title, measure, fmt, desc, p, spark=True):
    fields = [(f"measure({measure})", f"MEASURE(`{measure}`)")]
    enc = {"value": {"fieldName": f"measure({measure})", "displayName": title, "format": fmt}}
    if spark:
        fields.append(DAY_HORA)
        enc["period"] = {"fieldName": DAY_HORA[0]}
    return {"widget": {"name": name, "queries": q("ds_hora", fields),
                       "spec": {"version": 2, "widgetType": "counter", "encodings": enc,
                                "frame": frame(title, desc)}}, "position": p}


def counter_simple(name, title, ds, agg, col, fmt, desc, p, period=None):
    fname = f"{agg.lower()}({col})"
    fields = [(fname, f"{agg}(`{col}`)")]
    enc = {"value": {"fieldName": fname, "displayName": title, "format": fmt}}
    if period:
        pn = f"daily({period})"
        fields.append((pn, f'DATE_TRUNC("DAY", `{period}`)'))
        enc["period"] = {"fieldName": pn}
    return {"widget": {"name": name, "queries": q(ds, fields),
                       "spec": {"version": 2, "widgetType": "counter", "encodings": enc,
                                "frame": frame(title, desc)}}, "position": p}


def chart(name, kind, title, ds, x, ys, p, desc=None, disagg=True, yfmt=None, extra_fields=(), x_type="temporal"):
    fields = [(x, f"`{x}`")] + [(n, e) for n, e, _ in ys] + list(extra_fields)
    yenc = {"scale": {"type": "quantitative"}}
    if len(ys) == 1:
        yenc.update({"fieldName": ys[0][0], "displayName": ys[0][2]})
    else:
        yenc["fields"] = [{"fieldName": n, "displayName": d} for n, _, d in ys]
    if yfmt:
        yenc["format"] = yfmt
    spec = {"version": 3, "widgetType": kind,
            "encodings": {"x": {"fieldName": x, "scale": {"type": x_type}, "displayName": " "},
                          "y": yenc},
            "frame": frame(title, desc)}
    return {"widget": {"name": name, "queries": q(ds, fields, disagg), "spec": spec}, "position": p}


def table(name, title, ds, cols, p, desc=None):
    fields = [(c[0], f"`{c[0]}`") for c in cols]
    enc_cols = []
    for c in cols:
        col = {"fieldName": c[0], "displayName": c[1]}
        if len(c) > 2 and c[2]:
            col.update(c[2])
        enc_cols.append(col)
    return {"widget": {"name": name, "queries": q(ds, fields, True),
                       "spec": {"version": 2, "widgetType": "table",
                                "encodings": {"columns": enc_cols}, "frame": frame(title, desc)}},
            "position": p}


main = []
main.append(text("header", [
    "# Monitoramento de SQL Warehouse\n", "\n",
    "Selecione o **warehouse** e o **periodo** nos filtros (topo). "
    "Comece pelo **Semaforo**: 🟢 saudavel, 🟡 atencao, 🔴 agir. "
    "Fonte: system tables (`system.query.history`, `system.compute.*`, `system.billing.*`), latencia de alguns minutos."
], pos(0, 0, 12, 2)))

# KPIs
main += [
    counter_measure("kpi_queries", "Queries", "m_total_queries", NUM0, "Total no periodo", pos(0, 2, 2, 3)),
    counter_measure("kpi_pct_fila", "% com fila", "m_pct_fila", PCT, "Queries que esperaram slot", pos(2, 2, 2, 3)),
    counter_measure("kpi_espera_fila", "Espera media na fila", "m_espera_media_fila", SEC,
                    "Media das queries enfileiradas", pos(4, 2, 2, 3)),
    counter_simple("kpi_pico", "Pico de concorrencia", "ds_concorrencia", "MAX", "pico_concorrencia",
                   {"type": "number", "decimalPlaces": {"type": "max", "places": 0}},
                   "Max. queries simultaneas", pos(6, 2, 2, 3), period="hora"),
    counter_measure("kpi_pct_falha", "% de falhas", "m_pct_falha", PCT, "Queries com status FAILED", pos(8, 2, 2, 3)),
    counter_simple("kpi_custo", "Custo (lista)", "ds_custo", "SUM", "custo_usd", USD,
                   "Estimado a preco de lista", pos(10, 2, 2, 3), period="dia"),
]

# Semaforo + volume
main.append(table("semaforo", "Semaforo de saude", "ds_saude", [
    ("status", "Status"), ("indicador", "Indicador"), ("valor", "Valor"), ("referencia", "Referencia"),
], pos(0, 5, 6, 7), desc="Indicadores consolidados do periodo com limites de referencia"))
main.append(chart("volume_hora", "line", "Queries x queries enfileiradas (por hora)", "ds_hora", "hora", [
    ("queries", "`queries`", "Queries"), ("enfileiradas", "`enfileiradas`", "Enfileiradas")
], pos(6, 5, 6, 7), desc="Picos de enfileiradas indicam falta de capacidade"))

# Fila + concorrencia
main.append(chart("fila_hora", "line", "Tempo de fila por hora (s)", "ds_hora", "hora", [
    ("measure(m_espera_media_fila)", "MEASURE(`m_espera_media_fila`)", "Espera media (enfileiradas)"),
    ("max(fila_max_s)", "MAX(`fila_max_s`)", "Maior espera"),
], pos(0, 12, 6, 6), disagg=False, yfmt=SEC, desc="Espera por slot livre (warehouse no limite)"))
main.append(chart("concorrencia_hora", "line", "Pico de queries simultaneas (por hora)", "ds_concorrencia", "hora", [
    ("pico_concorrencia", "`pico_concorrencia`", "Queries simultaneas")
], pos(6, 12, 6, 6), desc="Inclui queries em fila e em execucao"))

# Clusters + custo
main.append(chart("clusters", "line", "Clusters ativos x maximo configurado", "ds_clusters", "event_time", [
    ("cluster_count", "`cluster_count`", "Clusters ativos"), ("max_clusters", "`max_clusters`", "Max configurado")
], pos(0, 18, 6, 6), desc="Se a linha encosta no maximo e ha fila: aumente max clusters"))
main.append(chart("custo_dia", "bar", "Custo diario (USD, preco de lista)", "ds_custo", "dia", [
    ("custo_usd", "`custo_usd`", "Custo (USD)")
], pos(6, 18, 6, 6), yfmt=USD))

# Config
main.append(table("config", "Configuracao atual do warehouse", "ds_config", [
    ("warehouse_name", "Nome"), ("warehouse_id", "ID"), ("warehouse_type", "Tipo"),
    ("warehouse_size", "Tamanho"), ("min_clusters", "Min clusters"), ("max_clusters", "Max clusters"),
    ("auto_stop_minutes", "Auto stop (min)"), ("channel", "Canal"),
], pos(0, 24, 12, 3)))

# Detalhes
main.append(text("sec_detalhe", ["## Detalhamento\n"], pos(0, 27, 12, 1)))
main.append(table("top_queries", "Top 100 queries mais longas", "ds_top_queries", [
    ("inicio", "Inicio"), ("usuario", "Usuario"), ("aplicacao", "Aplicacao"), ("status", "Status"),
    ("fila_s", "Fila (s)"), ("espera_compute_s", "Espera compute (s)"), ("execucao_s", "Execucao (s)"),
    ("total_s", "Total (s)"), ("gb_lidos", "GB lidos"), ("gb_spill", "GB spill"),
    ("query", "Query"), ("statement_id", "Statement ID"),
], pos(0, 28, 12, 8)))
main.append(table("usuarios", "Consumo por usuario / aplicacao", "ds_usuarios", [
    ("usuario", "Usuario"), ("aplicacao", "Aplicacao"), ("queries", "Queries"), ("falhas", "Falhas"),
    ("enfileiradas", "Enfileiradas"), ("minutos_em_fila", "Min. em fila"), ("horas_cpu", "Horas CPU"),
    ("duracao_p95_s", "Duracao p95 (s)"),
], pos(0, 36, 12, 7)))

# Filtros globais
wh_queries = [{"name": "q_wh_lista", "query": {"datasetName": "ds_warehouses",
                                                "fields": [{"name": "warehouse", "expression": "`warehouse`"}],
                                                "disaggregated": False}}]
wh_fields = [{"fieldName": "warehouse", "displayName": "Warehouse", "queryName": "q_wh_lista"}]
for ds in PARAM_DS:
    qn = f"q_wh_{ds}"
    wh_queries.append({"name": qn, "query": {"datasetName": ds,
                                             "parameters": [{"name": "warehouse", "keyword": "warehouse"}],
                                             "disaggregated": False}})
    wh_fields.append({"parameterName": "warehouse", "queryName": qn})

dt_queries, dt_fields = [], []
for ds in DATE_DS:
    qn = f"q_dt_{ds}"
    dt_queries.append({"name": qn, "query": {"datasetName": ds,
                                             "parameters": [{"name": "periodo", "keyword": "periodo"}],
                                             "disaggregated": False}})
    dt_fields.append({"parameterName": "periodo", "queryName": qn})

filters = [
    {"widget": {"name": "filtro_warehouse", "queries": wh_queries,
                "spec": {"version": 2, "widgetType": "filter-single-select",
                         "encodings": {"fields": wh_fields},
                         "frame": frame("Warehouse", "Nome | ID")}},
     "position": pos(0, 0, 4, 2)},
    {"widget": {"name": "filtro_periodo", "queries": dt_queries,
                "spec": {"version": 2, "widgetType": "filter-date-range-picker",
                         "encodings": {"fields": dt_fields},
                         "frame": frame("Periodo")}},
     "position": pos(0, 2, 4, 2)},
]

dash = {
    "datasets": datasets,
    "pages": [
        {"name": "visao_geral", "displayName": "Visao geral", "pageType": "PAGE_TYPE_CANVAS",
         "layoutVersion": "GRID_V1", "layout": main},
        {"name": "filtros", "displayName": "Filtros", "pageType": "PAGE_TYPE_GLOBAL_FILTERS",
         "layoutVersion": "GRID_V1", "layout": filters},
    ],
    "uiSettings": {"theme": {
        "canvasBackgroundColor": {"light": "#F7F9FA", "dark": "#1F272D"},
        "widgetBackgroundColor": {"light": "#FFFFFF", "dark": "#11171C"},
        "widgetBorderColor": {"light": "#FFFFFF", "dark": "#11171C"},
        "fontColor": {"light": "#11171C", "dark": "#E8ECF0"},
        "selectionColor": {"light": "#2272B4", "dark": "#8ACAFF"},
        "visualizationColors": ["#2272B4", "#FF7E5C", "#00A972", "#FFAB00", "#6B4FBB", "#5ADBFF", "#99DDB4"],
        "widgetHeaderAlignment": "LEFT",
        "widgetCornerRadius": 8,
    }},
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    json.dump(dash, f, ensure_ascii=False, indent=2)
print(OUT)
