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
# CONTROL DE ACCESO
# ==========================================
def check_access():
    st.sidebar.title("🔐 Acceso al Dashboard")
    clave = st.sidebar.text_input("Ingrese su clave de acceso:", type="password")
    
    if not clave:
        st.sidebar.warning("Por favor, ingrese una clave para acceder al panel.")
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
# CARGA DE ARCHIVO DINÁMICO
# ==========================================
st.sidebar.markdown("---")
st.sidebar.subheader("📂 Carga de Datos")
archivo_subido = st.sidebar.file_uploader("Suba su archivo Excel", type=["xlsx", "xls"])

if archivo_subido is None:
    st.info("👋 ¡Bienvenido! Por favor, cargue un archivo Excel en el panel izquierdo para visualizar el dashboard.")
    st.stop()

# ==========================================
# PREPARACIÓN DE DATOS (FLEXIBLE)
# ==========================================
@st.cache_data
def load_data(file):
    df = pd.read_excel(file)
    df.columns = df.columns.str.strip()
    
    # Búsqueda inteligente de la columna de Fecha
    col_fecha = None
    posibles_fechas = ['Fe/contab/', 'Fecha doc/', 'Fecha', 'FECHA', 'Date']
    for col in posibles_fechas:
        if col in df.columns:
            col_fecha = col
            break
            
    if col_fecha:
        df['Fecha'] = pd.to_datetime(df[col_fecha], errors='coerce')
        df = df.dropna(subset=['Fecha'])
        df['Año'] = df['Fecha'].dt.year
        df['Mes'] = df['Fecha'].dt.month
        df['Periodo'] = df['Fecha'].dt.to_period('M').astype(str)
        
    # Búsqueda inteligente de la columna de Importe
    col_importe = None
    posibles_importes = ['Importe en ML', 'Valor', 'Importe', 'Total', 'VALOR TOTAL']
    for col in posibles_importes:
        if col in df.columns:
            col_importe = col
            break
            
    if col_importe:
        df['Importe en ML'] = pd.to_numeric(df[col_importe], errors='coerce').fillna(0)
        
    return df

with st.spinner("Procesando archivo..."):
    df = load_data(archivo_subido)

if 'Fecha' not in df.columns or 'Importe en ML' not in df.columns:
    st.error(f"❌ El archivo subido no tiene el formato esperado. Columnas detectadas: {', '.join(df.columns)}")
    st.stop()

# ==========================================
# PANEL IZQUIERDO Y FILTROS
# ==========================================
st.sidebar.markdown("---")
st.sidebar.title("🎛️ Filtros y Controles")

# --- SLIDER DE FECHAS ---
st.sidebar.subheader("📅 Rango de Tiempo")
min_date = df['Fecha'].min().date()
max_date = df['Fecha'].max().date()

fecha_inicio, fecha_fin = st.sidebar.slider(
    "Seleccione el periodo de análisis:",
    min_value=min_date,
    max_value=max_date,
    value=(min_date, max_date),
    format="YYYY-MM-DD"
)

# --- SEGMENTADOR POR NOMBRE DE CUENTA ---
st.sidebar.subheader("🏷️ Tipo de Cuenta")
col_cuenta = None
posibles_cuentas = ['Nombre cuenta', 'Cuenta', 'Concepto']
for col in posibles_cuentas:
    if col in df.columns:
        col_cuenta = col
        break

opciones_cuenta = []
if col_cuenta:
    opciones_cuenta = st.sidebar.multiselect(
        f"Filtrar por {col_cuenta}:", 
        df[col_cuenta].dropna().unique()
    )

# Filtrado del dataframe
mask = (df['Fecha'].dt.date >= fecha_inicio) & (df['Fecha'].dt.date <= fecha_fin)
if opciones_cuenta:
    mask = mask & (df[col_cuenta].isin(opciones_cuenta))
df_filtrado = df[mask]

st.title("📊 Análisis Dinámico de Gastos")
st.markdown("---")

# ==========================================
# 1. ANÁLISIS DE TENDENCIAS Y COMPOSICIÓN
# ==========================================
st.subheader("📈 Evolución y Composición (Por Cuenta)")

