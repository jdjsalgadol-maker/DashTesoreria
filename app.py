import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

# ==========================================
# CONFIGURACIÓN Y ESTILOS
# ==========================================
st.set_page_config(page_title="Dashboard Financiero", layout="wide")

st.markdown("""
    <style>
    .titulo-panel {
        background-color: black; color: #FFD700; text-align: center;
        font-weight: bold; padding: 8px; border-radius: 5px;
        margin-bottom: 15px; font-size: 18px;
    }
    .stSlider > div > div > div > div { background-color: #FF4B4B !important; }
    div[data-testid="stThumbValue"] { background-color: #333333 !important; color: #FF4B4B !important; font-weight: bold; }
    span[data-baseweb="tag"] { background-color: #FF4B4B !important; color: white !important; }
    </style>
""", unsafe_allow_html=True)

# ==========================================
# CARGA DE DATOS
# ==========================================
st.sidebar.subheader("📂 Carga de Datos")
archivo_subido = st.sidebar.file_uploader("Suba su archivo Excel", type=["xlsx", "xls"])

@st.cache_data
def load_data(file):
    df = pd.read_excel(file)
    df.columns = df.columns.str.strip()
    col_fecha = 'Fe-contab-' if 'Fe-contab-' in df.columns else 'Fe/contab/'
    if col_fecha in df.columns:
        df['Fecha'] = pd.to_datetime(df[col_fecha], errors='coerce')
        df['Año'] = df['Fecha'].dt.year
        df['Mes'] = df['Fecha'].dt.month
        meses_nom = {1:'ene', 2:'feb', 3:'mar', 4:'abr', 5:'may', 6:'jun', 7:'jul', 8:'ago', 9:'sep', 10:'oct', 11:'nov', 12:'dic'}
        df['Mes_Nombre'] = df['Mes'].map(meses_nom)
        df['Periodo_Label'] = df['Mes_Nombre'] + " " + df['Año'].astype(str)
        df['Periodo_Sort'] = df['Año'].astype(str) + "-" + df['Mes'].astype(str).str.zfill(2)
        
    col_importe = 'Importe_Graficar' if 'Importe_Graficar' in df.columns else 'Importe en ML'
    if col_importe in df.columns:
        df['Importe'] = pd.to_numeric(df[col_importe], errors='coerce').abs()
    return df

if archivo_subido is None:
    st.info("Por favor, cargue el archivo Excel para visualizar el tablero.")
    st.stop()

df = load_data(archivo_subido)

def format_currency(val):
    if val >= 1_000_000_000: return f"{val/1_000_000_000:.1f} mil M".replace('.', ',')
    elif val >= 1_000_000: return f"{val/1_000_000:.1f} M".replace('.', ',')
    return str(val)

# ==========================================
# PANEL IZQUIERDO (FILTROS MAESTROS)
# ==========================================
st.sidebar.markdown('<div class="titulo-panel">Mes</div>', unsafe_allow_html=True)
meses_dict = {1:'enero', 2:'febrero', 3:'marzo', 4:'abril', 5:'mayo', 6:'junio', 7:'julio', 8:'agosto', 9:'septiembre', 10:'octubre', 11:'noviembre', 12:'diciembre'}
meses_seleccionados = st.sidebar.multiselect("Seleccionar meses:", list(meses_dict.values()), default=list(meses_dict.values()))
meses_ids = [k for k, v in meses_dict.items() if v in meses_seleccionados]

st.sidebar.markdown("---")
min_year, max_year = int(df['Año'].min()), int(df['Año'].max())
anios = st.sidebar.slider("Año", min_year, max_year, (min_year, max_year))

st.sidebar.markdown("---")
st.sidebar.markdown("### Origen cuenta")
tipos_disp = df['Tipo'].dropna().unique()
tipos_sel = [t for t in tipos_disp if st.sidebar.checkbox(str(t), value=True)]

# Filtro Base (Desde el panel lateral)
df_filt = df[(df['Año'] >= anios[0]) & (df['Año'] <= anios[1]) & (df['Mes'].isin(meses_ids)) & (df['Tipo'].isin(tipos_sel))]

# ==========================================
# LÓGICA DE FILTRO CRUZADO (ESTILO POWER BI)
# ==========================================
cuenta_seleccionada = None

# Leer si el usuario hizo clic en alguna barra en el ciclo anterior
if "grafico_cuentas" in st.session_state:
    puntos = st.session_state["grafico_cuentas"].get("selection", {}).get("points", [])
    if puntos:
        cuenta_seleccionada = puntos[0]["y"]

