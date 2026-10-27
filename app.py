import os
import time

# =============================================================================
# 0. AUTO-CONFIGURACIÓN DEL TEMA NATIVO
# =============================================================================
def setup_theme():
    os.makedirs(".streamlit", exist_ok=True)
    config_path = ".streamlit/config.toml"
    theme_config = '[theme]\nprimaryColor="#1F618D"\n'
    if not os.path.exists(config_path):
        with open(config_path, "w") as f:
            f.write(theme_config)

setup_theme()

import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
import re
import unicodedata

# =============================================================================
# 1. CONSTANTES Y PALETA CORPORATIVA 
# =============================================================================
APP_TITULO = "Dashboard Analítico de Tesorería"
LIMITE_BASICO_S = 60

CORP_BLUE = "#1F618D"       
CORP_BLUE_SOFT = "#D4E6F1"  
CORP_GRAY = "#34495E"       
BG_LIGHT = "#F8F9F9"        
BAJA = "#1B7A3A"            

MESES_LARGO = {
    1: "enero", 2: "febrero", 3: "marzo", 4: "abril", 5: "mayo",
    6: "junio", 7: "julio", 8: "agosto", 9: "septiembre", 10: "octubre",
    11: "noviembre", 12: "diciembre",
}
MESES_ABR = {k: v[:3] for k, v in MESES_LARGO.items()}
COL_FECHA = ("Fe-contab-", "Fe/contab/", "Fe.contab.", "Fe-contab")
NAT_GASTO = "Gasto"
NAT_MENOR = "Menor gasto / Ingreso"

ALIAS_ENTIDAD = {
    "BANCOLOMBIA S A": "Bancolombia", "BANCOLOMBIA PANAMA S": "Bancolombia Panamá",
    "VALORES BANCOLOMBIA": "Valores Bancolombia", "BANCO BILBAO VIZCAYA": "BBVA Colombia",
    "BANCO DAVIVIENDA S A": "Davivienda", "BANCO DAVIBANK S A": "Davibank",
    "BANCO DE OCCIDENTE": "Banco de Occidente", "BANCO COMERCIAL AV V": "Banco AV Villas",
    "BANCO DE BOGOTA PANA": "Banco de Bogotá Panamá", "BANCO DE BOGOTA": "Banco de Bogotá",
    "BANCO GNB SUDAMERIS": "GNB Sudameris", "GNB SUDAMERIS": "GNB Sudameris",
    "BANCO AGRARIO DE COL": "Banco Agrario", "BANCO CAJA SOCIAL S": "Banco Caja Social",
    "BANCO ITAU COLOMBIA": "Itaú", "ITAU COLOMBIA S A": "Itaú",
}

# =============================================================================
# 2. FORMATO NUMÉRICO Y NORMALIZACIÓN
# =============================================================================
def _num(valor: float, dec: int = 1) -> str:
    txt = f"{valor:,.{dec}f}"
    return txt.replace(",", "§").replace(".", ",").replace("§", ".")

def fmt(valor: float) -> str:
    if pd.isna(valor) or valor == 0: return "0"
    a, signo = abs(float(valor)), "-" if valor < 0 else ""
    if a >= 1e12: return f"{signo}{_num(a / 1e12)} B"
    if a >= 1e9: return f"{signo}{_num(a / 1e9)} mil M"
    if a >= 1e6: return f"{signo}{_num(a / 1e6)} M"
    return f"{signo}{_num(a, 0)}"

def format_currency(val):
    return f"${fmt(val)}"

def normalizar(texto: object) -> str:
    t = unicodedata.normalize("NFKD", str(texto).lower())
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = re.sub(r'[^a-z0-9 ]', ' ', t)
    return re.sub(r'\s+', ' ', t).strip()

