import os
import requests
from datetime import datetime
from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
import uvicorn

# ==========================================
# CONFIGURACIÓN
# ==========================================
INFER_API_KEY = os.environ.get("INFER_API_KEY", "TU_CLAVE_AQUI")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "TU_TOKEN_AQUI")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "TU_CHAT_ID")

app = FastAPI()

# Memoria en RAM para no alertar dos veces el mismo partido
partidos_alertados = set()

# ==========================================
# TELEGRAM
# ==========================================
def enviar_telegram(mensaje):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": mensaje,
            "parse_mode": "HTML"
        }
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"[Telegram Error] {e}")
        return False

# ==========================================
# API: ESPN
# ==========================================
def get_espn_games():
    try:
        r = requests.get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard", timeout=15)
        out = []
        for ev in r.json().get("events", []):
            comp = ev.get("competitions", [{}])[0]
            cs = comp.get("competitors", [])
            if len(cs) < 2: continue
            home = next((c for c in cs if c.get("homeAway") == "home"), cs[0])
            away = next((c for c in cs if c.get("homeAway") == "away"), cs[1])
            
            q_h = [int(q.get("value", 0)) for q in home.get("linescores", [])]
            q_a = [int(q.get("value", 0)) for q in away.get("linescores", [])]
            
            st = ev.get("status", {})
            out.append({
                "id": ev.get("id"),
                "matchup": f"{away.get('team', {}).get('displayName')} vs {home.get('team', {}).get('displayName')}",
                "status": st.get("type", {}).get("description", ""),
                "period": int(st.get("period", 0) or 0),
                "clock": st.get("displayClock", "") or "",
                "q_h": q_h,
                "q_a": q_a,
                "total": sum(q_h) + sum(q_a)
            })
        return out
    except Exception as e:
        print(f"[ESPN Error] {e}")
        return []

# ==========================================
# API: INFERSPORTS
# ==========================================
def get_infer_odds():
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Authorization': f'Bearer {INFER_API_KEY}'
        }
        r = requests.get("https://api.infersports.dev/v1/events/live", headers=headers, timeout=15)
        if r.status_code != 200: return {}
        
        events = [ev for ev in r.json().get("data", []) if ev.get("sport") == "basketball" and ev.get("league", {}).get("name") == "NBA"]
        odds_dict = {}
        
        for ev in events:
            home_short = ev["home_team"]["name"].split(".")[-1].strip().lower().rstrip('s')
            away_short = ev["away_team"]["name"].split(".")[-1].strip().lower().rstrip('s')
            event_key = f"{away_short} vs {home_short}"
            
            r2 = requests.get(f"https://api.infersports.dev/v1/events/{ev['id']}/odds?format=decimal", headers=headers, timeout=15)
            if r2.status_code == 200:
                mejor_balance = 999
                mejor_odd = None
                for odd in r2.json().get("odds", []):
                    if odd.get("market_type") == "totals" and odd.get("period") == "full_time" and odd.get("status") == "open":
                        try:
                            over_p = float(odd["prices"].get("over", 0))
                            under_p = float(odd["prices"].get("under", 0))
                        except: continue
                        balance = abs(over_p - 2.0) + abs(under_p - 2.0)
                        if balance < mejor_balance:
                            mejor_balance = balance
                            mejor_odd = {
                                "line": float(odd.get("line")),
                                "over": over_p
                            }
                if mejor_odd:
                    odds_dict[event_key] = mejor_odd
        return odds_dict
    except Exception as e:
        print(f"[Infer Error] {e}")
        return {}

# ==========================================
# LÓGICA PRINCIPAL
# ==========================================
def scan_q3_q4():
    games = get_espn_games()
    if not games: return
    
    # 1. Filtrar solo los partidos que están en final de Q3 o en Q4
    partidos_validos = []
    for g in games:
        if g["id"] in partidos_alertados:
            continue
            
        is_q3_end = "End of 3rd" in g["status"] or (g["period"] == 3 and g["clock"] in ["0.0", "0:00"])
        is_q4 = (g["period"] == 4 and g["status"] != "Final") # En Q4 o prórroga
        
        if is_q3_end or is_q4:
            partidos_validos.append(g)
            
    # Si no hay partidos válidos, nos salimos SIN GASTAR CRÉDITOS de InferSports
    if not partidos_validos:
        return
        
    print(f"🔍 Escaneando {len(partidos_validos)} partidos en Q3/Q4...")
    infer_odds = get_infer_odds()
    
    for g in partidos_validos:
        # Calcular T3 (Puntos al final del 3er cuarto)
        # Como ESPN nos da los cuartos, sumamos Q1+Q2+Q3
        t3_home = sum(g["q_h"][:3]) if len(g["q_h"]) >= 3 else sum(g["q_h"])
        t3_away = sum(g["q_a"][:3]) if len(g["q_a"]) >= 3 else sum(g["q_a"])
        t3_total = t3_home + t3_away
        
        if t3_total == 0:
            continue
            
        # Proyección: T3 + (T3 / 4) = T3 * 1.25
        proyeccion = t3_total * 1.25
        limite_maximo = proyeccion + 6
        
        # Buscar la cuota del partido
        team_away = g["matchup"].split(" vs ")[0].split()[-1].lower().rstrip('s')
        team_home = g["matchup"].split(" vs ")[1].split()[-1].lower().rstrip('s')
        
        ln = None
        for key, odds in infer_odds.items():
            if team_away in key and team_home in key:
                ln = odds
                break
                
        if not ln:
            continue
            
        linea_actual = ln["line"]
        
        # 2. La condición mágica: Línea <= Límite
        if linea_actual <= limite_maximo:
            print(f"🚨 ALERTA: {g['matchup']} | Línea: {linea_actual} | Límite: {limite_maximo:.1f}")
            
            msg = (
                f"📡 <b>ALERTA DE VALOR — OVER (Q3/Q4)</b>\n\n"
                f"🏀 <b>{g['matchup']}</b>\n"
                f"⏱️ <b>Estado:</b> P{g['period']} ({g['clock']})\n\n"
                f"📊 <b>Puntos Q1-Q3:</b> {t3_total} pts\n"
                f"📈 <b>Proyección Base:</b> {proyeccion:.1f} pts\n"
                f"🎯 <b>Límite permitido (+6):</b> {limite_maximo:.1f}\n\n"
                f"📌 <b>Línea en vivo:</b> {linea_actual:.1f}\n"
                f"🪙 <b>Cuota Over:</b> @{ln['over']:.2f}\n\n"
                f"💡 <b>Recomendación:</b> <b>⬆️ OVER {linea_actual:.1f}</b>\n\n"
                f"🕑 <i>La línea entró en el rango establecido.</i>"
            )
            
            if enviar_telegram(msg):
                partidos_alertados.add(g["id"])
                print(f"✅ Alerta enviada a Telegram para {g['matchup']}")
            else:
                print("❌ Error al enviar a Telegram")

# ==========================================
# FASTAPI Y SCHEDULER
# ==========================================
@app.on_event("startup")
def startup_event():
    scheduler = BackgroundScheduler(timezone="UTC")
    # Revisa cada 60 segundos
    scheduler.add_job(scan_q3_q4, "interval", seconds=60)
    scheduler.start()
    print("🚀 Q3/Q4 Scanner iniciado. Buscando líneas en rango...")

@app.get("/health")
@app.head("/health")
def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("scanner_q3:app", host="0.0.0.0", port=port)
