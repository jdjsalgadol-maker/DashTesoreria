"""
Dashboard Ejecutivo — Análisis de Tesorería
=============================================
Fuente: extracto contable 'gastos.xlsx' (movimientos de bancos, comisiones,
intereses, gravamen y rendimientos financieros).

Reglas de negocio clave (definidas por el usuario, verificadas contra los
datos reales):
  - Columna 'Importe en ML' (col. I): valor contable. Cada cuenta tiene una
    naturaleza contable distinta (débito/crédito), así que en la data
    conviven positivos y negativos para una misma cuenta o banco.
  - NUNCA se debe tomar valor absoluto fila por fila (eso infla artificialmente
    los totales al tratar débitos y créditos que se cancelan entre sí como si
    fueran dos gastos distintos). La regla correcta es: primero NETEAR
    (sumar con signo) por la dimensión de interés, y solo AL FINAL aplicar
    valor absoluto sobre el neto — así el signo contable no distorsiona las
    gráficas, pero tampoco se pierde información por cancelación.
  - Columna 'Nombre cuenta' (col. L): la cuenta contable (Rendimientos,
    Comisiones, Gravamen, Intereses, Gastos bancarios).
  - Columna 'Clave referencia 3' (col. B en el archivo real — ver nota
    abajo): nombre del banco/tercero contraparte del movimiento.

Nota de corrección: el dashboard de referencia entregado por el usuario
etiquetaba esta columna como "columna C", pero al inspeccionar el archivo,
el texto del banco/tercero está en la columna B ('Clave referencia 3'); la
columna C real ('Clave ref.1') es un código numérico, no un nombre. La
variable de datos usada aquí es la correcta (los valores de banco), solo se
corrige la etiqueta.
"""