# =============================================================================
# 3. ETL Y MODELO DE DATOS (CACHÉ)
# =============================================================================
def limpiar_entidad(serie: pd.Series) -> pd.Series:
    crudo = serie.fillna("Sin entidad").astype(str).str.strip()
    clave = crudo.map(lambda x: re.sub(r"\s+", " ", re.sub(r"[.,]", " ", x)).strip().upper())
    clave = clave.map(lambda x: unicodedata.normalize("NFKD", x).encode("ascii", "ignore").decode())
    bonito = crudo.str.title().str.replace(r"\bS\.?A\.?S\b\.?", "S.A.S", regex=True)
    return pd.Series([ALIAS_ENTIDAD.get(k, b) for k, b in zip(clave, bonito)], index=serie.index)

def limpiar_concepto(serie: pd.Series) -> pd.Series:
    t = serie.fillna("").astype(str).str.upper().str.strip()
    t = t.str.replace(r"\S*\d\S*", " ", regex=True)
    t = t.str.replace(r"\b(?:N[°º]|NRO\.?|NO\.)(?=\s|$)", " ", regex=True)
    t = t.str.replace(r"[\s\-–—:/#.,%]+$", "", regex=True)
    t = t.str.replace(r"^[\s\-–—:/#.,%]+", "", regex=True)
    return t.str.replace(r"\s+", " ", regex=True).str.strip().replace("", "(Sin descripción)")

@st.cache_data(show_spinner=False)
def cargar_datos(file) -> pd.DataFrame:
    df = pd.read_excel(file)
    df.columns = [str(c).strip() for c in df.columns]
    
    col_fecha = next((c for c in COL_FECHA if c in df.columns), None)
    col_imp = next((c for c in ("Importe_Graficar", "Importe en ML") if c in df.columns), None)
    
    out = pd.DataFrame(index=df.index)
    out["Fecha"] = pd.to_datetime(df[col_fecha], errors="coerce")
    neto = pd.to_numeric(df.get("Importe en ML", df[col_imp]), errors="coerce")
    out["Importe_Neto"] = neto
    out["Importe"] = pd.to_numeric(df[col_imp], errors="coerce").abs()
    out["Naturaleza"] = np.where(neto < 0, NAT_MENOR, NAT_GASTO)
    
    out["Rubro"] = df.get("Nombre cuenta", pd.Series("Sin rubro", index=df.index)).fillna("Sin rubro").astype(str).str.title()
    out["Tipo"] = df.get("Tipo", pd.Series("General", index=df.index)).fillna("Sin clasificar").astype(str).str.title()
    out["Entidad"] = limpiar_entidad(df.get("Clave referencia 3", pd.Series(np.nan, index=df.index)))
    out["Concepto"] = limpiar_concepto(df.get("Texto", pd.Series("", index=df.index)))
    
    out = out.dropna(subset=["Fecha", "Importe"]).reset_index(drop=True)
    out["Año"] = out["Fecha"].dt.year.astype(int)
    out["Mes"] = out["Fecha"].dt.month.astype(int)
    out["Periodo"] = out["Fecha"].dt.strftime("%Y-%m")
    out["Mes_Nombre"] = out["Mes"].map(MESES_ABR)
    out["Periodo_Label"] = out["Mes_Nombre"] + " " + out["Año"].astype(str)
    
    return out

def analizar_tendencia(serie: pd.Series) -> dict:
    n = len(serie)
    vacio = dict(estado="Datos insuficientes", color=CORP_GRAY)
    if n == 0: return vacio
    media = float(serie.mean())
    if n <= 2: return {"estado": "➡️ Estable", "color": CORP_GRAY}
    
    y, x = serie.to_numpy(dtype=float), np.arange(n)
    pend, _ = np.polyfit(x, y, 1)
    umbral = 0.015 * media
    
    if pend > umbral: return {"estado": "📈 Alcista (Expansión)", "color": CORP_GRAY}
    elif pend < -umbral: return {"estado": "📉 Bajista (Contracción)", "color": BAJA}
    else: return {"estado": "➡️ Estable (Controlado)", "color": CORP_GRAY}