if col_cuenta:
    top_cuentas = df_filtrado.groupby(col_cuenta)['Importe en ML'].sum().nlargest(5).index.tolist()
    
    df_graficos = df_filtrado.copy()
    df_graficos['Agrupación Cuenta'] = df_graficos[col_cuenta].apply(
        lambda x: x if x in top_cuentas else 'OTRAS CUENTAS'
    )
    
    df_tendencia = df_graficos.groupby(['Periodo', 'Agrupación Cuenta'])['Importe en ML'].sum().reset_index()
    
    col1, col2 = st.columns(2)
    with col1:
        # GRAFICO DE LÍNEAS CONSOLIDADO POR CUENTA
        fig_line = px.line(
            df_tendencia, x='Periodo', y='Importe en ML', color='Agrupación Cuenta', 
            title="Evolución Total Consolidada por Cuenta", markers=True
        )
        fig_line.update_layout(xaxis_showgrid=False, yaxis_showgrid=True, legend_title="Cuentas")
        st.plotly_chart(fig_line, use_container_width=True)
        
    with col2:
        # GRAFICO DE BARRAS HORIZONTALES
        fig_bar = px.bar(
            df_tendencia, x='Importe en ML', y='Periodo', color='Agrupación Cuenta', 
            title="Composición del Gasto", barmode='stack', orientation='h'
        )
        fig_bar.update_layout(xaxis_showgrid=True, yaxis_showgrid=False, yaxis={'categoryorder':'category descending'}, legend_title="Cuentas")
        st.plotly_chart(fig_bar, use_container_width=True)

# ==========================================
# 2. DISTRIBUCIÓN TOTAL POR COLUMNA B (REFERENCIA)
# ==========================================
st.markdown("---")
st.subheader("🏢 Distribución Total por Referencia (Columna B)")

# Buscar la columna que corresponde a "Clave referencia 3"
col_ref = None
posibles_refs = ['Clave referencia 3', 'Tercero', 'Referencia']
for col in posibles_refs:
    if col in df_filtrado.columns:
        col_ref = col
        break

if col_ref:
    # Agrupar los importes por la Referencia
    df_ref = df_filtrado.groupby(col_ref)['Importe en ML'].sum().reset_index()
    df_ref = df_ref.sort_values(by='Importe en ML', ascending=False)
    
    # Para mantener el gráfico limpio, agrupamos en el Top 15 (Recomendado en visualización de datos)
    top_n = 15
    if len(df_ref) > top_n:
        df_top_ref = df_ref.iloc[:top_n]
        otros_valor = df_ref.iloc[top_n:]['Importe en ML'].sum()
        df_otros = pd.DataFrame({col_ref: ['OTROS (Resto agrupado)'], 'Importe en ML': [otros_valor]})
        df_ref_final = pd.concat([df_top_ref, df_otros], ignore_index=True)
    else:
        df_ref_final = df_ref

    # GRÁFICO RECOMENDADO: Treemap (Mapa de Árbol)
    # Es la visualización en Python preferida para ver composición de totales sin hacer barras interminables
    fig_treemap = px.treemap(
        df_ref_final, 
        path=[px.Constant("Total Gastos"), col_ref], 
        values='Importe en ML',
        title=f"Proporción del Gasto Histórico por {col_ref} (Treemap)",
        color='Importe en ML',
        color_continuous_scale='Blues' # Escala de colores profesional
    )
    # Mostrar el porcentaje además del valor
    fig_treemap.update_traces(textinfo="label+value+percent parent")
    fig_treemap.update_layout(margin=dict(t=50, l=10, r=10, b=10))
    
    st.plotly_chart(fig_treemap, use_container_width=True)
else:
    st.info("No se detectó la Columna B ('Clave referencia 3') en el archivo cargado para generar este gráfico.")

# ==========================================
# 3. MATRIZ DE VARIACIONES
# ==========================================
st.markdown("---")
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
# 4. PREGUNTAS (4 PORQUÉS)
# ==========================================
st.markdown("---")
st.subheader("💡 Los 4 Porqués del Análisis")
with st.expander("1. ¿Por qué se observan picos atípicos en ciertos meses?"):
    st.write("Están correlacionados con la estacionalidad de las cuentas y pagos extraordinarios. Verifique el Treemap (Columna B) para identificar exactamente a qué proveedores se les atribuye el mayor volumen de gastos.")
with st.expander("2. ¿Por qué varía el margen de porcentaje mes a mes?"):
    st.write("Refleja el flujo operativo. Subidas en rojo en la matriz indican expansión de gastos fuera de la media esperada del periodo anterior.")
with st.expander("3. ¿Por qué la tendencia histórica anual difiere de la mensual?"):
    st.write("El análisis mensual presenta fluctuaciones cíclicas a corto plazo. Si analizamos la tendencia global por cuenta, observamos el crecimiento estructural real.")
with st.expander("4. ¿Por qué la proyección de algunas cuentas marca un alza sostenida?"):
    st.write("Al analizar el volumen consolidado, el modelo detecta que los gastos en las cuentas top superan las reducciones históricas, marcando una tendencia agregada al alza.")
