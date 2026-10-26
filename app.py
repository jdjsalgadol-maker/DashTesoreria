# ==========================================
# 1. ANÁLISIS DE TENDENCIAS (VERSIÓN LIMPIA TOP 5)
# ==========================================
st.subheader("📈 Evolución y Tendencias")
if 'Clave referencia 3' in df_filtrado.columns:
    
    # 1. Identificar el Top 5 de bancos con mayor volumen
    top_bancos = df_filtrado.groupby('Clave referencia 3')['Importe en ML'].sum().nlargest(5).index.tolist()
    
    # 2. Agrupar el resto en "OTROS" para limpiar el gráfico
    df_graficos = df_filtrado.copy()
    df_graficos['Banco Agrupado'] = df_graficos['Clave referencia 3'].apply(
        lambda x: x if x in top_bancos else 'OTROS (Menor volumen)'
    )
    
    # 3. Preparar datos consolidados
    df_tendencia = df_graficos.groupby(['Periodo', 'Banco Agrupado'])['Importe en ML'].sum().reset_index()
    
    col1, col2 = st.columns(2)
    with col1:
        fig_line = px.line(
            df_tendencia, x='Periodo', y='Importe en ML', color='Banco Agrupado', 
            title="Variaciones Mensuales (Top 5 Entidades)", markers=True
        )
        # Ocultar la cuadrícula de fondo para mayor limpieza
        fig_line.update_layout(xaxis_showgrid=False, yaxis_showgrid=True)
        st.plotly_chart(fig_line, use_container_width=True)
        
    with col2:
        fig_bar = px.bar(
            df_tendencia, x='Periodo', y='Importe en ML', color='Banco Agrupado', 
            title="Composición del Gasto", barmode='stack'
        )
        fig_bar.update_layout(xaxis_showgrid=False, yaxis_showgrid=True)
        st.plotly_chart(fig_bar, use_container_width=True)
