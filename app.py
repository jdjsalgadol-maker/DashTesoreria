"""
DASHBOARD EJECUTIVO — TESORERIA Y BANCOS
==================================================================================================
Fusiona la lógica contable de neteo (Tesorería) con el diseño de alto impacto visual y 
diagnósticos de texto automático (arquitectura app_2.py).
"""

import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# =============================================================================
# 0. CONFIGURACIÓN DE PÁGINA Y ESTILOS AVANZADOS
# =============================================================================
st.set_page_config(
    page_title="Dashboard Ejecutivo - Tesorería",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
    <style>
    .titulo-principal { font-size: 26px; font-weight: 800; color: #1E3A8A; margin-bottom: 5px; }
    .subtitulo { font-size: 15px; color: #4B5563; margin-bottom: 20px; font-style: italic; }
    div[data-testid="stMetric"] {
        background-color: #F8FAFC; padding: 15px; border-radius: 8px;
        border-left: 5px solid #1E3A8A; box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    .caja-info    { background-color: #F0F9FF; padding: 15px; border-left: 5px solid #0284C7; border-radius: 5px; margin-bottom: 20px; color: #075985; font-size: 14px;}
    .caja-alerta  { background-color: #FEF2F2; padding: 15px; border-left: 5px solid #EF4444; border-radius: 5px; margin-bottom: 20px; color: #7F1D1D;}
    .caja-exito   { background-color: #ECFDF5; padding: 15px; border-left: 5px solid #10B981; border-radius: 5px; margin-bottom: 20px; color: #064E3B;}
    </style>
""", unsafe_allow_html=True)

PALETA = ["#1E3A8A", "#0EA5E9", "#F59E0B", "#EF4444", "#10B981", "#8B5CF6", "#14B8A6"]
px.defaults.color_discrete_sequence = PALETA

NOMBRES_MESES = {1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
                 7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"}

COL_VALOR = 'Importe en ML'
COL_CUENTA = 'Nombre cuenta'
COL_BANCO = 'Clave referencia 3'
COL_FECHA = 'Fe-contab-'
CUENTAS_INGRESO = {"Rendimientos"} # Cuentas que suman positivamente al resultado

# =============================================================================
# 1. FUNCIONES CORE: ESTILOS PLOTLY Y DATOS
# =============================================================================
def estilizar_grafico(fig, titulo, subtitulo="", altura=430, leyenda_derecha=False):
    texto_titulo = f"{titulo}"
    if subtitulo:
        texto_titulo += f"<br><span style='font-size:13px;color:#6B7280;font-weight:normal'>{subtitulo}</span>"
    fig.update_layout(
        title={"text": texto_titulo, "x": 0.02, "xanchor": "left"},
        height=altura, margin=dict(t=95, l=10, r=10, b=10),
        plot_bgcolor="white", paper_bgcolor="white",
        font=dict(family="Arial", size=13, color="#1F2937"),
    )
    if leyenda_derecha:
        fig.update_layout(legend=dict(orientation="v", yanchor="top", y=0.98, xanchor="left", x=1.02), margin=dict(r=140))
    else:
        fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=1.10, xanchor="center", x=0.5))
    fig.update_xaxes(showgrid=False, showline=True, linecolor="#D1D5DB")
    fig.update_yaxes(showgrid=True, gridcolor="#F1F5F9", zeroline=False)
    return fig

def medidor_kpi(valor, referencia, titulo):
    color_delta = "#EF4444" if valor > referencia else "#10B981"
    rango_max = max(valor, referencia) * 1.3 if max(valor, referencia) > 0 else 1
    fig = go.Figure(go.Indicator(
        mode="gauge+number+delta", value=valor,
        number={"prefix": "$", "valueformat": ",.0f"},
        delta={"reference": referencia, "valueformat": ",.0f", "increasing": {"color": "#EF4444"}, "decreasing": {"color": "#10B981"}},
        gauge={"axis": {"range": [0, rango_max]}, "bar": {"color": color_delta},
               "threshold": {"line": {"color": "#1E3A8A", "width": 4}, "value": referencia}},
        title={"text": titulo, "font": {"size": 14}},
    ))
    fig.update_layout(height=280, margin=dict(t=60, l=30, r=30, b=10))
    return fig

def grafico_cascada(df_vif, costo_base, costo_actual, titulo, subtitulo=""):
    df_ord = df_vif.reindex(df_vif["Impacto ($)"].abs().sort_values(ascending=False).index).copy()
    
    medidas = ["absolute"] + ["relative"] * len(df_ord) + ["total"]
    etiquetas = ["Periodo Base"] + df_ord["Cuenta"].tolist() + ["Periodo Actual"]
    valores = [costo_base] + df_ord["Impacto ($)"].tolist() + [costo_actual]
    textos = ([f"${costo_base:,.0f}"] + [f"{'+' if v >= 0 else ''}${v:,.0f}" for v in df_ord["Impacto ($)"]] + [f"${costo_actual:,.0f}"])

    fig = go.Figure(go.Waterfall(
        orientation="v", measure=medidas, x=etiquetas, y=valores, text=textos, textposition="outside",
        connector={"line": {"color": "#CBD5E1", "width": 1.5, "dash": "dot"}},
        increasing={"marker": {"color": "#EF4444"}}, decreasing={"marker": {"color": "#10B981"}},
        totals={"marker": {"color": "#1E3A8A"}}, width=0.6,
    ))
    return estilizar_grafico(fig, titulo, subtitulo, altura=450)

@st.cache_data
def load_and_process_data(file_source):
    df = pd.read_excel(file_source)
    df.columns = df.columns.astype(str).str.strip()
    df[COL_FECHA] = pd.to_datetime(df[COL_FECHA], errors="coerce")
    df = df.dropna(subset=[COL_FECHA]).copy()
    df[COL_VALOR] = pd.to_numeric(df[COL_VALOR], errors="coerce").fillna(0)
    df[COL_CUENTA] = df[COL_CUENTA].fillna("Sin Cuenta")
    df[COL_BANCO] = df[COL_BANCO].fillna("Sin Banco/Tercero")

    df["Anio"] = df[COL_FECHA].dt.year
    df["Mes_Num"] = df[COL_FECHA].dt.month
    df["Periodo"] = df["Anio"].astype(str) + "-" + df["Mes_Num"].astype(str).str.zfill(2)
    return df

def netear(data, dimensiones):
    """Regla de Negocio: Suma con signo para anular débitos/créditos de la misma cuenta, luego aplica Absoluto para análisis visual."""
    neto = data.groupby(dimensiones, as_index=False)[COL_VALOR].sum()
    neto["Neto_Real"] = neto[COL_VALOR]
    neto[COL_VALOR] = neto[COL_VALOR].abs()
    return neto

def division_segura(num, den): return num / den if den != 0 else 0

# =============================================================================
# 2. MOTOR LINGÜÍSTICO (DIAGNÓSTICOS)
# =============================================================================
def diagnostico_consolidado(df_vif, vol_base, vol_actual, p_base, p_actual):
    var_vol = vol_actual - vol_base
    pct_var = division_segura(var_vol, vol_base) * 100
    
    if df_vif.empty: return ""
    df_ord = df_vif.sort_values(by="Impacto ($)", ascending=False)
    mayor_impacto = df_ord.iloc[0]
    
    caja = "caja-alerta" if var_vol > 0 else "caja-exito"
    tendencia = "se incrementó 📈" if var_vol > 0 else "se redujo 📉"
    
    html = f"""
    <div class="{caja}"><b>📊 Situación Actual:</b><br>
    El volumen total de movimientos netos <b>{tendencia} en ${abs(var_vol):,.0f} ({pct_var:+.1f}%)</b> 
    entre {p_base} y {p_actual}. El rubro que más impulsó el crecimiento del volumen fue <b>{mayor_impacto['Cuenta']}</b> 
    con un aporte de ${mayor_impacto['Impacto ($)']:,.0f}.</div>
    
    <div class="caja-info"><b>🚀 Acciones Sugeridas:</b><br>
    Auditar de inmediato la cuenta <b>{mayor_impacto['Cuenta']}</b>. Si corresponde a gastos bancarios o comisiones, 
    revisar el simulador predictivo para calcular metas de ahorro renegociando las tarifas con la entidad bancaria.</div>
    """
    return html

# =============================================================================
# 3. INTERFAZ Y BARRA LATERAL
# =============================================================================
st.sidebar.title("🏦 BI Tesorería")
archivo_subido = st.sidebar.file_uploader("Actualizar Data (.xlsx)", type=["xlsx", "xls"])

if archivo_subido is None:
    st.info("👋 Por favor, carga el archivo base de Excel para iniciar el procesamiento.")
    st.stop()

df = load_and_process_data(archivo_subido)
anios_disp = sorted(df["Anio"].unique(), reverse=True)

st.sidebar.markdown("---")
st.sidebar.subheader("📅 Control Temporal")
modo_analisis = st.sidebar.radio("Enfoque Analítico:", ["⚖️ Comparativo (Mes VS Mes)", "📈 Rango Histórico (Evolución)"])

def selector_periodo(titulo, prefijo_clave, opciones_anio, mes_invertido=False):
    st.sidebar.markdown(f"**{titulo}:**")
    c1, c2 = st.sidebar.columns(2)
    anio = c1.selectbox("Año", opciones_anio, key=f"{prefijo_clave}_anio")
    meses_disp = sorted(df[df["Anio"] == anio]["Mes_Num"].unique(), reverse=mes_invertido)
    mes = c2.selectbox("Mes", meses_disp, format_func=lambda x: NOMBRES_MESES.get(x, str(x)), key=f"{prefijo_clave}_mes")
    return f"{anio}-{str(mes).zfill(2)}"

if modo_analisis == "⚖️ Comparativo (Mes VS Mes)":
    p_base = selector_periodo("Periodo Base", "base", anios_disp)
    p_actual = selector_periodo("Periodo Actual", "actual", anios_disp, mes_invertido=True)
    texto_contexto = f"Comparativa Estratégica: **{p_actual}** VS **{p_base}**"
else:
    p_base = selector_periodo("Inicio del rango", "ini", sorted(anios_disp))
    p_actual = selector_periodo("Fin del rango", "fin", anios_disp, mes_invertido=True)
    texto_contexto = f"Evolución Histórica: **{min(p_base, p_actual)}** a **{max(p_base, p_actual)}**"

rango_inicio, rango_fin = min(p_base, p_actual), max(p_base, p_actual)
df_rango = df[(df["Periodo"] >= rango_inicio) & (df["Periodo"] <= rango_fin)].sort_values("Periodo")

st.sidebar.markdown("---")
menu = st.sidebar.radio(
    "Seleccione la Página del Informe:",
    [
        "1. Resumen Consolidado",
        "2. Análisis Evolutivo por Cuenta",
        "3. Matriz de Costos por Banco",
    ],
)

# =============================================================================
# PÁGINA 1: RESUMEN CONSOLIDADO (CON CASCADA Y KPIS)
# =============================================================================
if menu == "1. Resumen Consolidado":
    st.markdown('<p class="titulo-principal">1. RESUMEN CONSOLIDADO DE TESORERÍA</p>', unsafe_allow_html=True)
    st.markdown(f'<p class="subtitulo">{texto_contexto}</p>', unsafe_allow_html=True)

    if p_base == p_actual and modo_analisis == "⚖️ Comparativo (Mes VS Mes)":
        st.warning("⚠️ Selecciona un periodo Base diferente al Actual para ver la comparativa.")
        st.stop()

    df_base = netear(df[df["Periodo"] == p_base], [COL_CUENTA])
    df_actual = netear(df[df["Periodo"] == p_actual], [COL_CUENTA])
    
    vol_base = df_base[COL_VALOR].sum() if not df_base.empty else 0
    vol_actual = df_actual[COL_VALOR].sum() if not df_actual.empty else 0
    
    # Motor de Cascada (Variación por cuenta)
    df_vif = pd.merge(df_base, df_actual, on=COL_CUENTA, how="outer", suffixes=("_base", "_actual")).fillna(0)
    df_vif["Impacto ($)"] = df_vif[f"{COL_VALOR}_actual"] - df_vif[f"{COL_VALOR}_base"]
    df_vif = df_vif.rename(columns={COL_CUENTA: "Cuenta"})
    df_vif = df_vif[df_vif["Impacto ($)"] != 0]

    st.markdown(diagnostico_consolidado(df_vif, vol_base, vol_actual, p_base, p_actual), unsafe_allow_html=True)

    c1, c2 = st.columns([1, 1])
    with c1:
        gauge = medidor_kpi(vol_actual, vol_base, f"Volumen Transaccional: {p_actual} vs {p_base}")
        st.plotly_chart(gauge, use_container_width=True)
    with c2:
        fig_cascada = grafico_cascada(df_vif, vol_base, vol_actual, "Puente de Variación por Cuenta", f"De {p_base} a {p_actual}")
        st.plotly_chart(fig_cascada, use_container_width=True)

    st.subheader("📋 Matriz Evolutiva del Rango")
    df_matriz = netear(df_rango, ["Periodo", COL_CUENTA])
    pivot = pd.pivot_table(df_matriz, values=COL_VALOR, index="Periodo", columns=COL_CUENTA, aggfunc="sum").fillna(0)
    st.dataframe(pivot.style.format("${:,.0f}").background_gradient(cmap="Blues", axis=0), use_container_width=True)

# =============================================================================
# PÁGINA 2: ANÁLISIS EVOLUTIVO POR CUENTA Y SIMULADOR PREDICTIVO
# =============================================================================
elif menu == "2. Análisis Evolutivo por Cuenta":
    st.markdown('<p class="titulo-principal">2. EVOLUCIÓN DETALLADA POR CUENTA</p>', unsafe_allow_html=True)
    st.markdown(f'<p class="subtitulo">{texto_contexto}</p>', unsafe_allow_html=True)

    cuentas_disp = sorted(df_rango[COL_CUENTA].unique())
    cuenta_sel = st.selectbox("Filtre la cuenta a analizar:", cuentas_disp)
    
    df_cta = df_rango[df_rango[COL_CUENTA] == cuenta_sel]
    df_tendencia = netear(df_cta, ["Periodo", COL_BANCO])

    val_base = df_tendencia[df_tendencia["Periodo"] == p_base][COL_VALOR].sum()
    val_actual = df_tendencia[df_tendencia["Periodo"] == p_actual][COL_VALOR].sum()
    pct_var = division_segura(val_actual - val_base, val_base) * 100

    html_diagnostico = f"""
    <div class="caja-info"><b>📊 Diagnóstico de la Cuenta ({cuenta_sel}):</b><br>
    El volumen neto operado varió un <b>{pct_var:+.1f}%</b> entre el periodo base y el actual. 
    Revise las barras inferiores para identificar qué entidad bancaria absorbe el mayor peso de esta cuenta en el tiempo.</div>
    """
    st.markdown(html_diagnostico, unsafe_allow_html=True)

    fig_bar = px.bar(df_tendencia, x="Periodo", y=COL_VALOR, color=COL_BANCO, barmode="stack", text_auto=".2s")
    estilizar_grafico(fig_bar, f"Comportamiento de {cuenta_sel} por Entidad", "Volúmenes mensuales")
    fig_bar.update_yaxes(title_text="$ Valor Neteado")
    st.plotly_chart(fig_bar, use_container_width=True)

    st.markdown("---")
    st.subheader("🎯 Simulador Predictivo (Gestión del Gasto)")
    st.caption("Simule escenarios de optimización sobre el **Periodo Actual** para proyectar ahorros en presupuestos futuros.")
    
    col_sim1, col_sim2 = st.columns([1, 2])
    with col_sim1:
        st.markdown("**Variables de Optimización**")
        reduccion_tarifas = st.number_input(f"Negociar reducción de tarifa en {cuenta_sel} (%)", min_value=0.0, max_value=100.0, value=5.0, step=1.0)
        
        costo_proyectado = val_actual * (1 - (reduccion_tarifas/100))
        ahorro = val_actual - costo_proyectado
        
    with col_sim2:
        fig_simulador = go.Figure(go.Bar(
            x=["Volumen Actual", "Volumen Proyectado"], y=[val_actual, costo_proyectado],
            text=[f"${val_actual:,.0f}", f"${costo_proyectado:,.0f}"], textposition="outside",
            marker_color=[PALETA[3], PALETA[4]]
        ))
        estilizar_grafico(fig_simulador, "Proyección de Optimización", altura=320)
        st.plotly_chart(fig_simulador, use_container_width=True)
    
    st.success(f"🚀 **Proyección Estratégica:** Al reducir un {reduccion_tarifas}% las salidas asociadas a {cuenta_sel}, el costo proyectado caería a **${costo_proyectado:,.0f}**, representando un ahorro directo al flujo de caja de **${ahorro:,.0f}** mensual.")

# =============================================================================
# PÁGINA 3: MATRIZ DE COSTOS POR BANCO
# =============================================================================
elif menu == "3. Matriz de Costos por Banco":
    st.markdown('<p class="titulo-principal">3. ESTRUCTURA OPERATIVA POR TERCEROS / BANCOS</p>', unsafe_allow_html=True)
    st.markdown(f'<p class="subtitulo">Análisis focalizado en el periodo actual: <b>{p_actual}</b></p>', unsafe_allow_html=True)
    
    df_actual = netear(df_rango[df_rango["Periodo"] == p_actual], [COL_BANCO, COL_CUENTA])
    
    if df_actual.empty:
        st.warning("No hay datos para el periodo seleccionado.")
        st.stop()

    totales_banco = df_actual.groupby(COL_BANCO)[COL_VALOR].sum().sort_values(ascending=False)
    banco_top = totales_banco.index[0]
    participacion = division_segura(totales_banco.iloc[0], totales_banco.sum()) * 100
    
    st.markdown(f"""
        <div class="caja-alerta">
            <b>📊 Alerta de Concentración:</b><br>
            En el mes de <b>{p_actual}</b>, la entidad <b>{banco_top}</b> concentra el <b>{participacion:.1f}%</b> 
            del volumen neto operado (${totales_banco.iloc[0]:,.0f}). Evaluar si esta concentración operativa representa un 
            riesgo transaccional o una oportunidad para renegociar las tasas corporativas por volumen.
        </div>
    """, unsafe_allow_html=True)

    col1, col2 = st.columns([1.3, 1])
    with col1:
        # Treemap
        fig_treemap = px.treemap(df_actual, path=[COL_BANCO, COL_CUENTA], values=COL_VALOR,
                                 color=COL_VALOR, color_continuous_scale="RdYlGn_r")
        estilizar_grafico(fig_treemap, "Distribución de Cuentas por Entidad Bancaria", "Tamaño y Color = Volumen", altura=450)
        st.plotly_chart(fig_treemap, use_container_width=True)
    with col2:
        # Gráfico de barras horizontal
        df_ord = df_actual.groupby(COL_BANCO, as_index=False)[COL_VALOR].sum().sort_values(COL_VALOR)
        fig_barras = go.Figure(go.Bar(
            x=df_ord[COL_VALOR], y=df_ord[COL_BANCO], orientation="h",
            marker_color=PALETA[1], text=df_ord[COL_VALOR].map(lambda v: f"${v:,.0f}"), textposition="outside"
        ))
        estilizar_grafico(fig_barras, "Volumen Total por Entidad", altura=450)
        st.plotly_chart(fig_barras, use_container_width=True)
        
    st.subheader("📋 Matriz Detallada Banco / Cuenta")
    pivot_bco_cta = pd.pivot_table(df_actual, values=COL_VALOR, index=COL_BANCO, columns=COL_CUENTA, aggfunc='sum').fillna(0)
    pivot_bco_cta["Total Entidad"] = pivot_bco_cta.sum(axis=1)
    pivot_bco_cta = pivot_bco_cta.sort_values("Total Entidad", ascending=False)
    
    st.dataframe(pivot_bco_cta.style.format("${:,.0f}").background_gradient(cmap="Oranges", axis=1), use_container_width=True)
