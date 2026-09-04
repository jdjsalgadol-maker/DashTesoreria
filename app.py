import streamlit as st
import pandas as pd
import plotly.express as px
import numpy as np

# =============================================================================
# 0. CONFIGURACIÓN DE PÁGINA Y ESTILOS CSS (Estilo Imagen Referencia)
# =============================================================================
st.set_page_config(page_title="Dashboard Tesorería", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    /* Estilos para textos analíticos */
    .box-situacion { 
        background-color: #F0FDF4; border-left: 5px solid #22C55E; 
        padding: 15px; border-radius: 4px; margin-bottom: 10px; color: #166534; font-size: 15px;
    }
    .box-mejora { 
        background-color: #F0F9FF; border-left: 5px solid #0EA5E9; 
        padding: 15px; border-radius: 4px; margin-bottom: 25px; color: #0369A1; font-size: 15px;
    }
    .title-box { font-weight: bold; margin-bottom: 5px; display: flex; align-items: center; gap: 8px;}
    
    /* Estilos para KPI Cards */
    .kpi-card {
        background-color: white; border-radius: 5px; padding: 20px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1); border-left: 6px solid #1E3A8A;
        margin-bottom: 20px;
    }
    .kpi-card-2 { border-left-color: #3B82F6; }
    .kpi-title { color: #6B7280; font-size: 14px; margin-bottom: 5px; }
    .kpi-value { color: #111827; font-size: 32px; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)

# Variables de la base
COL_VALOR = 'Importe en ML'
COL_CUENTA = 'Nombre cuenta'
COL_BANCO = 'Clave referencia 3'
COL_FECHA = 'Fe-contab-'

@st.cache_data
def load_data(file):
    df = pd.read_excel(file)
    df.columns = df.columns.str.strip()
    
    df[COL_FECHA] = pd.to_datetime(df[COL_FECHA], errors='coerce')
    df = df.dropna(subset=[COL_FECHA])
    df['Año'] = df[COL_FECHA].dt.year
    df['Mes'] = df[COL_FECHA].dt.month
    df['Periodo'] = df[COL_FECHA].dt.strftime('%Y-%m')
    
    df[COL_VALOR] = pd.to_numeric(df[COL_VALOR], errors='coerce').fillna(0)
    df[COL_CUENTA] = df[COL_CUENTA].fillna('Sin Cuenta')
    df[COL_BANCO] = df[COL_BANCO].fillna('Sin Banco')
    
    return df

def netear(df_subset, group_cols):
    """Suma contablemente y devuelve el absoluto para gráficas"""
    res = df_subset.groupby(group_cols, as_index=False)[COL_VALOR].sum()
    res['Valor_Real'] = res[COL_VALOR]
    res[COL_VALOR] = res[COL_VALOR].abs()
    return res

# =============================================================================
# 1. BARRA LATERAL (MENÚ Y CONTROLES)
# =============================================================================
st.sidebar.markdown("### 📊 BI Tesorería Gerencial\n— **Control de Cuentas**")
uploaded_file = st.sidebar.file_uploader("Actualizar Data (.xlsx)", type=["xlsx", "xls"])

if not uploaded_file:
    st.info("Sube el archivo 'gastos.xlsx' en el menú lateral para iniciar.")
    st.stop()

df = load_data(uploaded_file)
periodos_disp = sorted(df['Periodo'].unique())

st.sidebar.markdown("---")
st.sidebar.markdown("### 🗓️ Control Temporal")
enfoque = st.sidebar.radio("Seleccione el enfoque:", ["⚖️ Comparativo (Mes VS Mes)", "📈 Rango Historico"])

col_b1, col_b2 = st.sidebar.columns(2)
with col_b1:
    per_base = st.selectbox("Periodo Base", periodos_disp, index=0)
with col_b2:
    per_actual = st.selectbox("Periodo Actual", periodos_disp, index=len(periodos_disp)-1)

st.sidebar.markdown("---")
st.sidebar.markdown("### Seleccione la Pagina:")
pagina = st.sidebar.radio("", [
    "1. Consolidado (Ingresos/Gastos)",
    "2. Evolucion Mes a Mes por Cuenta",
    "3. Matriz de Cuentas por Banco"
])

# =============================================================================
# 2. LÓGICA DE TEXTOS ANALÍTICOS DINÁMICOS
# =============================================================================
# Extraer datos de los periodos seleccionados para los textos
df_base = df[df['Periodo'] == per_base]
df_actual = df[df['Periodo'] == per_actual]

val_base = netear(df_base, ['Periodo'])[COL_VALOR].sum() if not df_base.empty else 0
val_actual = netear(df_actual, ['Periodo'])[COL_VALOR].sum() if not df_actual.empty else 0

var_pct = ((val_actual - val_base) / val_base * 100) if val_base != 0 else 0
tendencia_txt = "creciente 📈" if var_pct > 0 else "decreciente 📉"
color_tend = "aumentado" if var_pct > 0 else "reducido"

# =============================================================================
# 3. PÁGINAS DEL DASHBOARD
# =============================================================================

if pagina == "1. Consolidado (Ingresos/Gastos)":
    st.markdown(f"### 1. CONSOLIDADO DE TESORERIA (TODOS LOS BANCOS)")
    st.markdown(f"*Comparativa Estratégica: **{per_actual}** VS **{per_base}***")
    
    # Cajas Analíticas
    st.markdown(f"""
        <div class="box-situacion">
            <div class="title-box">📊 Situacion Actual:</div>
            El volumen transaccional neto muestra una tendencia <b>{tendencia_txt}</b> con una variación de <b>{var_pct:+.1f}%</b> entre el inicio ({per_base}) y el periodo actual ({per_actual}).<br>
            El movimiento total en el mes actual se ubica en <b>${val_actual:,.0f}</b>.
        </div>
        <div class="box-mejora">
            <div class="title-box">🚀 Como Mejorarlo:</div>
            Dado que el flujo ha {color_tend}, el paso natural es auditar las cuentas con mayor peso relativo en {per_actual} para asegurar que las comisiones y gastos operativos se mantengan dentro del presupuesto proyectado.
        </div>
    """, unsafe_allow_html=True)
    
    # Tarjetas KPI
    col_kpi1, col_kpi2 = st.columns(2)
    with col_kpi1:
        st.markdown(f"""
        <div class="kpi-card">
            <div class="kpi-title">Volumen Total (Periodo Actual {per_actual})</div>
            <div class="kpi-value">${val_actual:,.0f}</div>
        </div>
        """, unsafe_allow_html=True)
    with col_kpi2:
        st.markdown(f"""
        <div class="kpi-card kpi-card-2">
            <div class="kpi-title">Volumen Total (Periodo Base {per_base})</div>
            <div class="kpi-value">${val_base:,.0f}</div>
        </div>
        """, unsafe_allow_html=True)

    # Gráfico de Área (Evolución)
    st.markdown("**Volumen de Movimientos Mensual**")
    if enfoque == "📈 Rango Historico":
        df_chart = netear(df, ['Periodo', COL_CUENTA])
    else:
        df_chart = netear(df[df['Periodo'].isin([per_base, per_actual])], ['Periodo', COL_CUENTA])
        
    fig_area = px.area(df_chart, x='Periodo', y=COL_VALOR, color=COL_CUENTA, 
                       color_discrete_sequence=px.colors.qualitative.Pastel)
    fig_area.update_layout(margin=dict(l=0, r=0, t=10, b=0), height=350, yaxis_title="Importe ($)")
    st.plotly_chart(fig_area, use_container_width=True)

    # Matriz Inferior
    st.markdown("### 📋 Matriz Mes / Cuenta")
    pivot_cta = pd.pivot_table(df_chart, values=COL_VALOR, index='Periodo', columns=COL_CUENTA, aggfunc='sum').fillna(0)
    st.dataframe(pivot_cta.style.format("${:,.0f}").background_gradient(cmap="Blues", axis=0), use_container_width=True)

elif pagina == "2. Evolucion Mes a Mes por Cuenta":
    st.markdown("### 2. EVOLUCION DETALLADA POR CUENTA CONTABLE")
    cuenta_sel = st.selectbox("Filtre la cuenta a analizar:", df[COL_CUENTA].unique())
    
    df_cta = df[df[COL_CUENTA] == cuenta_sel]
    val_cta_act = netear(df_cta[df_cta['Periodo'] == per_actual], ['Periodo'])[COL_VALOR].sum() if not df_cta[df_cta['Periodo'] == per_actual].empty else 0
    val_cta_base = netear(df_cta[df_cta['Periodo'] == per_base], ['Periodo'])[COL_VALOR].sum() if not df_cta[df_cta['Periodo'] == per_base].empty else 0
    var_cta = ((val_cta_act - val_cta_base) / val_cta_base * 100) if val_cta_base != 0 else 0
    
    st.markdown(f"""
        <div class="box-situacion">
            <div class="title-box">📊 Situacion Actual ({cuenta_sel}):</div>
            La cuenta seleccionada varió un <b>{var_cta:+.2f}%</b> al comparar {per_base} contra {per_actual}.
        </div>
    """, unsafe_allow_html=True)
    
    df_tendencia = netear(df_cta, ['Periodo', COL_BANCO])
    fig_bar = px.bar(df_tendencia, x='Periodo', y=COL_VALOR, color=COL_BANCO, barmode='stack', color_discrete_sequence=px.colors.qualitative.Set2)
    st.plotly_chart(fig_bar, use_container_width=True)
    
    st.markdown("### 📋 Matriz Periodo / Banco")
    pivot_bco = pd.pivot_table(df_tendencia, values=COL_VALOR, index='Periodo', columns=COL_BANCO, aggfunc='sum').fillna(0)
    st.dataframe(pivot_bco.style.format("${:,.0f}").background_gradient(cmap="Greens", axis=0), use_container_width=True)

elif pagina == "3. Matriz de Cuentas por Banco":
    st.markdown("### 3. ESTRUCTURA DE COSTOS POR TERCEROS")
    st.markdown(f"*Evaluando periodo actual: **{per_actual}***")
    
    df_actual_banco = netear(df_actual, [COL_BANCO, COL_CUENTA])
    if not df_actual_banco.empty:
        banco_top = df_actual_banco.groupby(COL_BANCO)[COL_VALOR].sum().idxmax()
        
        st.markdown(f"""
            <div class="box-situacion">
                <div class="title-box">📊 Alerta de Concentración:</div>
                En el periodo <b>{per_actual}</b>, el banco/tercero que mayor volumen acumula es <b>{banco_top}</b>.
            </div>
        """, unsafe_allow_html=True)
        
        fig_sun = px.sunburst(df_actual_banco, path=[COL_BANCO, COL_CUENTA], values=COL_VALOR, color=COL_BANCO)
        st.plotly_chart(fig_sun, use_container_width=True)
        
        st.markdown("### 📋 Matriz Banco / Cuenta")
        pivot_bco_cta = pd.pivot_table(df_actual_banco, values=COL_VALOR, index=COL_BANCO, columns=COL_CUENTA, aggfunc='sum').fillna(0)
        st.dataframe(pivot_bco_cta.style.format("${:,.0f}").background_gradient(cmap="Oranges", axis=1), use_container_width=True)
    else:
        st.warning("No hay datos para el periodo seleccionado.")