from pathlib import Path

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
    .warn-box    { background-color: #FFFBEB; padding: 15px; border-left: 5px solid #F59E0B; border-radius: 5px; margin-bottom: 18px; color: #78350F;}
    </style>
""", unsafe_allow_html=True)

MESES_NOMBRES = {1: "Ene", 2: "Feb", 3: "Mar", 4: "Abr", 5: "May", 6: "Jun",
                 7: "Jul", 8: "Ago", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dic"}

COL_VALOR = "Importe en ML"
COL_CUENTA = "Nombre cuenta"
COL_BANCO = "Clave referencia 3"
COL_FECHA = "Fe-contab-"

# Cuentas que representan INGRESO financiero (naturaleza contraria al resto).
# Se usa solo para el KPI de "Costo Financiero Neto"; el resto del dashboard
# trata todas las cuentas de forma simétrica.
CUENTAS_INGRESO = {"Rendimientos"}


def find_default_excel():
    """Busca un .xlsx/.xls primero en data/raw/ y luego en el directorio de
    trabajo actual, para no depender de dónde se ejecute `streamlit run`."""
    for carpeta in (Path("data/raw"), Path(".")):
        if carpeta.exists():
            encontrados = sorted(f for f in carpeta.glob("*.xls*") if not f.name.startswith("~$"))
            if encontrados:
                return encontrados[0]
    return None


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
    df["Periodo"] = df["Anio"].astype(str) + "-" + df["Mes_Num"].astype(str).str.zfill(2)

    return df


def netear(data: pd.DataFrame, dimensiones: list) -> pd.DataFrame:
    """Suma CON SIGNO por las dimensiones dadas (netea débitos/créditos) y
    solo al final expone el valor absoluto — ver docstring del módulo."""
    neto = data.groupby(dimensiones, as_index=False)[COL_VALOR].sum()
    neto = neto.rename(columns={COL_VALOR: "Neto"})
    neto["Valor"] = neto["Neto"].abs()
    return neto


def linea_tendencia(x_num: np.ndarray, y: np.ndarray):
    """Regresión lineal simple (mínimos cuadrados) sin depender de
    statsmodels — mantiene el despliegue liviano para Streamlit Cloud."""
    if len(x_num) < 2 or np.all(x_num == x_num[0]):
        return None
    coef = np.polyfit(x_num, y, 1)
    return np.polyval(coef, x_num), coef[0]


# =============================================================================
# 1. CARGA DE DATOS
# =============================================================================
st.sidebar.title("🏦 BI Tesorería")
uploaded_file = st.sidebar.file_uploader("Actualizar Data (.xlsx)", type=["xlsx", "xls"])

if uploaded_file is not None:
    df = load_and_process_data(uploaded_file)
else:
    archivo_default = find_default_excel()
    if archivo_default is None:
        st.warning("⚠️ Se requiere un archivo Excel para inicializar el sistema. "
                   "Cárgalo en la barra lateral o colócalo en `data/raw/`.")
        st.stop()
    df = load_and_process_data(str(archivo_default))

if df.empty:
    st.error("El archivo no contiene movimientos procesables.")
    st.stop()

# =============================================================================
# 2. FILTROS GLOBALES
# =============================================================================
st.sidebar.markdown("---")
st.sidebar.subheader("📅 Filtros Globales")

anios_disp = sorted(df["Anio"].dropna().unique())
anio_sel = st.sidebar.multiselect("Año(s)", anios_disp, default=anios_disp)

cuentas_disp = sorted(df[COL_CUENTA].unique())
cuenta_sel = st.sidebar.multiselect("Cuenta(s)", cuentas_disp, default=cuentas_disp)

bancos_disp = sorted(df[COL_BANCO].unique())
banco_sel = st.sidebar.multiselect("Banco / Tercero", bancos_disp, default=bancos_disp)

df_f = df[df["Anio"].isin(anio_sel) & df[COL_CUENTA].isin(cuenta_sel) & df[COL_BANCO].isin(banco_sel)]

st.markdown('<p class="main-title">🏦 Análisis de Tesorería — Cuentas y Bancos</p>', unsafe_allow_html=True)
st.markdown('<p class="subtitle">Movimientos bancarios, comisiones, intereses, gravamen y rendimientos financieros</p>', unsafe_allow_html=True)

if df_f.empty:
    st.warning("No hay movimientos para los filtros seleccionados. Ajusta año, cuenta o banco en la barra lateral.")
    st.stop()

# =============================================================================
# 3. KPIS MAESTROS
# =============================================================================
por_cuenta_total = netear(df_f, [COL_CUENTA]).set_index(COL_CUENTA)["Neto"]
ingreso_total = -por_cuenta_total[por_cuenta_total.index.isin(CUENTAS_INGRESO)].sum()  # neto negativo -> ingreso positivo
gasto_total = por_cuenta_total[~por_cuenta_total.index.isin(CUENTAS_INGRESO)].sum()
resultado_financiero_neto = ingreso_total - gasto_total  # positivo = ganancia neta, negativo = pérdida neta
n_bancos = df_f[COL_BANCO].nunique()
n_movimientos = len(df_f)

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Resultado Financiero Neto", f"${resultado_financiero_neto:,.0f}",
          "Ganancia neta" if resultado_financiero_neto >= 0 else "Pérdida neta")
c2.metric("Gastos Financieros (Com+Int+Grav+Otros)", f"${gasto_total:,.0f}")
c3.metric("Ingresos Financieros (Rendimientos)", f"${ingreso_total:,.0f}")
c4.metric("Bancos / Terceros activos", f"{n_bancos}")
c5.metric("Movimientos analizados", f"{n_movimientos:,}")

banco_mas_costoso = netear(df_f[~df_f[COL_CUENTA].isin(CUENTAS_INGRESO)], [COL_BANCO]).sort_values(
    "Valor", ascending=False)
cuenta_mayor_peso = netear(df_f, [COL_CUENTA]).sort_values("Valor", ascending=False)

if not banco_mas_costoso.empty and not cuenta_mayor_peso.empty:
    top_banco = banco_mas_costoso.iloc[0]
    top_cuenta = cuenta_mayor_peso.iloc[0]
    pct_cuenta = safe_div(top_cuenta["Valor"], cuenta_mayor_peso["Valor"].sum()) * 100
    pct_banco = safe_div(top_banco["Valor"], banco_mas_costoso["Valor"].sum()) * 100
    st.markdown(f"""
    <div class="insight-box">
        💡 <b>Lectura del periodo:</b> la cuenta con mayor peso es <b>{top_cuenta[COL_CUENTA]}</b>
        (${top_cuenta['Valor']:,.0f}, {pct_cuenta:.1f}% del total analizado). El banco/tercero que más
        concentra costos financieros es <b>{top_banco[COL_BANCO]}</b> (${top_banco['Valor']:,.0f},
        {pct_banco:.1f}% de los gastos financieros).
    </div>
    """, unsafe_allow_html=True)

st.markdown("---")

# =============================================================================
# 4. ANÁLISIS POR CUENTA Y DESGLOSE POR BANCO
# =============================================================================
col1, col2 = st.columns(2)

with col1:
    st.subheader("📊 Análisis por Cuenta")
    df_cuentas = netear(df_f, [COL_CUENTA]).sort_values("Valor", ascending=False)
    fig_cuenta = px.bar(
        df_cuentas, x=COL_CUENTA, y="Valor", color=COL_CUENTA,
        color_discrete_sequence=PALETA_VIVA, text_auto=".2s",
        title="Valor neteado (siempre positivo) por cuenta contable",
    )
    fig_cuenta.update_layout(showlegend=False, yaxis_title="$ Neto")
    st.plotly_chart(fig_cuenta, use_container_width=True)

with col2:
    st.subheader("🏦 Desglose de Bancos por Cuenta")
    df_bancos = netear(df_f, [COL_CUENTA, COL_BANCO])
    df_bancos = df_bancos[df_bancos["Valor"] > 0]
    if df_bancos.empty:
        st.info("Sin datos para desglosar con los filtros actuales.")
    else:
        fig_bancos = px.sunburst(
            df_bancos, path=[COL_CUENTA, COL_BANCO], values="Valor",
            color=COL_CUENTA, color_discrete_sequence=PALETA_VIVA,
            title="Participación de cada banco dentro de cada cuenta",
        )
        st.plotly_chart(fig_bancos, use_container_width=True)

st.markdown("---")

# =============================================================================
# 5. RANKING DE BANCOS
# =============================================================================
st.subheader("🏆 Ranking de Bancos por Costo Financiero")
df_gastos_bancos = df_f[~df_f[COL_CUENTA].isin(CUENTAS_INGRESO)]
top_n = st.slider("Mostrar top N bancos/terceros", 5, min(30, n_bancos) if n_bancos > 5 else 5,
                  min(10, n_bancos))
ranking_bancos = netear(df_gastos_bancos, [COL_BANCO]).sort_values("Valor", ascending=False).head(top_n)

if ranking_bancos.empty:
    st.info("Sin datos de costos por banco para los filtros seleccionados.")
else:
    fig_rank = px.bar(
        ranking_bancos.sort_values("Valor"), x="Valor", y=COL_BANCO, orientation="h",
        color="Valor", color_continuous_scale="Turbo", text_auto=".2s",
        title=f"Top {top_n} bancos/terceros por costo financiero acumulado",
    )
    fig_rank.update_layout(xaxis_title="$ Costo Financiero", yaxis_title="")
    st.plotly_chart(fig_rank, use_container_width=True)

st.markdown("---")

# =============================================================================
# 6. TENDENCIA TEMPORAL (con línea de tendencia OLS manual)
# =============================================================================
st.subheader("📈 Tendencia Temporal por Cuenta")
df_tendencia = netear(df_f, ["Periodo", COL_CUENTA]).sort_values("Periodo")

fig_tendencia = go.Figure()
periodos_ordenados = sorted(df_tendencia["Periodo"].unique())
x_map = {p: i for i, p in enumerate(periodos_ordenados)}

for i, cuenta in enumerate(sorted(df_tendencia[COL_CUENTA].unique())):
    sub = df_tendencia[df_tendencia[COL_CUENTA] == cuenta].sort_values("Periodo")
    color = PALETA_VIVA[i % len(PALETA_VIVA)]
    fig_tendencia.add_trace(go.Scatter(
        x=sub["Periodo"], y=sub["Valor"], mode="lines+markers", name=cuenta,
        line=dict(width=2.5, color=color), marker=dict(size=7),
    ))
    x_num = sub["Periodo"].map(x_map).to_numpy(dtype=float)
    y_num = sub["Valor"].to_numpy(dtype=float)
    resultado = linea_tendencia(x_num, y_num)
    if resultado is not None:
        y_trend, pendiente = resultado
        fig_tendencia.add_trace(go.Scatter(
            x=sub["Periodo"], y=y_trend, mode="lines", name=f"Tendencia {cuenta}",
            line=dict(width=2, color=color, dash="dot"), showlegend=False,
        ))

fig_tendencia.update_layout(
    height=460, title="Comportamiento del saldo neto con líneas de tendencia",
    yaxis_title="$ Neto", legend_title="Cuenta",
)
st.plotly_chart(fig_tendencia, use_container_width=True)

# Insight de tendencia: qué cuenta sube más rápido
tendencias = []
for cuenta in df_tendencia[COL_CUENTA].unique():
    sub = df_tendencia[df_tendencia[COL_CUENTA] == cuenta].sort_values("Periodo")
    if len(sub) >= 2:
        x_num = sub["Periodo"].map(x_map).to_numpy(dtype=float)
        y_num = sub["Valor"].to_numpy(dtype=float)
        resultado = linea_tendencia(x_num, y_num)
        if resultado is not None:
            _, pendiente = resultado
            tendencias.append((cuenta, pendiente))

if tendencias:
    cuenta_sube, pend_sube = max(tendencias, key=lambda t: t[1])
    cuenta_baja, pend_baja = min(tendencias, key=lambda t: t[1])
    if pend_sube > 0:
        st.markdown(f"""
        <div class="alert-box">
            🚨 <b>Tendencia al alza:</b> la cuenta <b>{cuenta_sube}</b> muestra la pendiente más
            pronunciada al alza (~${pend_sube:,.0f} adicionales por mes en promedio). Si es un rubro
            de costo, amerita revisión con el banco o el área responsable.
        </div>
        """, unsafe_allow_html=True)
    if pend_baja < 0:
        st.markdown(f"""
        <div class="insight-box">
            ✅ <b>Tendencia a la baja:</b> la cuenta <b>{cuenta_baja}</b> muestra la mayor reducción
            mensual promedio (~${abs(pend_baja):,.0f} menos por mes).
        </div>
        """, unsafe_allow_html=True)

st.markdown("---")

# =============================================================================
# 7. VERSUS TEMPORAL (COMPARADOR DE PERIODOS)
# =============================================================================
st.subheader("⚖️ Versus Temporal — Comparativa de Periodos")
st.caption("Selecciona uno o varios meses para cada periodo — puedes comparar un mes puntual, "
           "un trimestre, o el mismo mes en dos años distintos.")

col_a, col_b = st.columns(2)
periodos_disp = sorted(df_f["Periodo"].dropna().unique())
with col_a:
    st.markdown("**Periodo A**")
    meses_a = st.multiselect("Meses Periodo A", options=periodos_disp, key="mes_a")
with col_b:
    st.markdown("**Periodo B**")
    meses_b = st.multiselect("Meses Periodo B", options=periodos_disp, key="mes_b")

if meses_a and meses_b:
    df_a = df_f[df_f["Periodo"].isin(meses_a)]
    df_b = df_f[df_f["Periodo"].isin(meses_b)]

    neto_a = netear(df_a, [COL_CUENTA]).rename(columns={"Valor": "Periodo A"})[[COL_CUENTA, "Periodo A"]]
    neto_b = netear(df_b, [COL_CUENTA]).rename(columns={"Valor": "Periodo B"})[[COL_CUENTA, "Periodo B"]]
    comp = pd.merge(neto_a, neto_b, on=COL_CUENTA, how="outer").fillna(0)
    comp["Variación $"] = comp["Periodo B"] - comp["Periodo A"]
    comp["Variación %"] = comp.apply(lambda r: safe_div(r["Variación $"], r["Periodo A"]) * 100, axis=1)

    df_vs = pd.melt(comp, id_vars=[COL_CUENTA], value_vars=["Periodo A", "Periodo B"],
                    var_name="Etiqueta", value_name="Valor")
    fig_vs = px.bar(
        df_vs, x=COL_CUENTA, y="Valor", color="Etiqueta", barmode="group",
        color_discrete_sequence=[COLOR_INGRESO, "#2979FF"],
        title=f"Comparativa: {', '.join(meses_a)} vs {', '.join(meses_b)}",
    )
    st.plotly_chart(fig_vs, use_container_width=True)

    st.dataframe(comp.style.format({
        "Periodo A": "${:,.0f}", "Periodo B": "${:,.0f}",
        "Variación $": "${:+,.0f}", "Variación %": "{:+.1f}%",
    }, na_rep="—").background_gradient(subset=["Variación %"], cmap="RdYlGn_r"), use_container_width=True)

    mayor_var = comp.reindex(comp["Variación $"].abs().sort_values(ascending=False).index).iloc[0]
    direccion = "aumentó" if mayor_var["Variación $"] > 0 else "disminuyó"
    st.markdown(f"""
    <div class="insight-box">
        💡 <b>Mayor variación:</b> la cuenta <b>{mayor_var[COL_CUENTA]}</b> {direccion} en
        ${abs(mayor_var['Variación $']):,.0f} ({mayor_var['Variación %']:+.1f}%) entre los dos periodos
        comparados.
    </div>
    """, unsafe_allow_html=True)
else:
    st.info("Selecciona al menos un mes en cada periodo (A y B) para ver la comparación.")
