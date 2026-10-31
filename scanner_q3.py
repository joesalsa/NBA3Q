import os
import libsql
import requests
from datetime import datetime
from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
import uvicorn

# ==========================================
# CONFIGURACIÓN
# ==========================================
INFER_API_KEY = os.environ.get("INFER_API_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
TURSO_URL = os.environ.get("TURSO_DATABASE_URL")
TURSO_TOKEN = os.environ.get("TURSO_AUTH_TOKEN")

app = FastAPI()
partidos_alertados = set()

# ==========================================
# BASE DE DATOS (TURSO)
# ==========================================
def get_db():
    return libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN)

def init_db():
    try:
        con = get_db()
        con.execute("""
            CREATE TABLE IF NOT EXISTS alertas_q3 (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT UNIQUE,
                matchup TEXT,
                q3_points INTEGER,
                proyeccion REAL,
                limite REAL,
                linea_real REAL,
                cuota_over REAL,
                timestamp TEXT
            )
        """)
        con.commit()
        con.close()
    except Exception as e:
        print(f"[DB Error] {e}")

def guardar_alerta_en_db(event_id, matchup, q3_points, proyeccion, limite, linea, cuota):
    try:
        con = get_db()
        con.execute("""
            INSERT OR IGNORE INTO alertas_q3 
            (event_id, matchup, q3_points, proyeccion, limite, linea_real, cuota_over, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (event_id, matchup, q3_points, proyeccion, limite, linea, cuota, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        con.commit()
        con.close()
        print(f"💾 Alerta guardada en Turso: {matchup}")
    except Exception as e:
        print(f"[DB Error] {e}")

# ==========================================
# TRADUCTOR MAESTRO DE EQUIPOS
# ==========================================
def get_team_key(name):
    n = name.lower()
    if "hawks" in n: return "atlanta"
    if "celtics" in n: return "boston"
    if "nets" in n: return "brooklyn"
    if "hornets" in n: return "charlotte"
    if "bulls" in n: return "chicago"
    if "cavaliers" in n or "cavs" in n: return "cleveland"
    if "mavericks" in n or "mavs" in n: return "dallas"
    if "nuggets" in n: return "denver"
    if "pistons" in n: return "detroit"
    if "warriors" in n or "warrior" in n or "gsw" in n: return "goldenstate"
    if "rockets" in n: return "houston"
    if "pacers" in n: return "indiana"
    if "clippers" in n or "lac" in n: return "clippers"
    if "lakers" in n or "lal" in n: return "lakers"
    if "grizzlies" in n: return "memphis"
    if "heat" in n: return "miami"
    if "bucks" in n: return "milwaukee"
    if "timberwolves" in n or "wolves" in n or "min" in n: return "minnesota"
    if "pelicans" in n or "nop" in n: return "neworleans"
    if "knicks" in n or "nyk" in n: return "newyork"
    if "thunder" in n or "okc" in n: return "oklahomacity"
    if "magic" in n or "orl" in n: return "orlando"
    if "76ers" in n or "sixers" in n or "phi" in n: return "philadelphia"
    if "suns" in n or "pho" in n: return "phoenix"
    if "blazers" in n or "trail blazers" in n or "por" in n: return "portland"
    if "kings" in n or "sac" in n: return "sacramento"
    if "spurs" in n or "sas" in n: return "sanantonio"
    if "raptors" in n or "tor" in n: return "toronto"
    if "jazz" in n or "uta" in n: return "utah"
    if "wizards" in n or "was" in n: return "washington"
    return n

# ==========================================
# TELEGRAM
# ==========================================
def enviar_telegram(mensaje):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
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
                "away_key": get_team_key(away.get('team', {}).get('displayName', '')),
                "home_key": get_team_key(home.get('team', {}).get('displayName', '')),
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
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Authorization': f'Bearer {INFER_API_KEY}'
        }
        r = requests.get("https://api.infersports.dev/v1/events/live", headers=headers, timeout=15)
        if r.status_code != 200: return {}
        
        events = [ev for ev in r.json().get("data", []) if ev.get("sport") == "basketball" and ev.get("league", {}).get("name") == "NBA"]
        odds_dict = {}
        
        for ev in events:
            away_key = get_team_key(ev["away_team"]["name"])
            home_key = get_team_key(ev["home_team"]["name"])
            event_key = f"{away_key}_vs_{home_key}"
            
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
                            mejor_odd = {"line": float(odd.get("line")), "over": over_p}
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
        t3_home = sum(g["q_h"][:3]) if len(g["q_h"]) >= 3 else sum(g["q_h"])
        t3_away = sum(g["q_a"][:3]) if len(g["q_a"]) >= 3 else sum(g["q_a"])
        t3_total = t3_home + t3_away
        
        if t3_total == 0: continue
            
        proyeccion = t3_total * 1.25
        limite_maximo = proyeccion + 6
        
        event_key = f"{g['away_key']}_vs_{g['home_key']}"
        ln = infer_odds.get(event_key)
        
        if not ln: continue
            
        linea_actual = ln["line"]
        
        if linea_actual <= limite_maximo:
            msg = (
                f"📡 <b>ALERTA DE VALOR — OVER (Q3/Q4)</b>\n\n"
                f"🏀 <b>{g['matchup']}</b>\n"
                f"⏱️ <b>Estado:</b> P{g['period']} ({g['clock']})\n\n"
                f"📊 <b>Puntos Q1-Q3:</b> {t3_total} pts\n"
                f"📈 <b>Proyección Base:</b> {proyeccion:.1f} pts\n"
                f"🎯 <b>Límite permitido (+6):</b> {limite_maximo:.1f}\n\n"
                f"📌 <b>Línea en vivo:</b> {linea_actual:.1f}\n"
                f"🪙 <b>Cuota Over:</b> @{ln['over']:.2f}\n\n"
                f"💡 <b>Recomendación:</b> <b>⬆️ OVER {linea_actual:.1f}</b>"
            )
            
            if enviar_telegram(msg):
                partidos_alertados.add(g["id"])
                # Guardar en Turso
                guardar_alerta_en_db(g["id"], g["matchup"], t3_total, proyeccion, limite_maximo, linea_actual, ln['over'])
                print(f"✅ Alerta enviada y guardada para {g['matchup']}")

# ==========================================
# INICIO
# ==========================================
@app.on_event("startup")
def startup_event():
    init_db()
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(scan_q3_q4, "interval", seconds=60)
    scheduler.start()
    print("🚀 Q3/Q4 Scanner iniciado con Turso y Traductor Maestro.")

@app.get("/health")
@app.head("/health")
def health_check():
    return {"status": "ok"}

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("scanner_q3:app", host="0.0.0.0", port=port)
