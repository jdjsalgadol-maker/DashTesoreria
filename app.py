import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go

# ==========================================
# 1. CONFIGURACIÓN DE PÁGINA Y ESTILOS CSS
# ==========================================
st.set_page_config(
    page_title="Dashboard Analítico de Tesorería", 
    page_icon="📊", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Inyección de CSS para replicar la estética corporativa (Power BI theme)
st.markdown("""
    <style>
    /* Estilo de los encabezados de paneles */
    .titulo-panel {
        background-color: #000000; 
        color: #FFD700; 
        text-align: center;
        font-weight: bold; 
        padding: 10px; 
        border-radius: 6px;
        margin-bottom: 20px; 
        font-size: 18px;
        box-shadow: 0px 4px 6px rgba(0, 0, 0, 0.1);
    }
    
    /* Personalización del Slider (Tonos Salmón/Rojo) */
    .stSlider > div > div > div > div { background-color: #FF4B4B !important; }
    div[data-testid="stThumbValue"] { 
        background-color: #333333 !important; 
        color: #FF4B4B !important; 
        font-weight: bold; 
    }
    
    /* Personalización de los MultiSelects (Chips) */
    span[data-baseweb="tag"] { 
        background-color: #FF4B4B !important; 
        color: white !important; 
    }
    
    /* Estilos de las Tarjetas KPI */
    div[data-testid="metric-container"] {
        background-color: #ffffff; 
        border: 1px solid #e6e6e6;
        border-radius: 8px; 
        padding: 15px 20px; 
        box-shadow: 2px 2px 10px rgba(0,0,0,0.05);
        border-left: 5px solid #C98B8B;
    }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# 2. MOTOR DE CARGA Y TRANSFORMACIÓN DE DATOS
# ==========================================
@st.cache_data(show_spinner=False)
def load_data(file):
    """Carga, limpia y estandariza el dataset financiero."""
    df = pd.read_excel(file)
    df.columns = df.columns.str.strip()
    
    # Estandarización de Fechas
    col_fecha = 'Fe-contab-' if 'Fe-contab-' in df.columns else 'Fe/contab/'
    if col_fecha in df.columns:
        df['Fecha'] = pd.to_datetime(df[col_fecha], errors='coerce')
        df['Año'] = df['Fecha'].dt.year
        df['Mes'] = df['Fecha'].dt.month
        
        # Diccionario de meses para etiquetas limpias
        meses_nom = {1:'ene', 2:'feb', 3:'mar', 4:'abr', 5:'may', 6:'jun', 
                     7:'jul', 8:'ago', 9:'sep', 10:'oct', 11:'nov', 12:'dic'}
        df['Mes_Nombre'] = df['Mes'].map(meses_nom)
        
        # Columnas de ordenamiento y visualización
        df['Periodo_Label'] = df['Mes_Nombre'] + " " + df['Año'].astype(str)
        df['Periodo_Sort'] = df['Año'].astype(str) + "-" + df['Mes'].astype(str).str.zfill(2)
        
    # Estandarización de Importes (Siempre Absolutos para visualización)
    col_importe = 'Importe_Graficar' if 'Importe_Graficar' in df.columns else 'Importe en ML'
    if col_importe in df.columns:
        df['Importe'] = pd.to_numeric(df[col_importe], errors='coerce').abs()
        
    return df

def format_currency(val):
    """Formatea valores grandes a notaciones legibles (ej: 1,2 mil M)."""
    if pd.isna(val) or val == 0: return "$0"
    if val >= 1_000_000_000: return f"{val/1_000_000_000:.1f} mil M".replace('.', ',')
    elif val >= 1_000_000: return f"{val/1_000_000:.1f} M".replace('.', ',')
    return f"${val:,.0f}"

# ==========================================
# 3. INTERFAZ LATERAL (SIDEBAR & FILTROS)
# ==========================================
st.sidebar.image("https://upload.wikimedia.org/wikipedia/commons/thumb/c/c3/Python-logo-notext.svg/1200px-Python-logo-notext.svg.png", width=50)
st.sidebar.title("Configuración")

archivo_subido = st.sidebar.file_uploader("📂 Suba su dataset (Excel)", type=["xlsx", "xls"])

if archivo_subido is None:
    st.info("👋 **Bienvenido al Dashboard Analítico.** Por favor, cargue su archivo Excel de gastos para comenzar.")
    st.stop()

with st.spinner("Procesando datos financieros..."):
    df = load_data(archivo_subido)

# Filtro de Meses
st.sidebar.markdown('<div class="titulo-panel" style="font-size:16px; margin-bottom:10px;">Mes</div>', unsafe_allow_html=True)
meses_dict = {1:'enero', 2:'febrero', 3:'marzo', 4:'abril', 5:'mayo', 6:'junio', 
              7:'julio', 8:'agosto', 9:'septiembre', 10:'octubre', 11:'noviembre', 12:'diciembre'}
meses_seleccionados = st.sidebar.multiselect("Seleccionar meses:", list(meses_dict.values()), default=list(meses_dict.values()))
meses_ids = [k for k, v in meses_dict.items() if v in meses_seleccionados]

st.sidebar.markdown("---")

# Filtro de Años
min_year, max_year = int(df['Año'].min()), int(df['Año'].max())
if min_year == max_year:
    anios = (min_year, max_year)
    st.sidebar.info(f"Año único detectado: {min_year}")
else:
    anios = st.sidebar.slider("Año", min_year, max_year, (min_year, max_year))

st.sidebar.markdown("---")

# Filtro de Origen/Tipo
st.sidebar.markdown("### Origen de cuenta")
tipos_disp = df['Tipo'].dropna().unique()
tipos_sel = [t for t in tipos_disp if st.sidebar.checkbox(str(t), value=True)]

# DataFrame filtrado base
df_filt = df[
    (df['Año'] >= anios[0]) & (df['Año'] <= anios[1]) & 
    (df['Mes'].isin(meses_ids)) & 
    (df['Tipo'].isin(tipos_sel))
]

# ==========================================
# 4. LÓGICA DE SEGMENTACIÓN CRUZADA (CROSS-FILTERING)
# ==========================================
cuenta_seleccionada = None
if "grafico_cuentas" in st.session_state:
    puntos = st.session_state["grafico_cuentas"].get("selection", {}).get("points", [])
    if puntos:
        cuenta_seleccionada = puntos[0]["y"]

# df_dinamico reacciona al clic en la barra. df_filt mantiene el total para la gráfica de cuentas.
if cuenta_seleccionada:
    df_dinamico = df_filt[df_filt['Nombre cuenta'] == cuenta_seleccionada]
else:
    df_dinamico = df_filt

# ==========================================
# 5. PANEL DE MÉTRICAS (KPIs) & MACHINE LEARNING BÁSICO
# ==========================================
st.markdown('<div class="titulo-panel">Resumen de Métricas (Filtro Activo)</div>', unsafe_allow_html=True)
kpi1, kpi2, kpi3, kpi4 = st.columns(4)

total_gastos = df_dinamico['Importe'].sum()
meses_unicos = df_dinamico['Periodo_Sort'].nunique()
promedio_mensual = total_gastos / meses_unicos if meses_unicos > 0 else 0

# Algoritmo de Regresión Lineal para clasificar la tendencia
tendencia_estado = "Insuficientes datos"
if meses_unicos > 2:
    df_trend = df_dinamico.groupby('Periodo_Sort')['Importe'].sum().reset_index()
    x = np.arange(len(df_trend))
    y = df_trend['Importe'].values
    z = np.polyfit(x, y, 1) # Polinomio grado 1 (Línea)
    pendiente = z[0]
    
    umbral = promedio_mensual * 0.01 # Considera estable si la variación es menor al 1% del promedio
    if pendiente > umbral: tendencia_estado = "📈 Alcista (Gasto al alza)"
    elif pendiente < -umbral: tendencia_estado = "📉 Bajista (Gasto a la baja)"
    else: tendencia_estado = "➡️ Estable"
elif meses_unicos > 0:
     tendencia_estado = "➡️ Estable"

kpi1.metric("Total Gastos Acumulados", format_currency(total_gastos))
kpi2.metric("Promedio Mensual", format_currency(promedio_mensual))
kpi3.metric("Tendencia General", tendencia_estado)
kpi4.metric("Filtro Cruzado Activo", cuenta_seleccionada if cuenta_seleccionada else "Todas (Global)")

# ==========================================
# 6. VISUALIZACIONES PRINCIPALES (PLOTLY)
# ==========================================
st.markdown("---")

# --- GRÁFICO 1: TENDENCIA TEMPORAL ---
st.markdown('<div class="titulo-panel">Evolución de Tendencia</div>', unsafe_allow_html=True)
tendencia = df_dinamico.groupby(['Periodo_Sort', 'Periodo_Label'])['Importe'].sum().reset_index().sort_values('Periodo_Sort')
tendencia['Texto_Hover'] = tendencia['Importe'].apply(format_currency)

fig_line = go.Figure()
if not tendencia.empty:
    fig_line.add_trace(go.Scatter(
        x=tendencia['Periodo_Label'], y=tendencia['Importe'],
        mode='lines+markers+text', text=tendencia['Texto_Hover'], textposition='top center',
        line=dict(color='#0088FF', width=3), # Línea Azul
        marker=dict(color='#D9777F', size=9, line=dict(width=1.5, color='white')), # Puntos Rosados
        fill='tozeroy', fillcolor='rgba(220, 220, 220, 0.3)'
    ))
fig_line.update_layout(
    plot_bgcolor='white', margin=dict(l=20, r=20, t=20, b=20), height=320,
    xaxis=dict(showgrid=True, gridcolor='#f0f0f0'), 
    yaxis=dict(showgrid=True, gridcolor='#f0f0f0', visible=False)
)
st.plotly_chart(fig_line, use_container_width=True)

# FILA DE GRÁFICOS DE BARRAS
col_bar1, col_bar2 = st.columns(2)

# --- GRÁFICO 2: TIPO DE CUENTA (EL SEGMENTADOR INTERACTIVO) ---
with col_bar1:
    st.markdown('<div class="titulo-panel">Tipo de cuenta (Segmentador)</div>', unsafe_allow_html=True)
    st.caption("👆 *Haz clic en una barra para filtrar el dashboard. Clic fuera para quitar filtro.*")
    
    # IMPORTANTE: Usa df_filt para mostrar siempre todas las cuentas
    cuenta_df = df_filt.groupby('Nombre cuenta')['Importe'].sum().reset_index().sort_values('Importe', ascending=True)
    cuenta_df['Texto_Hover'] = cuenta_df['Importe'].apply(format_currency)
    
    # Lógica de Color: Resalta la selección actual, atenúa las demás
    colores = ['#C98B8B' if (not cuenta_seleccionada or c == cuenta_seleccionada) else '#F2DADA' for c in cuenta_df['Nombre cuenta']]
    
    fig_bar1 = px.bar(cuenta_df, x='Importe', y='Nombre cuenta', text='Texto_Hover', orientation='h')
    fig_bar1.update_traces(marker_color=colores, textposition='outside')
    fig_bar1.update_layout(
        plot_bgcolor='white', xaxis=dict(visible=False), yaxis=dict(title=""), 
        margin=dict(l=10, r=50, t=10, b=10), height=380, clickmode='event+select'
    )
    
    # Enlazamos el evento de clic con st.session_state
    st.plotly_chart(fig_bar1, use_container_width=True, on_select="rerun", selection_mode="points", key="grafico_cuentas")

# --- GRÁFICO 3: BANCOS TOP 15 ---
with col_bar2:
    st.markdown('<div class="titulo-panel">Cantidad por Entidad / Banco</div>', unsafe_allow_html=True)
    st.caption("📊 *Top 15 referencias asociadas al filtro actual.*")
    
    banco_df = df_dinamico.groupby('Clave referencia 3')['Importe'].sum().reset_index().sort_values('Importe', ascending=True).tail(15)
    banco_df['Texto_Hover'] = banco_df['Importe'].apply(format_currency)
    
    fig_bar2 = px.bar(banco_df, x='Importe', y='Clave referencia 3', text='Texto_Hover', orientation='h')
    fig_bar2.update_traces(marker_color='#C98B8B', textposition='outside')
    fig_bar2.update_layout(
        plot_bgcolor='white', xaxis=dict(visible=False), yaxis=dict(title=""), 
        margin=dict(l=10, r=50, t=10, b=10), height=380
    )
    st.plotly_chart(fig_bar2, use_container_width=True)

# ==========================================
# 7. MATRIZ DE VARIACIONES Y ASISTENTE IA (Q&A)
# ==========================================
st.markdown("---")
col_var, col_chat = st.columns([1.5, 1.2])

# --- MATRIZ DE CRECIMIENTO ---
with col_var:
    st.markdown('<div class="titulo-panel">Matriz de Variación (MoM)</div>', unsafe_allow_html=True)
    if not tendencia.empty and len(tendencia) > 1:
        tendencia['Variación %'] = tendencia['Importe'].pct_change() * 100
        df_mostrar = tendencia[['Periodo_Label', 'Importe', 'Variación %']].copy()
        df_mostrar.columns = ['Periodo', 'Importe Total', 'Variación vs Anterior (%)']
        
        def highlight_var(val):
            if pd.isna(val): return ''
            return 'color: #D32F2F; font-weight: bold;' if val > 0 else 'color: #388E3C; font-weight: bold;'
            
        st.dataframe(
            df_mostrar.style.format({
                'Importe Total': lambda x: f"${x:,.0f}", 
                'Variación vs Anterior (%)': lambda x: f"{x:+.2f}%" if pd.notna(x) else "-"
            }).map(highlight_var, subset=['Variación vs Anterior (%)']),
            use_container_width=True, height=300
        )
    else:
        st.info("No hay suficientes periodos consecutivos filtrados para calcular variaciones porcentuales.")

# --- ASISTENTE DE DATOS LOCAL ---
with col_chat:
    st.markdown('<div class="titulo-panel">Asistente Virtual Analítico</div>', unsafe_allow_html=True)
    
    pregunta = st.chat_input("Ej: ¿Mayor banco? / Promedio / Total de gastos")
    
    if pregunta:
        st.chat_message("user").write(pregunta)
        q = pregunta.lower()
        respuesta = ""
        
        # Procesamiento de Lenguaje Natural Básico (NLP basado en reglas)
        if df_dinamico.empty:
            respuesta = "No hay datos disponibles con los filtros actuales para responder."
        elif "mayor" in q and ("cuenta" in q or "tipo" in q):
            cuenta_max = df_dinamico.groupby('Nombre cuenta')['Importe'].sum().idxmax()
            val_max = df_dinamico.groupby('Nombre cuenta')['Importe'].sum().max()
            respuesta = f"La cuenta principal en tu filtro actual es **{cuenta_max}** con **{format_currency(val_max)}**."
        
        elif "mayor" in q and ("banco" in q or "referencia" in q or "entidad" in q):
            banco_max = df_dinamico.groupby('Clave referencia 3')['Importe'].sum().idxmax()
            val_max = df_dinamico.groupby('Clave referencia 3')['Importe'].sum().max()
            respuesta = f"El banco/referencia con mayor volumen es **{banco_max}** con **{format_currency(val_max)}**."
            
        elif "menor" in q and ("banco" in q or "referencia" in q):
            banco_min = df_dinamico.groupby('Clave referencia 3')['Importe'].sum().idxmin()
            val_min = df_dinamico.groupby('Clave referencia 3')['Importe'].sum().min()
            respuesta = f"El banco con menor registro es **{banco_min}** ({format_currency(val_min)})."
            
        elif "total" in q or "suma" in q or "gastos" in q:
            respuesta = f"El total acumulado actual es de **{format_currency(total_gastos)}**."
            
        elif "promedio" in q or "media" in q:
            respuesta = f"El gasto promedio mensual es de **{format_currency(promedio_mensual)}**."
            
        elif "transacciones" in q or "registros" in q or "cuantos" in q:
            respuesta = f"Hay **{len(df_dinamico):,} transacciones** procesadas bajo los filtros actuales."
            
        else:
            respuesta = "🤖 **No entendí la consulta.** Intenta usar palabras como: *total*, *promedio*, *mayor cuenta*, *mayor banco*, o *transacciones*."

        with st.chat_message("assistant"):
            st.write(respuesta)
    else:
        st.info("💡 **Tip:** Pregúntame sobre los datos que estás viendo. Conozco totales, promedios y los picos más altos de bancos o cuentas.")
