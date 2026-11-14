def scan_q3_q4():
    games = get_espn_games()
    if not games: return
    partidos_validos = []
    for g in games:
        if g["id"] in partidos_alertados: continue
        is_q3_end = "End of 3rd" in g["status"] or (g["period"] == 3 and g["clock"] in ["0.0", "0:00"])
        is_q4 = (g["period"] == 4 and g["status"] != "Final")
        if is_q3_end or is_q4:
            partidos_validos.append(g)
            
    if not partidos_validos: return
    print(f"🔍 Escaneando {len(partidos_validos)} partidos en Q3/Q4...")
    infer_odds = get_infer_odds()
    
    for g in partidos_validos:
        # Calcular puntos de los 3 primeros cuartos
        t3_home = sum(g["q_h"][:3]) if len(g["q_h"]) >= 3 else sum(g["q_h"])
        t3_away = sum(g["q_a"][:3]) if len(g["q_a"]) >= 3 else sum(g["q_a"])
        t3_total = t3_home + t3_away
        if t3_total == 0: continue
        
        # --- NUEVA REGLA: Diferencia de puntos no mayor a 30 ---
        margen = abs(t3_home - t3_away)
        if margen > 30:
            print(f"⏭️ Saltando {g['matchup']} (Diferencia de {margen} pts > 30)")
            continue
        # ---------------------------------------------------------
        
        proyeccion = t3_total * 1.25
        limite_maximo = proyeccion + 4
        limite_radar = limite_maximo + 5
        
        event_key = f"{g['away_key']}_vs_{g['home_key']}"
        ln = infer_odds.get(event_key)
        if not ln: continue
        linea_actual = ln["line"]
        
        # 1. ALERTA REAL
        if linea_actual <= limite_maximo:
            msg = (
                f"📡 <b>ALERTA DE VALOR — OVER (Q3/Q4)</b>\n\n"
                f"🏀 <b>{g['matchup']}</b>\n"
                f"⏱️ <b>Estado:</b> P{g['period']} ({g['clock']})\n\n"
                f"📊 <b>Puntos Q1-Q3:</b> {t3_total} pts (Dif: {margen})\n"
                f"📈 <b>Proyección Base:</b> {proyeccion:.1f} pts\n"
                f"🎯 <b>Límite permitido (+4):</b> {limite_maximo:.1f}\n\n"
                f"📌 <b>Línea en vivo:</b> {linea_actual:.1f}\n"
                f"🪙 <b>Cuota Over:</b> @{ln['over']:.2f}\n\n"
                f"💡 <b>Recomendación:</b> <b>⬆️ OVER {linea_actual:.1f}</b>"
            )
            if enviar_telegram(msg):
                partidos_alertados.add(g["id"])
                guardar_alerta_en_db(g["id"], g["matchup"], t3_total, proyeccion, limite_maximo, linea_actual, ln['over'])
                print(f"✅ Alerta enviada y guardada para {g['matchup']}")
                
        # 2. RADAR
        elif limite_maximo < linea_actual <= limite_radar:
            if g["id"] not in partidos_radar:
                distancia = linea_actual - limite_maximo
                msg_radar = (
                    f"🟡 <b>RADAR: SEÑAL CERCA (Q3/Q4)</b>\n\n"
                    f"🏀 <b>{g['matchup']}</b>\n"
                    f"⏱️ <b>Estado:</b> P{g['period']} ({g['clock']})\n\n"
                    f"📊 <b>Puntos Q1-Q3:</b> {t3_total} pts (Dif: {margen})\n"
                    f"📈 <b>Proyección Base:</b> {proyeccion:.1f} pts\n"
                    f"🎯 <b>Límite de Apuesta (+4):</b> {limite_maximo:.1f}\n\n"
                    f"📌 <b>Línea en vivo:</b> {linea_actual:.1f}\n"
                    f"⚠️ <b>Distancia al objetivo:</b> Faltan {distancia:.1f} pts\n\n"
                    f"💡 <b>Prepárate:</b> La línea está cerca. Atento a tu app para el <b>OVER {limite_maximo:.1f}</b>."
                )
                if enviar_telegram(msg_radar):
                    partidos_radar.add(g["id"])
                    print(f"🟡 Radar enviado para {g['matchup']} (Línea a {distancia:.1f} pts)")