# =============================================================================
# 4. CONFIGURACIÓN UI Y LOGIN
# =============================================================================
st.set_page_config(page_title=APP_TITULO, page_icon="📊", layout="wide", initial_sidebar_state="expanded")

st.markdown(f'''
    <style>
    .titulo-panel {{
        background: linear-gradient(90deg, #101820 0%, #1a2530 100%);
        color: #FEE715; text-align: left; font-weight: 600; padding: 12px 20px; 
        border-radius: 8px; margin-bottom: 20px; font-size: 18px;
        box-shadow: 0px 4px 10px rgba(0,0,0,0.15); letter-spacing: 0.5px;
    }}
    div[data-testid="stThumbValue"] {{ background-color: {CORP_GRAY} !important; color: #FFFFFF !important; font-weight: bold; border-radius: 4px; }}
    div[data-testid="metric-container"] {{
        background-color: #ffffff; border: 1px solid #EAECEE; border-radius: 10px; 
        padding: 20px; box-shadow: 0px 4px 15px rgba(0,0,0,0.04);
        border-left: 6px solid {CORP_BLUE}; transition: transform 0.2s ease-in-out;
    }}
    div[data-testid="metric-container"]:hover {{ transform: translateY(-3px); box-shadow: 0px 6px 20px rgba(0,0,0,0.08); }}
    </style>
''', unsafe_allow_html=True)

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False
if "user_type" not in st.session_state:
    st.session_state.user_type = None
if "login_time" not in st.session_state:
    st.session_state.login_time = None

def check_password():
    pwd = st.session_state.password
    if pwd == "basico123":
        st.session_state.authenticated, st.session_state.user_type, st.session_state.login_time = True, "Básico", time.time()
    elif pwd == "premium123":
        st.session_state.authenticated, st.session_state.user_type, st.session_state.login_time = True, "Premium", time.time()
    else:
        st.warning("⚠️ Clave incorrecta. Intente nuevamente.")

if not st.session_state.authenticated:
    st.title("🔐 Portal de Inteligencia Financiera")
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.text_input("Clave de acceso:", type="password", key="password")
        st.button("Ingresar de forma segura", on_click=check_password, use_container_width=True)
    st.stop()

if st.session_state.user_type == "Básico":
    if time.time() - st.session_state.login_time > LIMITE_BASICO_S:
        st.session_state.authenticated = False
        st.warning("⏳ Tiempo de sesión (Básico) finalizado.")
        st.stop()
    else:
        st.sidebar.warning("👁️ Modo Básico Activo (1 min)")
else:
    st.sidebar.success("👑 Modo Analista Premium Activo")

if st.sidebar.button("Cerrar Sesión"):
    st.session_state.authenticated = False
    st.rerun()

st.sidebar.markdown("---")

# =============================================================================
# 5. PANEL LATERAL (CARGA Y FILTROS)
# =============================================================================
st.sidebar.title("🎛️ Filtros de Análisis")
archivo_subido = st.sidebar.file_uploader("📂 Origen de Datos (Excel)", type=["xlsx", "xls"])

if not archivo_subido:
    st.info("👋 Por favor, cargue su archivo de Excel normalizado para desplegar el tablero.")
    st.stop()

with st.spinner("Construyendo modelo de datos (ETL)..."):
    df = cargar_datos(archivo_subido)

st.sidebar.markdown('<div class="titulo-panel" style="font-size:15px; padding:8px;">Periodos</div>', unsafe_allow_html=True)
meses_sel = st.sidebar.multiselect("Meses:", list(MESES_LARGO.values()), default=list(MESES_LARGO.values()))
meses_ids = [k for k, v in MESES_LARGO.items() if v in meses_sel]

