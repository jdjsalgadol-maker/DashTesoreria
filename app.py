import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import time

# ==========================================
# 1. CONFIGURACIÓN DE PÁGINA Y ESTILOS CSS
# ==========================================
st.set_page_config(
    page_title="Dashboard Analítico de Tesorería", 
    page_icon="📊", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Estética Profesional: Azul Corporativo, Salmón (Power BI) y Gris Pizarra
st.markdown('''
    <style>
    /* Encabezados de los Paneles */
    .titulo-panel {
        background: linear-gradient(90deg, #101820 0%, #1a2530 100%);
        color: #FEE715; 
        text-align: left;
        font-weight: 600; 
        padding: 12px 20px; 
        border-radius: 8px;
        margin-bottom: 20px; 
        font-size: 18px;
        box-shadow: 0px 4px 10px rgba(0,0,0,0.15);
        letter-spacing: 0.5px;
    }
    
    /* Controles de Rango (Slider) - Tono Salmón Elegante */
    .stSlider > div > div > div > div { background-color: #C98B8B !important; }
    div[data-testid="stThumbValue"] { 
        background-color: #2C3E50 !important; 
        color: #FFFFFF !important; 
        font-weight: bold; 
        border-radius: 4px;
    }
    
    /* Etiquetas MultiSelect (Chips) */
    span[data-baseweb="tag"] { 
        background-color: #C98B8B !important; 
        color: white !important; 
        border-radius: 4px;
    }
    
    /* Tarjetas de Métricas (KPIs) */
    div[data-testid="metric-container"] {
        background-color: #ffffff; 
        border: 1px solid #EAECEE;
        border-radius: 10px; 
        padding: 20px; 
        box-shadow: 0px 4px 15px rgba(0,0,0,0.04);
        border-left: 6px solid #C98B8B;
        transition: transform 0.2s ease-in-out;
    }
    div[data-testid="metric-container"]:hover {
        transform: translateY(-3px);
        box-shadow: 0px 6px 20px rgba(0,0,0,0.08);
    }
    </style>
''', unsafe_allow_html=True)

# ==========================================
# 2. SISTEMA DE ACCESO (LOGIN)
# ==========================================
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_type" not in st.session_state:
    st.session_state.user_type = None
if "login_time" not in st.session_state:
    st.session_state.login_time = None

def check_password():
    pwd = st.session_state.password
    if pwd == "basico123":
        st.session_state.authenticated = True
        st.session_state.user_type = "Básico"
        st.session_state.login_time = time.time()
    elif pwd == "premium123":
        st.session_state.authenticated = True
        st.session_state.user_type = "Premium"
        st.session_state.login_time = time.time()
    else:
        st.error("⚠️ Clave incorrecta. Intente nuevamente.")

if not st.session_state.authenticated:
    st.title("🔐 Portal de Inteligencia Financiera")
    st.write("Ingrese sus credenciales corporativas para acceder al cuadro de mando.")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("Clave de acceso:", type="password", key="password")
        st.button("Ingresar de forma segura", on_click=check_password, use_container_width=True)
        st.info("💡 **Claves habilitadas:**\n- Visor Básico: `basico123` (Tiempo límite: 1 min)\n- Analista Premium: `premium123` (Ilimitado)")
    st.stop()

if st.session_state.user_type == "Básico":
    elapsed_time = time.time() - st.session_state.login_time
    if elapsed_time > 60:
        st.session_state.authenticated = False
        st.warning("⏳ Tiempo de sesión (Básico) finalizado. Autentíquese nuevamente para continuar.")
        st.stop()
    else:
        st.sidebar.warning(f"👁️ Modo Básico - Expira en {int(60 - elapsed_time)}s")
        st.sidebar.button("🔄 Refrescar sesión")
else:
    st.sidebar.success("👑 Modo Analista Premium Activo")

if st.sidebar.button("Cerrar Sesión"):
    st.session_state.authenticated = False
    st.rerun()

st.sidebar.markdown("---")

# ==========================================
# 3. ETL Y PREPARACIÓN DE DATOS (CACHÉ)
# ==========================================
@st.cache_data(show_spinner=False)
def load_data(file):
    df = pd.read_excel(file)
    df.columns = df.columns.str.strip()
    
    col_fecha = 'Fe-contab-' if 'Fe-contab-' in df.columns else 'Fe/contab/'
    if col_fecha in df.columns:
        df['Fecha'] = pd.to_datetime(df[col_fecha], errors='coerce')
        df = df.dropna(subset=['Fecha']) # Limpieza de seguridad
        df['Año'] = df['Fecha'].dt.year
        df['Mes'] = df['Fecha'].dt.month
        
        meses_nom = {1:'ene', 2:'feb', 3:'mar', 4:'abr', 5:'may', 6:'jun', 
                     7:'jul', 8:'ago', 9:'sep', 10:'oct', 11:'nov', 12:'dic'}
        df['Mes_Nombre'] = df['Mes'].map(meses_nom)
        df['Periodo_Label'] = df['Mes_Nombre'] + " " + df['Año'].astype(str)
        df['Periodo_Sort'] = df['Año'].astype(str) + "-" + df['Mes'].astype(str).str.zfill(2)
        
    col_importe = 'Importe_Graficar' if 'Importe_Graficar' in df.columns else 'Importe en ML'
    if col_importe in df.columns:
        df['Importe'] = pd.to_numeric(df[col_importe], errors='coerce').abs()
        
    return df

def format_currency(val):
    if pd.isna(val) or val == 0: return "$0"
    if val >= 1_000_000_000: return f"{val/1_000_000_000:.1f} mil M".replace('.', ',')
    elif val >= 1_000_000: return f"{val/1_000_000:.1f} M".replace('.', ',')
    return f"${val:,.0f}"

# ==========================================
# 4. CONTROLES DEL TABLERO (SIDEBAR)
# ==========================================
st.sidebar.title("🎛️ Filtros de Análisis")
archivo_subido = st.sidebar.file_uploader("📂 Origen de Datos (Excel)", type=["xlsx", "xls"])

if archivo_subido is None:
    st.info("👋 **Bienvenido.** Por favor, cargue su archivo Excel de gastos normalizado para desplegar el tablero.")
    st.stop()

with st.spinner("Estructurando modelo de datos..."):
    df = load_data(archivo_subido)

# Filtros Temporales
st.sidebar.markdown('<div class="titulo-panel" style="font-size:15px; margin-bottom:10px; padding:8px;">Mes de Ejercicio</div>', unsafe_allow_html=True)
meses_dict = {1:'enero', 2:'febrero', 3:'marzo', 4:'abril', 5:'mayo', 6:'junio', 
              7:'julio', 8:'agosto', 9:'septiembre', 10:'octubre', 11:'noviembre', 12:'diciembre'}
meses_seleccionados = st.sidebar.multiselect("Periodos:", list(meses_dict.values()), default=list(meses_dict.values()))
meses_ids = [k for k, v in meses_dict.items() if v in meses_seleccionados]

st.sidebar.markdown("---")
min_year, max_year = int(df['Año'].min()), int(df['Año'].max())
if min_year == max_year:
    anios = (min_year, max_year)
    st.sidebar.info(f"Ejercicio único: {min_year}")
else:
    anios = st.sidebar.slider("Ejercicio (Año)", min_year, max_year, (min_year, max_year))

st.sidebar.markdown("---")
st.sidebar.markdown("### Origen de Cuenta")
tipos_disp = df['Tipo'].dropna().unique()
tipos_sel = [t for t in tipos_disp if st.sidebar.checkbox(str(t), value=True)]

# Dataframe base filtrado
df_filt = df[
    (df['Año'] >= anios[0]) & (df['Año'] <= anios[1]) & 
    (df['Mes'].isin(meses_ids)) & 
    (df['Tipo'].isin(tipos_sel))
]

# ==========================================
# 5. MOTOR DE FILTRADO CRUZADO
# ==========================================
cuenta_seleccionada = None
if "grafico_cuentas" in st.session_state:
    puntos = st.session_state["grafico_cuentas"].get("selection", {}).get("points", [])
    if puntos:
        cuenta_seleccionada = puntos[0]["y"]

df_dinamico = df_filt[df_filt['Nombre cuenta'] == cuenta_seleccionada] if cuenta_seleccionada else df_filt

# ==========================================
# 6. BANDEJA DE INDICADORES CLAVE (KPIs)
# ==========================================
st.markdown('<div class="titulo-panel">Resumen Ejecutivo de Métricas</div>', unsafe_allow_html=True)
kpi1, kpi2, kpi3, kpi4 = st.columns(4)

total_gastos = df_dinamico['Importe'].sum()
meses_unicos = df_dinamico['Periodo_Sort'].nunique()
promedio_mensual = total_gastos / meses_unicos if meses_unicos > 0 else 0

# Machine Learning Básico: Regresión Lineal de Tendencia
tendencia_estado = "Insuficientes datos"
if meses_unicos > 2:
    df_trend = df_dinamico.groupby('Periodo_Sort')['Importe'].sum().reset_index()
    z = np.polyfit(np.arange(len(df_trend)), df_trend['Importe'].values, 1)
    pendiente = z[0]
    umbral = promedio_mensual * 0.015 # 1.5% de tolerancia para estabilidad
    if pendiente > umbral: tendencia_estado = "📈 Alcista (En expansión)"
    elif pendiente < -umbral: tendencia_estado = "📉 Bajista (En contracción)"
    else: tendencia_estado = "➡️ Estable (Controlado)"
elif meses_unicos > 0:
     tendencia_estado = "➡️ Estable (Controlado)"

kpi1.metric("Importe Acumulado", format_currency(total_gastos))
kpi2.metric("Media de Gasto Mensual", format_currency(promedio_mensual))
kpi3.metric("Vector de Tendencia", tendencia_estado)
kpi4.metric("Segmento Analizado", cuenta_seleccionada if cuenta_seleccionada else "Consolidado Global")

# ==========================================
# 7. VISUALIZACIÓN ANALÍTICA CON PLOTLY
# ==========================================
st.markdown("---")

# --- GRÁFICO 1: LÍNEA DE TENDENCIA ---
st.markdown('<div class="titulo-panel">Evolución Cronológica del Gasto</div>', unsafe_allow_html=True)
tendencia = df_dinamico.groupby(['Periodo_Sort', 'Periodo_Label'])['Importe'].sum().reset_index().sort_values('Periodo_Sort')
tendencia['Texto_Hover'] = tendencia['Importe'].apply(format_currency)

fig_line = go.Figure()
if not tendencia.empty:
    fig_line.add_trace(go.Scatter(
        x=tendencia['Periodo_Label'], y=tendencia['Importe'],
        mode='lines+markers+text', text=tendencia['Texto_Hover'], textposition='top center',
        line=dict(color='#1F618D', width=3.5), # Azul corporativo oscuro
        marker=dict(color='#C98B8B', size=10, line=dict(width=2, color='white')), # Salmón
        fill='tozeroy', fillcolor='rgba(31, 97, 141, 0.1)' # Sombreado azul pálido
    ))
fig_line.update_layout(
    plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', 
    margin=dict(l=20, r=20, t=20, b=20), height=350,
    xaxis=dict(showgrid=True, gridcolor='#EAECEE'), 
    yaxis=dict(showgrid=False, visible=False)
)
st.plotly_chart(fig_line, use_container_width=True)

col_bar1, col_bar2 = st.columns(2)

# --- GRÁFICO 2: SEGMENTADOR INTERACTIVO ---
with col_bar1:
    st.markdown('<div class="titulo-panel">Distribución por Rubro Contable</div>', unsafe_allow_html=True)
    st.caption("👆 *Interactivo: Seleccione una barra para enfocar el análisis.*")
    
    cuenta_df = df_filt.groupby('Nombre cuenta')['Importe'].sum().reset_index().sort_values('Importe', ascending=True)
    cuenta_df['Texto_Hover'] = cuenta_df['Importe'].apply(format_currency)
    
    # Atenuar barras no seleccionadas
    colores = ['#C98B8B' if (not cuenta_seleccionada or c == cuenta_seleccionada) else '#F2DADA' for c in cuenta_df['Nombre cuenta']]
    
    fig_bar1 = px.bar(cuenta_df, x='Importe', y='Nombre cuenta', text='Texto_Hover', orientation='h')
    fig_bar1.update_traces(marker_color=colores, textposition='outside')
    fig_bar1.update_layout(
        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', 
        xaxis=dict(visible=False), yaxis=dict(title=""), 
        margin=dict(l=10, r=50, t=10, b=10), height=400, clickmode='event+select'
    )
    st.plotly_chart(fig_bar1, use_container_width=True, on_select="rerun", selection_mode="points", key="grafico_cuentas")

# --- GRÁFICO 3: TOP BANCOS / TERCEROS ---
with col_bar2:
    st.markdown('<div class="titulo-panel">Concentración por Entidad / Tercero</div>', unsafe_allow_html=True)
    st.caption("📊 *Top 15 entidades para el segmento seleccionado.*")
    
    banco_df = df_dinamico.groupby('Clave referencia 3')['Importe'].sum().reset_index().sort_values('Importe', ascending=True).tail(15)
    banco_df['Texto_Hover'] = banco_df['Importe'].apply(format_currency)
    
    fig_bar2 = px.bar(banco_df, x='Importe', y='Clave referencia 3', text='Texto_Hover', orientation='h')
    fig_bar2.update_traces(marker_color='#C98B8B', textposition='outside')
    fig_bar2.update_layout(
        plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', 
        xaxis=dict(visible=False), yaxis=dict(title=""), 
        margin=dict(l=10, r=50, t=10, b=10), height=400
    )
    st.plotly_chart(fig_bar2, use_container_width=True)

# ==========================================
# 8. MATRIZ MO-M Y ASISTENTE IA (NLP AVANZADO)
# ==========================================
st.markdown("---")
col_var, col_chat = st.columns([1.5, 1.2])

with col_var:
    st.markdown('<div class="titulo-panel">Matriz de Variación Mensual (MoM)</div>', unsafe_allow_html=True)
    if not tendencia.empty and len(tendencia) > 1:
        tendencia['Variación %'] = tendencia['Importe'].pct_change() * 100
        df_mostrar = tendencia[['Periodo_Label', 'Importe', 'Variación %']].copy()
        df_mostrar.columns = ['Periodo', 'Importe Total', 'Variación vs Anterior (%)']
        
        def highlight_var(val):
            if pd.isna(val): return ''
            # Rojo para aumentos de gasto, Verde para ahorros/disminuciones
            return 'color: #D32F2F; font-weight: 600;' if val > 0 else 'color: #2E7D32; font-weight: 600;'
            
        st.dataframe(
            df_mostrar.style.format({
                'Importe Total': lambda x: f"${x:,.0f}", 
                'Variación vs Anterior (%)': lambda x: f"{x:+.2f}%" if pd.notna(x) else "-"
            }).map(highlight_var, subset=['Variación vs Anterior (%)']),
            use_container_width=True, height=350
        )
    else:
        st.info("💡 Faltan periodos secuenciales en el filtro actual para calcular variaciones (MoM).")

with col_chat:
    st.markdown('<div class="titulo-panel">Asistente Analítico Inteligente</div>', unsafe_allow_html=True)
    
    pregunta = st.chat_input("Escriba su consulta analítica aquí...")
    
    if pregunta:
        st.chat_message("user").write(pregunta)
        
        # Estandarización de texto (NLP Básico)
        q = pregunta.lower().replace('á', 'a').replace('é', 'e').replace('í', 'i').replace('ó', 'o').replace('ú', 'u')
        q = q.replace('¿', '').replace('?', '').strip()
        
        respuesta = ""
        
        if df_filt.empty:
            respuesta = "⚠️ El dataset actual carece de registros bajo los filtros seleccionados."
        else:
            # 1. Reconocimiento de Entidades (Cuenta Contable)
            cuenta_mencionada = None
            for c in df_filt['Nombre cuenta'].dropna().unique():
                if c.lower() in q:
                    cuenta_mencionada = c
                    break
            if not cuenta_mencionada and cuenta_seleccionada:
                cuenta_mencionada = cuenta_seleccionada

            # 2. Motor de Respuestas Cualitativas (Minería de Columna Texto)
            if any(p in q for p in ["por que", "porque", "razon", "motivo", "texto", "detalle", "explica"]):
                if not cuenta_mencionada:
                    respuesta = "🔍 **Precisión requerida:** Por favor, especifique el rubro contable a auditar.\n\n*Ejemplo: 'Detalle de Comisiones' o '¿Por qué aumentó el Gravamen?'*"
                else:
                    df_txt = df_filt[df_filt['Nombre cuenta'] == cuenta_mencionada]
                    if not df_txt.empty and 'Texto' in df_txt.columns:
                        top_textos = df_txt.groupby('Texto')['Importe'].sum().sort_values(ascending=False).head(5)
                        detalles_str = "\n".join([f"- {texto}: **{format_currency(importe)}**" for texto, importe in top_textos.items()])
                        respuesta = f"📑 **Auditoría de Cuenta: {cuenta_mencionada}**\nAl extraer las descripciones directas (Columna 'Texto'), los generadores de gasto más relevantes son:\n\n{detalles_str}"
                        
                        # Inyección de Reglas de Negocio / Estacionalidad
                        if "gravamen" in cuenta_mencionada.lower():
                            if "diciembre" in q or "junio" in q:
                                respuesta += "\n\n💡 *Insight Operativo:* Las alzas en estos ciclos están indexadas al pago de **primas, bonificaciones** y nómina adicional."
                            elif "enero" in q:
                                respuesta += "\n\n💡 *Insight Operativo:* La concentración de egresos en enero corresponde operativamente a la liquidación y pago de **cesantías**."
                        elif "comision" in cuenta_mencionada.lower() and ("diciembre" in q or "ano" in q or "temporada" in q):
                            respuesta += "\n\n💡 *Insight Operativo:* La estacionalidad de fin de año genera un pico transaccional por **mayor volumen de recaudo y consumo**, impactando la tarifa bancaria."
                    else:
                        respuesta = f"⚠️ El rubro **{cuenta_mencionada}** no posee descripciones imputadas en la columna 'Texto'."

            # 3. Motor de Respuestas Cuantitativas (Cálculos Directos)
            elif "mayor" in q and ("cuenta" in q or "tipo" in q or "rubro" in q):
                c_max = df_dinamico.groupby('Nombre cuenta')['Importe'].sum().idxmax()
                v_max = df_dinamico.groupby('Nombre cuenta')['Importe'].sum().max()
                respuesta = f"🏆 El rubro con mayor impacto financiero es **{c_max}** sumando **{format_currency(v_max)}**."
            
            elif ("mayor" in q or "top" in q or "mas" in q) and ("banco" in q or "referencia" in q or "entidad" in q or "tercero" in q):
                b_max = df_dinamico.groupby('Clave referencia 3')['Importe'].sum().idxmax()
                v_max = df_dinamico.groupby('Clave referencia 3')['Importe'].sum().max()
                respuesta = f"🏦 La entidad/tercero con mayor concentración de pagos es **{b_max}** con **{format_currency(v_max)}**."
                
            elif ("menor" in q or "menos" in q) and ("banco" in q or "referencia" in q or "entidad" in q):
                b_min = df_dinamico.groupby('Clave referencia 3')['Importe'].sum().idxmin()
                v_min = df_dinamico.groupby('Clave referencia 3')['Importe'].sum().min()
                respuesta = f"📉 La entidad con menor facturación registrada es **{b_min}** ({format_currency(v_min)})."
                
            elif "total" in q or "suma" in q or "acumulado" in q:
                respuesta = f"💰 El **capital total egresado** en este segmento es de **{format_currency(total_gastos)}**."
                
            elif "promedio" in q or "media" in q:
                respuesta = f"⚖️ El modelo calcula un **gasto promedio mensual** de **{format_currency(promedio_mensual)}**."
                
            elif "transacciones" in q or "registros" in q or "cuantos" in q or "cantidad" in q:
                respuesta = f"🗃️ El dataset contiene **{len(df_dinamico):,} operaciones** bajo los parámetros actuales."

            # 4. Sistema de Sugerencias Dinámicas (Fallback Inteligente)
            else:
                if "banco" in q or "referencia" in q or "entidad" in q:
                    respuesta = "🤖 **Asistente:** Parece requerir métricas de entidades. ¿Le gustaría saber?:\n\n" \
                                "- *¿Cuál es el mayor banco?*\n" \
                                "- *¿Cuál es el menor banco?*"
                elif "cuenta" in q or "rubro" in q:
                    respuesta = "🤖 **Asistente:** Ha consultado sobre cuentas contables. Pruebe preguntar:\n\n" \
                                "- *¿Cuál es la cuenta con más gastos?*\n" \
                                "- *¿Por qué subió el gravamen en diciembre?*"
                elif "mes" in q or "tiempo" in q or "fecha" in q:
                    respuesta = "🤖 **Asistente:** Para análisis temporal, los comandos óptimos son:\n\n" \
                                "- *¿Cuál es el promedio mensual?*\n" \
                                "- *¿Cuál es el total acumulado?*"
                else:
                    top_cuenta_sug = df_dinamico.groupby('Nombre cuenta')['Importe'].sum().idxmax() if not df_dinamico.empty else "GRAVAMEN"
                    respuesta = f"🤖 **Consulta no catalogada.** Intente formularla como una de las siguientes opciones:\n\n" \
                                f"1. *¿Cuál es el detalle del rubro {top_cuenta_sug}?*\n" \
                                f"2. *¿Cuál es el mayor banco?*\n" \
                                f"3. *¿A cuánto asciende el gasto total?*\n\n" \
                                f"💡 **Consejo:** Use palabras clave como *'por qué', 'detalle', 'total'* o *'mayor'*."

        with st.chat_message("assistant"):
            st.write(respuesta)
    else:
        st.info("💬 **Asistente Preparado:** Extraigo insights, justifico variaciones desde la columna 'Texto' y calculo totales. ¿Qué desea auditar hoy?")
