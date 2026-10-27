import streamlit as st
import pandas as pd
import plotly.express as px
import time

st.set_page_config(page_title="Dashboard Financiero", layout="wide")

# --- SISTEMA DE LOGIN ---
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
        st.error("Clave incorrecta")

if not st.session_state.authenticated:
    st.title("Acceso al Dashboard")
    st.text_input("Clave de acceso", type="password", key="password")
    st.button("Ingresar", on_click=check_password)
    st.info("💡 Claves: Básico: `basico123` (1 min) | Premium: `premium123` (Ilimitado)")
    st.stop()

if st.session_state.user_type == "Básico":
    elapsed = time.time() - st.session_state.login_time
    if elapsed > 60:
        st.session_state.authenticated = False
        st.warning("Tiempo expirado.")
        st.stop()
    else:
        st.sidebar.info(f"Básico - Expira en {int(60 - elapsed)}s")
        st.sidebar.button("Actualizar")
else:
    st.sidebar.success("Usuario Premium")

if st.sidebar.button("Cerrar Sesión"):
    st.session_state.authenticated = False
    st.rerun()

# --- CARGAR DATOS ---
@st.cache_data
def load_data():
    df = pd.read_excel('gastos_limpios.xlsx')
    date_col = 'Fe-contab-' if 'Fe-contab-' in df.columns else 'Fe/contab/'
    df['Fecha'] = pd.to_datetime(df[date_col], errors='coerce')
    df['Año'] = df['Fecha'].dt.year
    df['Mes'] = df['Fecha'].dt.month
    return df

df = load_data()

# --- FILTROS ---
st.sidebar.markdown("### Filtros")
min_y, max_y = int(df['Año'].min()), int(df['Año'].max())
anios = st.sidebar.slider("Año", min_y, max_y, (min_y, max_y))

meses_dict = {1:'Ene', 2:'Feb', 3:'Mar', 4:'Abr', 5:'May', 6:'Jun', 7:'Jul', 8:'Ago', 9:'Sep', 10:'Oct', 11:'Nov', 12:'Dic'}
meses_sel = st.sidebar.multiselect("Meses", list(meses_dict.keys()), format_func=lambda x: meses_dict[x], default=list(meses_dict.keys()))

st.sidebar.markdown("### Origen (Tipo)")
tipos_sel = [t for t in df['Tipo'].dropna().unique() if st.sidebar.checkbox(str(t), value=True)]

df_filt = df[(df['Año'] >= anios[0]) & (df['Año'] <= anios[1]) & (df['Mes'].isin(meses_sel)) & (df['Tipo'].astype(str).isin(tipos_sel))]

# --- PANEL PRINCIPAL ---
st.title("Dashboard de Gastos")
cuentas_disp = df_filt['Nombre cuenta'].dropna().unique().tolist()
cuenta_sel = st.multiselect("Filtrar Cuentas", cuentas_disp, default=cuentas_disp)
df_filt = df_filt[df_filt['Nombre cuenta'].isin(cuenta_sel)]

col1, col2 = st.columns([2, 1])

with col1:
    st.markdown("#### Tendencia Consolidada")
    tendencia = df_filt.groupby(['Año', 'Mes']).agg({'Importe_Graficar': 'sum'}).reset_index()
    if not tendencia.empty:
        tendencia['Periodo'] = tendencia['Año'].astype(str) + '-' + tendencia['Mes'].astype(str).str.zfill(2)
        fig_line = px.line(tendencia.sort_values(['Año', 'Mes']), x='Periodo', y='Importe_Graficar', markers=True)
        st.plotly_chart(fig_line, use_container_width=True)

with col2:
    st.markdown("#### Tipo de Cuenta")
    cuenta_df = df_filt.groupby('Nombre cuenta').agg({'Importe_Graficar': 'sum'}).reset_index().sort_values('Importe_Graficar')
    fig_bar1 = px.bar(cuenta_df, x='Importe_Graficar', y='Nombre cuenta', orientation='h')
    st.plotly_chart(fig_bar1, use_container_width=True)

st.markdown("#### Top 20 por Referencia")
banco_df = df_filt.groupby('Clave referencia 3').agg({'Importe_Graficar': 'sum'}).reset_index().sort_values('Importe_Graficar').tail(20)
fig_bar2 = px.bar(banco_df, x='Importe_Graficar', y='Clave referencia 3', orientation='h')
st.plotly_chart(fig_bar2, use_container_width=True)

# --- MATRIZ ---
if not tendencia.empty:
    st.markdown("#### Matriz de Variaciones")
    tendencia['Var %'] = tendencia['Importe_Graficar'].pct_change() * 100
    st.dataframe(tendencia[['Periodo', 'Importe_Graficar', 'Var %']].style.format({'Importe_Graficar': '${:,.2f}', 'Var %': '{:+.2f}%'}), use_container_width=True)