min_y, max_y = df['Año'].min(), df['Año'].max()
anios = st.sidebar.slider("Ejercicio (Año)", min_y, max_y, (min_y, max_y)) if min_y != max_y else (min_y, max_y)

st.sidebar.markdown("### Origen de Cuenta")
tipos_sel = [t for t in df['Tipo'].dropna().unique() if st.sidebar.checkbox(str(t), value=True)]

df_filt = df[(df['Año'] >= anios[0]) & (df['Año'] <= anios[1]) & (df['Mes'].isin(meses_ids)) & (df['Tipo'].isin(tipos_sel))]

# =============================================================================
# 6. FILTRADO CRUZADO BIDIRECCIONAL Y KPIs
# =============================================================================
cuenta_sel = None
if "grafico_cuentas" in st.session_state:
    puntos_c = st.session_state["grafico_cuentas"].get("selection", {}).get("points", [])
    if puntos_c: cuenta_sel = puntos_c[0]["y"]

entidad_sel = None
if "grafico_entidades" in st.session_state:
    puntos_e = st.session_state["grafico_entidades"].get("selection", {}).get("points", [])
    if puntos_e: entidad_sel = puntos_e[0]["y"]

# Dataframes para los gráficos (ignoran su propio filtro para permitir visualizar el resto del top y deseleccionar)
df_para_cuentas = df_filt[df_filt['Entidad'] == entidad_sel] if entidad_sel else df_filt
df_para_entidades = df_filt[df_filt['Rubro'] == cuenta_sel] if cuenta_sel else df_filt

# Dataframe dinámico total (Aplica todos los clics y filtros de la página)
df_dinamico = df_filt.copy()
if cuenta_sel: df_dinamico = df_dinamico[df_dinamico['Rubro'] == cuenta_sel]
if entidad_sel: df_dinamico = df_dinamico[df_dinamico['Entidad'] == entidad_sel]


st.markdown('<div class="titulo-panel">Resumen Ejecutivo de Métricas</div>', unsafe_allow_html=True)
kpi1, kpi2, kpi3, kpi4 = st.columns(4)

total_gastos = df_dinamico['Importe'].sum()
meses_unicos = df_dinamico['Periodo'].nunique()
prom_mensual = total_gastos / meses_unicos if meses_unicos > 0 else 0
tendencia_res = analizar_tendencia(df_dinamico.groupby('Periodo')['Importe'].sum().sort_index())

filtros_activos = []
if cuenta_sel: filtros_activos.append(cuenta_sel)
if entidad_sel: filtros_activos.append(entidad_sel)
txt_segmento = " + ".join(filtros_activos) if filtros_activos else "Consolidado Global"

kpi1.metric("Importe Acumulado", format_currency(total_gastos))
kpi2.metric("Media de Gasto Mensual", format_currency(prom_mensual))
kpi3.metric("Vector de Tendencia", tendencia_res["estado"])
kpi4.metric("Segmento Analizado", txt_segmento)

# =============================================================================
# 7. VISUALIZACIONES PLOTLY
# =============================================================================
st.markdown("---")
st.markdown('<div class="titulo-panel">Evolución Cronológica del Gasto</div>', unsafe_allow_html=True)
tend = df_dinamico.groupby(['Periodo', 'Periodo_Label'])['Importe'].sum().reset_index().sort_values('Periodo')

fig_line = go.Figure()
if not tend.empty:
    fig_line.add_trace(go.Scatter(
        x=tend['Periodo_Label'], y=tend['Importe'], mode='lines+markers+text',
        text=tend['Importe'].apply(fmt), textposition='top center',
        line=dict(color=CORP_GRAY, width=3.5), marker=dict(color=CORP_BLUE, size=10, line=dict(width=2, color='white')),
        fill='tozeroy', fillcolor=f'rgba(31, 97, 141, 0.1)'
    ))
