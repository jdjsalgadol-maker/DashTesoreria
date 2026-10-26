import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import time

# ==========================================
# CONFIGURACIÓN DE LA PÁGINA
# ==========================================
st.set_page_config(page_title="Dashboard Analítico de Gastos", page_icon="📈", layout="wide")

# ==========================================
# CONTROL DE ACCESO (BÁSICO VS PREMIUM)
# ==========================================
def check_access():
    st.sidebar.title("🔐 Acceso al Dashboard")
    clave = st.sidebar.text_input("Ingrese su clave de acceso:", type="password")
    
    if not clave:
        st.warning("Por favor, ingrese una clave para acceder al panel.")
        st.stop()
        
    if clave == "basico123":
        nivel = "Básico"
        limite_segundos = 60
    elif clave == "premium2026":
        nivel = "Premium"
        limite_segundos = None
    else:
        st.sidebar.error("Clave incorrecta.")
        st.stop()
        
    st.sidebar.success(f"Usuario {nivel} autenticado.")
    
    if "inicio_sesion" not in st.session_state:
        st.session_state.inicio_sesion = time.time()
        
    if nivel == "Básico":
        tiempo_transcurrido = time.time() - st.session_state.inicio_sesion
        tiempo_restante = int(limite_segundos - tiempo_transcurrido)
        
        if tiempo_restante <= 0:
            st.error("⏳ Su tiempo de acceso gratuito (1 minuto) ha expirado. Adquiera Premium para tiempo ilimitado.")
            st.stop()
        else:
            st.sidebar.warning(f"Tiempo restante: {tiempo_restante} segundos")
            time.sleep(1)
            st.rerun()

check_access()

# ==========================================
# CARGA Y PREPARACIÓN DE DATOS
# ==========================================
@st.cache_data
def load_data():
    # Intenta cargar el archivo gast_2.xlsx
    df = pd.read_excel("gast_2.xlsx")
    df.columns = df.columns.str.strip()
    
    if 'Fe/contab/' in df.columns:
        df['Fecha'] = pd.to_datetime(df['Fe/contab/'], errors='coerce')
        df['Año'] = df['Fecha'].dt.year
        df['Mes'] = df['Fecha'].dt.month
        df['Periodo'] = df['Fecha'].dt.to_period('M').astype(str)
        
    if 'Importe en ML' in df.columns:
        df['Importe en ML'] = pd.to_numeric(df['Importe en ML'], errors='coerce').fillna(0)
        
    return df

with st.spinner("Cargando base de datos..."):
    df = load_data()

# ==========================================
# PANEL IZQUIERDO Y FILTROS
# ==========================================
st.sidebar.title("🎛️ Filtros")

fecha_inicio, fecha_fin = st.sidebar.date_input(
    "Seleccione el periodo de análisis:",
    [df['Fecha'].min().date(), df['Fecha'].max().date()]
)

columnas_segmentacion = ['Nombre cuenta', 'Clave referencia 3', 'Cuenta', 'CT']
segmentador_seleccionado = st.sidebar.selectbox("Segmentar datos por:", [c for c in columnas_segmentacion if c in df.columns])
opciones_segmento = st.sidebar.multiselect(f"Seleccione {segmentador_seleccionado}:", df[segmentador_seleccionado].dropna().unique())

mask = (df['Fecha'].dt.date >= fecha_inicio) & (df['Fecha'].dt.date <= fecha_fin)
if opciones_segmento:
    mask = mask & (df[segmentador_seleccionado].isin(opciones_segmento))
df_filtrado = df[mask]

st.title("📊 Análisis Dinámico de Gastos")
st.markdown("---")

# ==========================================
# 1. ANÁLISIS DE TENDENCIAS
# ==========================================
st.subheader("📈 Evolución y Tendencias")
if 'Clave referencia 3' in df_filtrado.columns:
    df_tendencia = df_filtrado.groupby(['Periodo', 'Clave referencia 3'])['Importe en ML'].sum().reset_index()
    
    col1, col2 = st.columns(2)
    with col1:
        fig_line = px.line(df_tendencia, x='Periodo', y='Importe en ML', color='Clave referencia 3', title="Variaciones Mensuales", markers=True)
        st.plotly_chart(fig_line, use_container_width=True)
    with col2:
        fig_bar = px.bar(df_tendencia, x='Periodo', y='Importe en ML', color='Clave referencia 3', title="Composición", barmode='stack')
        st.plotly_chart(fig_bar, use_container_width=True)

# ==========================================
# 2. MATRIZ DE VARIACIONES
# ==========================================
st.subheader("📉 Matriz de Variaciones Porcentuales")
df_matriz = df_filtrado.groupby('Periodo')['Importe en ML'].sum().reset_index().sort_values('Periodo')
df_matriz['Periodo Anterior'] = df_matriz['Importe en ML'].shift(1)
df_matriz['Variación %'] = ((df_matriz['Importe en ML'] - df_matriz['Periodo Anterior']) / df_matriz['Periodo Anterior']) * 100

def color_variacion(val):
    if pd.isna(val): return ''
    color = 'green' if val < 0 else 'red'
    return f'color: {color}; font-weight: bold'

st.dataframe(df_matriz.style.map(color_variacion, subset=['Variación %']).format({"Importe en ML": "${:,.2f}", "Periodo Anterior": "${:,.2f}", "Variación %": "{:.2f}%"}), use_container_width=True)

# ==========================================
# 3. PREGUNTAS (4 PORQUÉS)
# ==========================================
st.markdown("---")
st.subheader("💡 Los 4 Porqués del Análisis")
with st.expander("1. ¿Por qué se observan picos atípicos en ciertos meses?"):
    st.write("Están correlacionados con la estacionalidad de las cuentas y pagos extraordinarios.")
with st.expander("2. ¿Por qué varía el margen de porcentaje mes a mes?"):
    st.write("Refleja el flujo operativo. Subidas en rojo indican expansión de gastos fuera de la media.")
with st.expander("3. ¿Por qué la tendencia histórica anual difiere de la mensual?"):
    st.write("El análisis mensual tiene ruido contable; el anual muestra el crecimiento real estructural.")
with st.expander("4. ¿Por qué la proyección marca esta tendencia?"):
    st.write("El modelo detecta si el volumen escala más rápido de lo que se reduce históricamente.")
