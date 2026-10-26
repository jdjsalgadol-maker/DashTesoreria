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
# PREPARACIÓN DE DATOS
# ==========================================
@st.cache_data
def load_data(file):
    df = pd.read_excel(file)
    df.columns = df.columns.str.strip()
    
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
# PANEL IZQUIERDO Y FILTROS LATERALES
# ==========================================
st.sidebar.markdown("---")
st.sidebar.title("🎛️ Filtros y Controles")

# 1. Slider para Años y Multiselect para Meses
st.sidebar.subheader("📅 Rango de Tiempo")
min_year = int(df['Año'].min())
max_year = int(df['Año'].max())

if min_year == max_year:
    rango_anios = st.sidebar.slider("Seleccione el Año:", min_value=min_year, max_value=max_year, value=min_year)
    anios_seleccionados = [rango_anios]
else:
    rango_anios = st.sidebar.slider("Seleccione Rango de Años:", min_value=min_year, max_value=max_year, value=(min_year, max_year))
    anios_seleccionados = list(range(rango_anios[0], rango_anios[1] + 1))

meses_disponibles = sorted(df['Mes'].unique())
nombres_meses = {1:'Ene', 2:'Feb', 3:'Mar', 4:'Abr', 5:'May', 6:'Jun', 7:'Jul', 8:'Ago', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Dic'}
meses_formato = [f"{m} - {nombres_meses[m]}" for m in meses_disponibles]

meses_seleccionados_str = st.sidebar.multiselect("Seleccione Mes(es):", meses_formato, default=meses_formato)
meses_seleccionados = [int(m.split(" - ")[0]) for m in meses_seleccionados_str]

# 2. Segmentador por Nombre de cuenta
st.sidebar.subheader("🏷️ Tipo de Cuenta")
col_cuenta = None
for col in ['Nombre cuenta', 'Cuenta', 'Concepto']:
    if col in df.columns:
        col_cuenta = col
        break

opciones_cuenta = []
if col_cuenta:
    opciones_cuenta = st.sidebar.multiselect(f"Filtrar por {col_cuenta}:", df[col_cuenta].dropna().unique())

# Aplicar filtros de panel izquierdo
mask = (df['Año'].isin(anios_seleccionados)) & (df['Mes'].isin(meses_seleccionados))
if opciones_cuenta:
    mask = mask & (df[col_cuenta].isin(opciones_cuenta))
df_filtrado = df[mask]

# ==========================================
# PANEL PRINCIPAL Y SEGMENTADOR COL N
# ==========================================
st.title("📊 Análisis Dinámico de Gastos")

# Buscar la columna N o la columna que se llame "Tipo"
col_tipo = None
for col in ['Tipo', 'TIPO', 'N Tipo', 'Tipo de cuenta']:
    if col in df.columns:
        col_tipo = col
        break
# Si no la encuentra por nombre, toma la columna N (índice 13) si existe
if not col_tipo and len(df.columns) > 13:
    col_tipo = df.columns[13]

if col_tipo:
    st.subheader(f"🗂️ Segmentador Principal ({col_tipo})")
    opciones_tipo = st.multiselect(
        f"Seleccione las opciones de '{col_tipo}' para filtrar todo el dashboard:", 
        df_filtrado[col_tipo].dropna().unique()
    )
    if opciones_tipo:
        df_filtrado = df_filtrado[df_filtrado[col_tipo].isin(opciones_tipo)]

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
    
    # Agrupar por Periodo para la línea de tiempo
    df_tendencia = df_graficos.groupby(['Periodo', 'Agrupación Cuenta'])['Importe en ML'].sum().reset_index()
    
    col1, col2 = st.columns(2)
    with col1:
        fig_line = px.line(
            df_tendencia, x='Periodo', y='Importe en ML', color='Agrupación Cuenta', 
            text='Importe en ML', title="Evolución Total Consolidada por Cuenta", markers=True
        )
        fig_line.update_traces(textposition="top center", texttemplate='%{text:.2s}')
        fig_line.update_layout(xaxis_showgrid=False, yaxis_showgrid=True, legend_title="Cuentas")
        st.plotly_chart(fig_line, use_container_width=True)
        
    with col2:
        fig_bar = px.bar(
            df_tendencia, x='Importe en ML', y='Periodo', color='Agrupación Cuenta', 
            text_auto='.2s', title="Composición del Gasto por Periodo", barmode='stack', orientation='h'
        )
        fig_bar.update_layout(xaxis_showgrid=True, yaxis_showgrid=False, yaxis={'categoryorder':'category descending'}, legend_title="Cuentas")
        st.plotly_chart(fig_bar, use_container_width=True)

# ==========================================
# 2. BARRAS APILADAS HORIZONTALES PARA COLUMNA B
# ==========================================
st.markdown("---")
st.subheader("🏢 Distribución Total por Referencia (Columna B)")

col_ref = None
for col in ['Clave referencia 3', 'Tercero', 'Referencia']:
    if col in df_filtrado.columns:
        col_ref = col
        break

if col_ref:
    top_refs = df_filtrado.groupby(col_ref)['Importe en ML'].sum().nlargest(15).index.tolist()
    df_ref_stacked = df_filtrado[df_filtrado[col_ref].isin(top_refs)].groupby([col_ref, 'Periodo'])['Importe en ML'].sum().reset_index()
    orden_total = df_filtrado.groupby(col_ref)['Importe en ML'].sum().loc[top_refs].sort_values(ascending=True).index.tolist()
    
    fig_bar_ref = px.bar(
        df_ref_stacked, x='Importe en ML', y=col_ref, color='Periodo',
        orientation='h', title=f"Total por {col_ref} Apilado por Periodo (Top 15)",
        text_auto='.2s'
    )
    fig_bar_ref.update_layout(
        yaxis={'categoryorder':'array', 'categoryarray': orden_total},
        xaxis_showgrid=True, yaxis_showgrid=False,
        height=500
    )
    
    st.plotly_chart(fig_bar_ref, use_container_width=True)

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
# 4. ANÁLISIS PREDICTIVO
# ==========================================
st.markdown("---")
st.subheader("🔮 Análisis Predictivo de Tendencias")
if len(df_matriz) > 2:
    # Regresión lineal para predecir el comportamiento general
    x = np.arange(len(df_matriz))
    y = df_matriz['Importe en ML'].values
    z = np.polyfit(x, y, 1) # Polinomio de grado 1 (Línea recta)
    p = np.poly1d(z)
    
    tendencia_str = "alza" if z[0] > 0 else "baja"
    color_tendencia = "🔴" if z[0] > 0 else "🟢" # Asumiendo que es gasto: alza es alerta, baja es positivo
    
    proyeccion = p(len(x))
    
    st.info(f"{color_tendencia} **Proyección Algorítmica:** Basado en el volumen de las variaciones del periodo analizado, el modelo matemático proyecta que la tendencia general va a la **{tendencia_str}**. De mantenerse las condiciones operativas actuales, se estima que el importe global para el próximo periodo será de aproximadamente **${proyeccion:,.2f}**.")
else:
    st.warning("Se requieren al menos 3 periodos (meses) continuos de datos para generar un modelo predictivo confiable.")

# ==========================================
# 5. PREGUNTAS (4 PORQUÉS)
# ==========================================
st.markdown("---")
st.subheader("💡 Los 4 Porqués del Análisis")
with st.expander("1. ¿Por qué se observan picos atípicos en ciertos meses?"):
    st.write("Están correlacionados con la estacionalidad de las cuentas y pagos extraordinarios. Verifique el gráfico de barras inferior (Columna B) para identificar exactamente a qué proveedores/referencias se les atribuye el mayor volumen de gastos en dicho mes.")
with st.expander("2. ¿Por qué varía el margen de porcentaje mes a mes?"):
    st.write("Refleja el flujo operativo. Subidas en rojo en la matriz indican expansión de gastos fuera de la media esperada del periodo anterior.")
with st.expander("3. ¿Por qué la tendencia histórica anual difiere de la mensual?"):
    st.write("El análisis mensual presenta fluctuaciones cíclicas a corto plazo. Si analizamos la tendencia global por cuenta, observamos el crecimiento estructural real.")
with st.expander("4. ¿Por qué la proyección algorítmica marca esa tendencia?"):
    st.write("Al analizar el volumen consolidado mediante regresión lineal, el modelo detecta la aceleración de los gastos en el tiempo. Si la curva supera las reducciones históricas, el algoritmo proyecta un alza agregada para el periodo siguiente.")