fig_line.update_layout(
    plot_bgcolor='rgba(0,0,0,0)', paper_bgcolor='rgba(0,0,0,0)', margin=dict(l=20, r=20, t=20, b=20),
    height=350, xaxis=dict(showgrid=True, gridcolor='#EAECEE'), yaxis=dict(showgrid=False, visible=False)
)
st.plotly_chart(fig_line, use_container_width=True)

col_bar1, col_bar2 = st.columns(2)
with col_bar1:
    st.markdown('<div class="titulo-panel">Distribución por Rubro Contable</div>', unsafe_allow_html=True)
    st.caption("👆 *Interactivo: Seleccione un rubro para filtrar.*")
    
    cuenta_df = df_para_cuentas.groupby('Rubro')['Importe'].sum().reset_index().sort_values('Importe')
    cuenta_df['Texto_Hover'] = cuenta_df['Importe'].apply(fmt)
    colores_c = [CORP_BLUE if (not cuenta_sel or c == cuenta_sel) else CORP_BLUE_SOFT for c in cuenta_df['Rubro']]
    
    fig_bar1 = px.bar(cuenta_df, x='Importe', y='Rubro', text='Texto_Hover', orientation='h')
    fig_bar1.update_traces(marker_color=colores_c, textposition='outside')
    fig_bar1.update_layout(plot_bgcolor='rgba(0,0,0,0)', xaxis=dict(visible=False), yaxis=dict(title=""), margin=dict(l=10, r=50, t=10, b=10), height=400, clickmode='event+select')
    st.plotly_chart(fig_bar1, use_container_width=True, on_select="rerun", selection_mode="points", key="grafico_cuentas")

with col_bar2:
    st.markdown('<div class="titulo-panel">Concentración por Entidad / Tercero</div>', unsafe_allow_html=True)
    st.caption("👆 *Interactivo: Seleccione un tercero para filtrar.*")
    
    banco_df = df_para_entidades.groupby('Entidad')['Importe'].sum().reset_index().sort_values('Importe').tail(15)
    banco_df['Texto_Hover'] = banco_df['Importe'].apply(fmt)
    colores_e = [CORP_BLUE if (not entidad_sel or e == entidad_sel) else CORP_BLUE_SOFT for e in banco_df['Entidad']]
    
    fig_bar2 = px.bar(banco_df, x='Importe', y='Entidad', text='Texto_Hover', orientation='h')
    fig_bar2.update_traces(marker_color=colores_e, textposition='outside')
    fig_bar2.update_layout(plot_bgcolor='rgba(0,0,0,0)', xaxis=dict(visible=False), yaxis=dict(title=""), margin=dict(l=10, r=50, t=10, b=10), height=400, clickmode='event+select')
    st.plotly_chart(fig_bar2, use_container_width=True, on_select="rerun", selection_mode="points", key="grafico_entidades")

# =============================================================================
# 8. MATRIZ MoM Y ASISTENTE IA NLP
# =============================================================================
st.markdown("---")
col_var, col_chat = st.columns([1.5, 1.2])

with col_var:
    st.markdown('<div class="titulo-panel">Matriz de Variación Mensual (MoM)</div>', unsafe_allow_html=True)
    if len(tend) > 1:
        tend['Variación %'] = tend['Importe'].pct_change() * 100
        df_mostrar = tend[['Periodo_Label', 'Importe', 'Variación %']].copy()
        df_mostrar.columns = ['Periodo', 'Importe Total', 'Variación vs Anterior (%)']
        def highlight_var(val):
            if pd.isna(val): return ''
            return f'color: {CORP_GRAY}; font-weight: 600;' if val > 0 else f'color: {BAJA}; font-weight: 600;'
        st.dataframe(df_mostrar.style.format({'Importe Total': lambda x: f"${x:,.0f}", 'Variación vs Anterior (%)': lambda x: f"{x:+.2f}%" if pd.notna(x) else "-"}).map(highlight_var, subset=['Variación vs Anterior (%)']), use_container_width=True, height=350)
    else:
        st.info("💡 Faltan periodos secuenciales para variaciones (MoM).")