# Generar un DataFrame dinámico: Si hay clic, filtra por esa cuenta. Si no, usa el total.
if cuenta_seleccionada:
    df_dinamico = df_filt[df_filt['Nombre cuenta'] == cuenta_seleccionada]
    st.success(f"🎯 **Filtro cruzado activo:** Mostrando evolución y bancos asociados a **{cuenta_seleccionada}**. (Haz clic en un espacio en blanco del gráfico para quitar el filtro).")
else:
    df_dinamico = df_filt

# ==========================================
# PANEL PRINCIPAL (DIBUJO DE GRÁFICOS)
# ==========================================

# --- 1. TENDENCIA (Se actualiza con el clic) ---
st.markdown('<div class="titulo-panel">Tendencia</div>', unsafe_allow_html=True)
tendencia = df_dinamico.groupby(['Periodo_Sort', 'Periodo_Label'])['Importe'].sum().reset_index().sort_values('Periodo_Sort')
tendencia['Texto_Hover'] = tendencia['Importe'].apply(format_currency)

fig_line = go.Figure()
fig_line.add_trace(go.Scatter(
    x=tendencia['Periodo_Label'], y=tendencia['Importe'],
    mode='lines+markers+text', text=tendencia['Texto_Hover'], textposition='top center',
    line=dict(color='#0088FF', width=3), marker=dict(color='#D9777F', size=8, line=dict(width=1, color='white')),
    fill='tozeroy', fillcolor='rgba(220, 220, 220, 0.4)'
))
fig_line.update_layout(plot_bgcolor='white', margin=dict(l=20, r=20, t=20, b=20), xaxis=dict(showgrid=True, gridcolor='#f0f0f0'), yaxis=dict(showgrid=True, gridcolor='#f0f0f0', visible=False), height=300)
st.plotly_chart(fig_line, use_container_width=True)

col1, col2 = st.columns(2)

# --- 2. TIPO DE CUENTA (El Segmentador) ---
with col1:
    st.markdown('<div class="titulo-panel">Tipo de cuenta</div>', unsafe_allow_html=True)
    
    # ATENCIÓN: Este gráfico usa df_filt (NO df_dinamico) para mostrar siempre todas las opciones
    cuenta_df = df_filt.groupby('Nombre cuenta')['Importe'].sum().reset_index().sort_values('Importe', ascending=True)
    cuenta_df['Texto_Hover'] = cuenta_df['Importe'].apply(format_currency)
    
    # Lógica Visual Power BI: Resalta la barra seleccionada y atenúa las demás
    color_fuerte = '#C98B8B' # Salmón oscuro
    color_atenuado = '#F2DADA' # Salmón muy pálido
    colores = [color_fuerte if (not cuenta_seleccionada or c == cuenta_seleccionada) else color_atenuado for c in cuenta_df['Nombre cuenta']]
    
    fig_bar1 = px.bar(cuenta_df, x='Importe', y='Nombre cuenta', text='Texto_Hover', orientation='h')
    fig_bar1.update_traces(marker_color=colores, textposition='outside')
    fig_bar1.update_layout(plot_bgcolor='white', xaxis=dict(visible=False), yaxis=dict(title=""), margin=dict(l=10, r=40, t=10, b=10), height=350, clickmode='event+select')
    
    # Renderizamos activando la lectura de selecciones de Streamlit
    st.plotly_chart(fig_bar1, use_container_width=True, on_select="rerun", selection_mode="points", key="grafico_cuentas")

# --- 3. CANTIDAD POR BANCO (Se actualiza con el clic) ---
with col2:
    st.markdown('<div class="titulo-panel">Cantidad por banco</div>', unsafe_allow_html=True)
    # Usa df_dinamico (Reacciona al filtro de cuenta)
    banco_df = df_dinamico.groupby('Clave referencia 3')['Importe'].sum().reset_index().sort_values('Importe', ascending=True).tail(15)
    banco_df['Texto_Hover'] = banco_df['Importe'].apply(format_currency)
    
    fig_bar2 = px.bar(banco_df, x='Importe', y='Clave referencia 3', text='Texto_Hover', orientation='h')
    fig_bar2.update_traces(marker_color='#C98B8B', textposition='outside')
    fig_bar2.update_layout(plot_bgcolor='white', xaxis=dict(visible=False), yaxis=dict(title=""), margin=dict(l=10, r=40, t=10, b=10), height=350)
    
    st.plotly_chart(fig_bar2, use_container_width=True)
