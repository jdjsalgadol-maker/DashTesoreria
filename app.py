"""
Dashboard Ejecutivo — Análisis de Tesorería
=============================================
Reglas de negocio clave:
  - Carga estrictamente manual por sesión (sin persistencia en nube).
  - Neteo de naturalezas contables antes de aplicar valores absolutos.
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# =============================================================================
# 0. CONFIGURACIÓN DE PÁGINA Y ESTILOS
# =============================================================================
st.set_page_config(
    page_title="Dashboard Tesorería - Bancos y Costos Financieros",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

PALETA_VIVA = px.colors.qualitative.Vivid
COLOR_INGRESO = "#00E676"
COLOR_GASTO = "#FF1744"

st.markdown("""
    <style>
    .main-title { font-size: 28px; font-weight: 800; color: #0D47A1; margin-bottom: 5px; }
    .subtitle { font-size: 15px; color: #4B5563; margin-bottom: 20px; font-style: italic; }
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, #0D47A1 0%, #1565C0 100%);
        padding: 16px; border-radius: 12px; box-shadow: 0 2px 8px rgba(13,71,161,0.25);
    }
    div[data-testid="stMetric"] label, div[data-testid="stMetric"] div { color: white !important; }
    .insight-box { background-color: #E3F2FD; padding: 15px; border-left: 5px solid #0D47A1; border-radius: 5px; margin-bottom: 18px; color: #0D3B66;}
    .alert-box   { background-color: #FFF1F0; padding: 15px; border-left: 5px solid #FF1744; border-radius: 5px; margin-bottom: 18px; color: #7F1D1D;}
    </style>
""", unsafe_allow_html=True)

MESES_NOMBRES = {1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
                 7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"}

COL_VALOR = "Importe en ML"
COL_CUENTA = "Nombre cuenta"
COL_BANCO = "Clave referencia 3"
COL_FECHA = "Fe-contab-"

CUENTAS_INGRESO = {"Rendimientos"}

def safe_div(numer, denom):
    if isinstance(denom, pd.Series):
        denom = denom.replace(0, np.nan)
    elif denom == 0:
        denom = np.nan
    return numer / denom

@st.cache_data(show_spinner="Procesando datos de tesorería...")
def load_and_process_data(file_source):
    df = pd.read_excel(file_source, sheet_name=0)
    df.columns = df.columns.astype(str).str.strip()

    faltantes = [c for c in [COL_VALOR, COL_CUENTA, COL_BANCO, COL_FECHA] if c not in df.columns]
    if faltantes:
        st.error(f"⚠️ Error Crítico: no se encontraron las columnas {faltantes} en el archivo.")
        st.stop()

    df[COL_FECHA] = pd.to_datetime(df[COL_FECHA], errors="coerce")
    df = df.dropna(subset=[COL_FECHA]).copy()
    df[COL_VALOR] = pd.to_numeric(df[COL_VALOR], errors="coerce").fillna(0)
    df[COL_CUENTA] = df[COL_CUENTA].fillna("Sin Cuenta")
    df[COL_BANCO] = df[COL_BANCO].fillna("Sin Banco/Tercero Asignado")

    df["Anio"] = df[COL_FECHA].dt.year
    df["Mes_Num"] = df[COL_FECHA].dt.month
    df["Mes_Nombre"] = df["Mes_Num"].map(MESES_NOMBRES)
    df["Periodo"] = df["Anio"].astype(str) + "-" + df["Mes_Num"].astype(str).str.zfill(2)

    return df

def netear(data: pd.DataFrame, dimensiones: list) -> pd.DataFrame:
    neto = data.groupby(dimensiones, as_index=False)[COL_VALOR].sum()
    neto = neto.rename(columns={COL_VALOR: "Neto"})
    neto["Valor"] = neto["Neto"].abs()
    return neto

def linea_tendencia(x_num: np.ndarray, y: np.ndarray):
    if len(x_num) < 2 or np.all(x_num == x_num[0]):
        return None
    coef = np.polyfit(x_num, y, 1)
    return np.polyval(coef, x_num), coef[0]

# =============================================================================
# 1. CARGA DE DATOS ESTRICTA
# =============================================================================
st.sidebar.title("🏦 BI Tesorería")
uploaded_file = st.sidebar.file_uploader("Cargar Base de Datos (.xlsx)", type=["xlsx", "xls"])

if uploaded_file is None:
    st.info("👋 Por favor, carga el archivo base de Excel para iniciar el procesamiento. Los datos se procesan en memoria y no se guardan en la nube.")
    st.stop()

df = load_and_process_data(uploaded_file)

if df.empty:
    st.error("El archivo no contiene movimientos procesables.")
    st.stop()

# =============================================================================
# 2. NAVEGACIÓN PRINCIPAL
# =============================================================================
st.sidebar.markdown("---")
st.sidebar.subheader("Navegación")
menu_opcion = st.sidebar.radio("Ir a:", ["Vista Consolidada", "Análisis por Cuenta"])

# =============================================================================
# 3. VISTA CONSOLIDADA
# =============================================================================
if menu_opcion == "Vista Consolidada":
    st.markdown('<p class="main-title">🏦 Vista Consolidada de Tesorería</p>', unsafe_allow_html=True)
    st.markdown('<p class="subtitle">Panorama general de todas las cuentas y rubros financieros</p>', unsafe_allow_html=True)

    st.sidebar.markdown("---")
    st.sidebar.subheader("📅 Filtros Globales")
    anios_disp = sorted(df["Anio"].dropna().unique())
    anio_sel = st.sidebar.multiselect("Año(s)", anios_disp, default=anios_disp)

    df_f = df[df["Anio"].isin(anio_sel)]

    if df_f.empty:
        st.warning("No hay movimientos para los filtros seleccionados.")
        st.stop()

    por_cuenta_total = netear(df_f, [COL_CUENTA]).set_index(COL_CUENTA)["Neto"]
    ingreso_total = -por_cuenta_total[por_cuenta_total.index.isin(CUENTAS_INGRESO)].sum()
    gasto_total = por_cuenta_total[~por_cuenta_total.index.isin(CUENTAS_INGRESO)].sum()
    resultado_financiero_neto = ingreso_total - gasto_total
    
    c1, c2, c3 = st.columns(3)
    c1.metric("Resultado Financiero Neto", f"${resultado_financiero_neto:,.0f}", "Ganancia" if resultado_financiero_neto >= 0 else "Pérdida")
    c2.metric("Total Gastos Financieros", f"${gasto_total:,.0f}")
    c3.metric("Total Ingresos (Rendimientos)", f"${ingreso_total:,.0f}")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("📊 Distribución por Cuenta")
        df_cuentas = netear(df_f, [COL_CUENTA]).sort_values("Valor", ascending=False)
        fig_cuenta = px.bar(
            df_cuentas, x=COL_CUENTA, y="Valor", color=COL_CUENTA,
            color_discrete_sequence=PALETA_VIVA, text_auto=".2s"
        )
        fig_cuenta.update_layout(showlegend=False, yaxis_title="$ Neto")
        st.plotly_chart(fig_cuenta, use_container_width=True)

    with col2:
        st.subheader("🏦 Bancos por Cuenta")
        df_bancos = netear(df_f, [COL_CUENTA, COL_BANCO])
        df_bancos = df_bancos[df_bancos["Valor"] > 0]
        fig_bancos = px.sunburst(
            df_bancos, path=[COL_CUENTA, COL_BANCO], values="Valor",
            color=COL_CUENTA, color_discrete_sequence=PALETA_VIVA
        )
        st.plotly_chart(fig_bancos, use_container_width=True)

# =============================================================================
# 4. ANÁLISIS ESPECÍFICO POR CUENTA
# =============================================================================
elif menu_opcion == "Análisis por Cuenta":
    st.markdown('<p class="main-title">🔎 Análisis Detallado por Cuenta</p>', unsafe_allow_html=True)
    
    st.sidebar.markdown("---")
    st.sidebar.subheader("Filtros Específicos")
    
    # Selector de cuenta individual
    cuentas_disp = sorted(df[COL_CUENTA].unique())
    cuenta_seleccionada = st.sidebar.selectbox("Seleccione la Cuenta", cuentas_disp)
    
    # Filtros de tiempo para el análisis
    anios_disp = sorted(df["Anio"].dropna().unique())
    anio_sel = st.sidebar.multiselect("Año(s)", anios_disp, default=anios_disp)
    
    meses_disp = sorted(df["Mes_Num"].dropna().unique())
    mes_sel = st.sidebar.multiselect("Mes(es)", options=meses_disp, format_func=lambda x: MESES_NOMBRES[x], default=meses_disp)

    # Aplicar filtros
    df_cuenta = df[(df[COL_CUENTA] == cuenta_seleccionada) & (df["Anio"].isin(anio_sel)) & (df["Mes_Num"].isin(mes_sel))]

    if df_cuenta.empty:
        st.warning(f"No hay movimientos para la cuenta {cuenta_seleccionada} en el periodo seleccionado.")
        st.stop()

    # KPIS de la cuenta
    total_cuenta = netear(df_cuenta, [COL_CUENTA])["Valor"].sum()
    bancos_activos = df_cuenta[COL_BANCO].nunique()
    
    st.markdown(f"### Cuenta analizada: **{cuenta_seleccionada}**")
    c1, c2 = st.columns(2)
    c1.metric("Valor Total Neteado (Filtros actuales)", f"${total_cuenta:,.0f}")
    c2.metric("Terceros / Bancos involucrados", f"{bancos_activos}")

    st.markdown("---")
    col_a, col_b = st.columns(2)
    
    with col_a:
        st.subheader("🏦 Comportamiento por Banco")
        df_bancos_cta = netear(df_cuenta, [COL_BANCO]).sort_values("Valor", ascending=False)
        fig_bancos_cta = px.bar(
            df_bancos_cta, x="Valor", y=COL_BANCO, orientation="h",
            color="Valor", color_continuous_scale="Turbo", text_auto=".2s"
        )
        fig_bancos_cta.update_layout(yaxis_title="", xaxis_title="$ Valor")
        st.plotly_chart(fig_bancos_cta, use_container_width=True)

    with col_b:
        st.subheader("📈 Evolución Temporal y Tendencia")
        df_tend_cta = netear(df_cuenta, ["Periodo"]).sort_values("Periodo")
        fig_tend_cta = go.Figure()
        
        fig_tend_cta.add_trace(go.Scatter(
            x=df_tend_cta["Periodo"], y=df_tend_cta["Valor"], mode="lines+markers",
            line=dict(width=3, color=PALETA_VIVA[1]), marker=dict(size=8), name="Valor Real"
        ))

        # Línea de tendencia
        periodos_ordenados = sorted(df_tend_cta["Periodo"].unique())
        x_map = {p: i for i, p in enumerate(periodos_ordenados)}
        x_num = df_tend_cta["Periodo"].map(x_map).to_numpy(dtype=float)
        y_num = df_tend_cta["Valor"].to_numpy(dtype=float)
        
        res_tendencia = linea_tendencia(x_num, y_num)
        if res_tendencia is not None:
            y_trend, _ = res_tendencia
            fig_tend_cta.add_trace(go.Scatter(
                x=df_tend_cta["Periodo"], y=y_trend, mode="lines",
                line=dict(width=2, color="gray", dash="dot"), name="Tendencia"
            ))
            
        fig_tend_cta.update_layout(yaxis_title="$ Neto")
        st.plotly_chart(fig_tend_cta, use_container_width=True)

    st.markdown("---")
    st.subheader("⚖️ Versus Temporal (Misma Cuenta)")
    st.caption("Compara el rendimiento de esta cuenta entre dos periodos distintos (ej. Q1 vs Q2, o 2024 vs 2025).")
    
    col_v1, col_v2 = st.columns(2)
    periodos_totales = sorted(df[df[COL_CUENTA] == cuenta_seleccionada]["Periodo"].dropna().unique())
    
    with col_v1:
        meses_a = st.multiselect("Periodo A", options=periodos_totales, key="mes_a")
    with col_v2:
        meses_b = st.multiselect("Periodo B", options=periodos_totales, key="mes_b")

    if meses_a and meses_b:
        df_a = df[(df[COL_CUENTA] == cuenta_seleccionada) & (df["Periodo"].isin(meses_a))]
        df_b = df[(df[COL_CUENTA] == cuenta_seleccionada) & (df["Periodo"].isin(meses_b))]

        val_a = netear(df_a, [COL_CUENTA])["Valor"].sum() if not df_a.empty else 0
        val_b = netear(df_b, [COL_CUENTA])["Valor"].sum() if not df_b.empty else 0
        
        variacion = val_b - val_a
        pct = (variacion / val_a * 100) if val_a != 0 else 0

        df_vs = pd.DataFrame({
            "Periodo": [f"Periodo A ({len(meses_a)} meses)", f"Periodo B ({len(meses_b)} meses)"],
            "Valor": [val_a, val_b]
        })
        
        col_graf, col_kpi = st.columns([2, 1])
        with col_graf:
            fig_vs = px.bar(df_vs, x="Periodo", y="Valor", color="Periodo", color_discrete_sequence=[COLOR_INGRESO, "#2979FF"], text_auto=".2s")
            st.plotly_chart(fig_vs, use_container_width=True)
            
        with col_kpi:
            st.metric(label="Variación Total", value=f"${variacion:,.0f}", delta=f"{pct:+.1f}%")
            if variacion > 0:
                st.info("El rubro aumentó respecto al periodo A.")
            elif variacion < 0:
                st.success("El rubro disminuyó respecto al periodo A.")