with col_chat:
    st.markdown('<div class="titulo-panel">Asistente Analítico Inteligente</div>', unsafe_allow_html=True)
    pregunta = st.chat_input("Escriba su consulta analítica aquí...")
    if pregunta:
        st.chat_message("user").write(pregunta)
        q = normalizar(pregunta)
        respuesta = ""
        
        if df_filt.empty:
            respuesta = "⚠️ El dataset actual carece de registros bajo los filtros seleccionados."
        else:
            cuenta_mencionada = next((c for c in df_filt['Rubro'].dropna().unique() if normalizar(c) in q), cuenta_sel)
            
            if any(p in q for p in ["por que", "porque", "razon", "motivo", "texto", "detalle", "explica", "justifica"]):
                if not cuenta_mencionada:
                    respuesta = "🔍 **Precisión requerida:** Por favor, especifique el rubro contable a auditar.\n\n*Ejemplo: 'Detalle de Comisiones'*"
                else:
                    df_txt = df_filt[df_filt['Rubro'] == cuenta_mencionada]
                    top_textos = df_txt[df_txt['Concepto'] != "(Sin descripción)"].groupby('Concepto')['Importe'].sum().sort_values(ascending=False).head(5)
                    
                    if not top_textos.empty:
                        detalles_str = "\n".join([f"- {txt}: **{format_currency(imp)}**" for txt, imp in top_textos.items()])
                        respuesta = f"📑 **Auditoría de Rubro: {cuenta_mencionada}**\nDesglose de conceptos base:\n\n{detalles_str}"
                        if "gravamen" in cuenta_mencionada.lower():
                            if "diciembre" in q or "junio" in q: respuesta += "\n\n💡 *Insight:* Alzas vinculadas a pagos de primas."
                            elif "enero" in q: respuesta += "\n\n💡 *Insight:* Egresos correspondientes a pago de cesantías."
                        elif "comision" in cuenta_mencionada.lower() and ("diciembre" in q or "ano" in q):
                            respuesta += "\n\n💡 *Insight:* Pico transaccional por mayor recaudo estacional."
                    else:
                        respuesta = f"⚠️ El rubro **{cuenta_mencionada}** carece de conceptos detallados."
            
            elif "mayor" in q and ("cuenta" in q or "rubro" in q):
                c_max = df_dinamico.groupby('Rubro')['Importe'].sum().idxmax()
                respuesta = f"🏆 El rubro con mayor impacto es **{c_max}** ({format_currency(df_dinamico.groupby('Rubro')['Importe'].sum().max())})."
            elif ("mayor" in q or "mas" in q) and ("banco" in q or "entidad" in q or "tercero" in q):
                b_max = df_dinamico.groupby('Entidad')['Importe'].sum().idxmax()
                respuesta = f"🏦 La entidad con mayor pago es **{b_max}** ({format_currency(df_dinamico.groupby('Entidad')['Importe'].sum().max())})."
            elif "total" in q or "suma" in q:
                respuesta = f"💰 El **capital total egresado** en este segmento es **{format_currency(total_gastos)}**."
            elif "promedio" in q or "media" in q:
                respuesta = f"⚖️ El **gasto promedio mensual** es **{format_currency(prom_mensual)}**."
            else:
                top_sug = df_dinamico.groupby('Rubro')['Importe'].sum().idxmax() if not df_dinamico.empty else "Gravamen"
                respuesta = f"🤖 **Consulta no catalogada.** Intente:\n1. *¿Cuál es el detalle del rubro {top_sug}?*\n2. *¿Cuál es el mayor banco?*\n3. *¿Total acumulado?*"
                
        with st.chat_message("assistant"):
            st.write(respuesta)
    else:
        st.info("💬 **Asistente Preparado:** Aclaraciones sobre rubros")
