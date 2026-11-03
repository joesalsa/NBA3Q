def check_results():
    try:
        con = get_db()
        # Agregamos 'matchup' a la consulta para usarlo en el mensaje
        cursor = con.execute("SELECT id, event_id, linea_real, matchup FROM alertas_q3 WHERE status = 'PENDING'")
        pending = cursor.fetchall()
        con.close()

        if not pending: return

        print(f"🔄 Verificando resultados de {len(pending)} alertas pendientes...")
        r = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard", timeout=15)
        games = r.json().get("events", [])
        
        for p in pending:
            alert_id = p[0]
            event_id = p[1]
            linea = p[2]
            matchup = p[3] # Nuevo campo obtenido
            
            game = next((g for g in games if g.get("id") == event_id), None)
            if not game: continue

            state = game.get("status", {}).get("type", {}).get("state", "")
            if state == "post":
                comp = game.get("competitions", [{}])[0]
                final_total = sum(int(c.get("score", 0) or 0) for c in comp.get("competitors", []))

                if final_total > linea: status = "WON"
                elif final_total < linea: status = "LOST"
                else: status = "PUSH"

                # Actualizar la base de datos
                con = get_db()
                con.execute("UPDATE alertas_q3 SET status = ?, final_total = ? WHERE id = ?", (status, final_total, alert_id))
                con.commit()
                con.close()
                print(f"✅ Resultado: {event_id} | {status} (Total: {final_total} vs Línea: {linea})")
                
                # --- NUEVO: Enviar mensaje a Telegram ---
                if status == "WON":
                    emoji = "✅"
                    resultado_txt = "GANADA"
                elif status == "LOST":
                    emoji = "❌"
                    resultado_txt = "PERDIDA"
                else:
                    emoji = "⚖️"
                    resultado_txt = "EMPATE"

                msg_resultado = (
                    f"🏁 <b>RESULTADO DE ALERTA #{alert_id}</b>\n\n"
                    f"🏀 <b>{matchup}</b>\n"
                    f"📌 <b>Línea apostada:</b> {linea:.1f}\n"
                    f"📊 <b>Total final:</b> {final_total} pts\n\n"
                    f"{emoji} <b>Resultado:</b> {resultado_txt}\n"
                    f"🕑 <i>El bot ha actualizado tu historial.</i>"
                )
                enviar_telegram(msg_resultado)
                
    except Exception as e:
        print(f"[check_results Error] {e}")
