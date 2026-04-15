import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
import os
import json
import threading
import math
import re
import csv
import logging
from datetime import datetime
from collections import deque
import pandas as pd
import numpy as np

# =========================================================
# LIBRERIAS GRAFICAS (ANTI-PARPADEO)
# =========================================================
from rich.live import Live
from rich.panel import Panel
from rich.console import Group, Console
from rich.text import Text
from rich.table import Table
from rich.layout import Layout
from rich.align import Align
from rich.status import Status

# =========================================================
# SISTEMA DE LOGGING PROFESIONAL
# =========================================================
logging.basicConfig(
    filename='radar_hft.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logging.info("Iniciando Radar Quantum Institucional...")

# =========================================================
# INFRAESTRUCTURA DE RED RESILIENTE (ANTI-CRASH)
# =========================================================
http_session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[500, 502, 503, 504])
http_session.mount('https://', HTTPAdapter(max_retries=retries))

# =========================================================
# CONFIGURACION SEGURA
# =========================================================
TELEGRAM_BOT_TOKEN = "" 
TELEGRAM_CHAT_ID = ""   
ALERTAS_SONORAS = True  

# =========================================================
# PALETA DE COLORES Y EMOJIS UI
# =========================================================
RESET = '[/]'
GREEN = '[bold green]'
DARK_GREEN = '[green]'
RED = '[bold red]'
DARK_RED = '[red]'
CYAN = '[bold cyan]'
YELLOW = '[bold yellow]'
MAGENTA = '[bold magenta]'
BOLD = '[bold]'
WHITE = '[bold white]'
DARK_GRAY = '[grey74]'

console = Console()

# =========================================================
# VALIDACION DE LIBRERIAS PROFESIONALES
# =========================================================
try:
    import websocket
    import pandas_ta as ta
except ImportError as e:
    logging.critical(f"Librerias faltantes: {e}")
    console.print(f"{RED}[!] Atencion! Faltan librerias profesionales.{RESET}")
    console.print(f"{YELLOW}Por favor, abre tu terminal y ejecuta el siguiente comando:{RESET}")
    console.print(f"{WHITE}pip install rich pandas pandas-ta websocket-client requests urllib3{RESET}")
    exit()

# =========================================================
# VARIABLES GLOBALES E INFRAESTRUCTURA
# =========================================================
is_running = True 
data_lock = threading.Lock() 

simbolo_rest = "BTCUSDT"
simbolo_ws = "btcusdt"
timeframes = ["1d", "4h", "1h"] 

bids_local = {}
asks_local = {}
last_update_id = 0
snapshot_loaded = False
eventos_en_cola = []

klines_data = {'1d': [], '4h': [], '1h': []}
indicadores = {'1d': {}, '4h': {}, '1h': {}}

precio_actual = 0.0
funding_rate = 0.0 
high_24h = 0.0
low_24h = float('inf')

# Filtros Institucionales
open_interest = 0.0
ls_ratio = 0.0 
btc_macro_trend = "CALIBRANDO"

tape_trades_count = 0
tape_speed = 0.0
last_tape_time = time.time()
cvd_history = deque(maxlen=60)

cache_proy = {
    '1h': {'dir': '', 'entrada': 0.0, 'sl': 0.0, 'tp': 0.0},
    '4h': {'dir': '', 'entrada': 0.0, 'sl': 0.0, 'tp': 0.0}
}

stats_mercado = {
    'cvd_sesion': 0.0,
    'vol_compras': 0.0,
    'vol_ventas': 0.0,
    'liq_longs': 0.0,  
    'liq_shorts': 0.0
}

ultima_alerta_telegram = 0
ultima_alerta_sonora = 0
ultima_alerta_csv = 0

recent_trades_vp = deque(maxlen=10000)

# =========================================================
# FUNCIONES AUXILIARES Y RENDERIZADO VISUAL
# =========================================================
def cargar_configuracion():
    global TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, ALERTAS_SONORAS
    archivo_config = 'config_radar.json'
    if not os.path.exists(archivo_config):
        plantilla = {"TELEGRAM_BOT_TOKEN": "", "TELEGRAM_CHAT_ID": "", "ALERTAS_SONORAS": True}
        try:
            with open(archivo_config, 'w', encoding='utf-8') as f: json.dump(plantilla, f, indent=4)
        except: pass
    else:
        try:
            with open(archivo_config, 'r', encoding='utf-8') as f:
                config = json.load(f)
                TELEGRAM_BOT_TOKEN = config.get("TELEGRAM_BOT_TOKEN", "")
                TELEGRAM_CHAT_ID = config.get("TELEGRAM_CHAT_ID", "")
                ALERTAS_SONORAS = config.get("ALERTAS_SONORAS", True)
        except: pass

def registrar_alerta_csv(datos_fila):
    global ultima_alerta_csv
    if time.time() - ultima_alerta_csv > 300:
        archivo_csv = 'registro_senales.csv'
        header = ['Fecha', 'Par', 'Temporalidad', 'Direccion', 'Entrada', 'TP', 'SL', 'Contexto', 'POC', 'VWAP', 'LS_Ratio', 'Divergencia']
        existe = os.path.exists(archivo_csv)
        try:
            with open(archivo_csv, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                if not existe: writer.writerow(header)
                writer.writerow(datos_fila)
            ultima_alerta_csv = time.time()
        except: pass

def formato_liq(p_liq, p_act, vol=0.0, moneda=""):
    if vol > 0:
        base = f"${p_liq:,.0f} [dim]({vol:,.1f} {moneda})[/dim]"
    else:
        base = f"${p_liq:,.0f}"
        
    if p_act > 0 and abs(p_liq - p_act) / p_act < 0.003:
        return f"{base} {YELLOW}🔥 [IMÁN]{RESET}"
    return base

def dibujar_barra(pct_bids):
    bloques_verdes = int((pct_bids / 100) * 20)
    bloques_rojos = max(0, 20 - bloques_verdes)
    return f"{GREEN}{'█' * bloques_verdes}{RESET}{RED}{'█' * bloques_rojos}{RESET}"

def dibujar_barra_madurez(pct):
    bloques_llenos = int((pct / 100) * 20)
    bloques_vacios = max(0, 20 - bloques_llenos)
    col = RED if pct < 40 else YELLOW if pct < 100 else GREEN
    return f"{col}{'━' * bloques_llenos}{RESET}{DARK_GRAY}{'╌' * bloques_vacios}{RESET}"

def formatear_tendencia(tendencia):
    if "ALCISTA" in tendencia: return f"{GREEN}🐂 {tendencia}{RESET}"
    elif "BAJISTA" in tendencia: return f"{RED}🐻 {tendencia}{RESET}"
    else: return f"{YELLOW}🦀 {tendencia}{RESET}"

def formatear_valle(valle_color, valor):
    if "VERDE CLARO" in valle_color: return f"{GREEN}🟩 Alcista (▲) [{valor:.2f}]{RESET}"
    elif "VERDE OSCURO" in valle_color: return f"{DARK_GREEN}🌲 Bajista (▼) [{valor:.2f}]{RESET}"
    elif "ROJO CLARO" in valle_color: return f"{RED}🟥 Bajista (▼) [{valor:.2f}]{RESET}"
    else: return f"{DARK_RED}🧱 Alcista (▲) [{valor:.2f}]{RESET}"

# =========================================================
# HERRAMIENTAS DE ALERTA
# =========================================================
def emitir_sonido():
    global ultima_alerta_sonora
    if ALERTAS_SONORAS and (time.time() - ultima_alerta_sonora > 60):
        print('\a') 
        ultima_alerta_sonora = time.time()

def enviar_telegram(mensaje):
    global ultima_alerta_telegram
    if TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID and (time.time() - ultima_alerta_telegram > 300):
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {"chat_id": TELEGRAM_CHAT_ID, "text": mensaje, "parse_mode": "HTML"}
        try:
            http_session.post(url, data=data, timeout=5)
            ultima_alerta_telegram = time.time()
        except: pass

# =========================================================
# FORMULAS EXACTAS DE TRADINGVIEW
# =========================================================
def procesar_indicadores(res):
    df = pd.DataFrame(res, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume', 'close_time', 'qav', 'num_trades', 'taker_base_vol', 'taker_quote_vol', 'ignore'])
    for col in ['open', 'high', 'low', 'close', 'volume']: 
        df[col] = df[col].astype(float)

    df['ema10'] = df['close'].ewm(span=10, adjust=False).mean()
    df['ema55'] = df['close'].ewm(span=55, adjust=False).mean()

    rsi_len = 14
    delta_rsi = df['close'].diff()
    gain = (delta_rsi.where(delta_rsi > 0, 0)).rolling(window=rsi_len).mean()
    loss = (-delta_rsi.where(delta_rsi < 0, 0)).rolling(window=rsi_len).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    df['atr'] = true_range.rolling(14).mean()

    length_sqz = 20
    highest_high = df['high'].rolling(window=length_sqz).max()
    lowest_low = df['low'].rolling(window=length_sqz).min()
    sma_close = df['close'].rolling(window=length_sqz).mean()
    
    avg_hl = (highest_high + lowest_low) / 2.0
    avg_all = (avg_hl + sma_close) / 2.0
    delta = df['close'] - avg_all

    x = np.arange(length_sqz)
    x_mean = (length_sqz - 1) / 2.0
    x_dev = x - x_mean
    sq_sum = np.sum(x_dev ** 2)

    def linreg(y):
        y_mean = np.mean(y)
        b = np.sum(x_dev * y) / sq_sum
        return y_mean + b * x_mean

    df['valle'] = delta.rolling(window=length_sqz).apply(linreg, raw=True)

    basis = df['close'].rolling(length_sqz).mean()
    dev = 2.0 * df['close'].rolling(length_sqz).std()
    upperBB = basis + dev
    lowerBB = basis - dev

    ma = df['close'].rolling(length_sqz).mean()
    rng = true_range.rolling(length_sqz).mean()
    upperKC = ma + rng * 1.5
    lowerKC = ma - rng * 1.5

    df['sqz_on'] = (lowerBB > lowerKC) & (upperBB < upperKC)

    length_adx = 14
    tr1 = df['high'] - df['low']
    tr2 = (df['high'] - df['close'].shift(1)).abs()
    tr3 = (df['low'] - df['close'].shift(1)).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    up_move = df['high'] - df['high'].shift(1)
    down_move = df['low'].shift(1) - df['low']
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

    tr_rma = tr.ewm(alpha=1.0/length_adx, adjust=False).mean()
    plus_di = pd.Series(plus_dm).ewm(alpha=1.0/length_adx, adjust=False).mean() / tr_rma * 100
    minus_di = pd.Series(minus_dm).ewm(alpha=1.0/length_adx, adjust=False).mean() / tr_rma * 100

    dx = (plus_di - minus_di).abs() / (plus_di + minus_di) * 100
    df['adx'] = dx.ewm(alpha=1.0/length_adx, adjust=False).mean()

    ultimo = df.iloc[-1]
    previo = df.iloc[-2]

    ind = {}
    ind['closes'] = df['close'].tolist()
    ind['ema10'] = ultimo['ema10']
    ind['ema55'] = ultimo['ema55']
    ind['rsi'] = ultimo['rsi']
    ind['atr'] = ultimo['atr']
    ind['sqz_on'] = ultimo['sqz_on']
    
    # EXTRAEMOS LOS LIMITES DEL RANGO (MÁXIMOS Y MÍNIMOS DE 20 PERIODOS)
    ind['hh_20'] = highest_high.iloc[-1]
    ind['ll_20'] = lowest_low.iloc[-1]
    
    valle_actual = ultimo['valle']
    valle_previo = previo['valle']
    ind['valle'] = valle_actual
    ind['valle_previo'] = valle_previo
    ind['valle_slope'] = valle_actual - valle_previo
    
    if valle_actual >= 0:
        if valle_actual > valle_previo: ind['valle_color'] = "VERDE CLARO (Alcista)"
        else: ind['valle_color'] = "VERDE OSCURO (Bajista)"
    else:
        if valle_actual < valle_previo: ind['valle_color'] = "ROJO CLARO (Bajista)"
        else: ind['valle_color'] = "ROJO OSCURO (Alcista)"
            
    ind['adx'] = ultimo['adx']
    ind['adx_slope'] = ultimo['adx'] - previo['adx']
    return ind

# =========================================================
# WEBSOCKETS Y WORKERS
# =========================================================
def actualizar_datos_globales():
    global klines_data, indicadores, funding_rate, high_24h, low_24h, open_interest, ls_ratio, btc_macro_trend, cvd_history
    while is_running:
        try:
            res_fut = http_session.get(f"https://fapi.binance.com/fapi/v1/premiumIndex?symbol={simbolo_rest}", timeout=5).json()
            if 'lastFundingRate' in res_fut: funding_rate = float(res_fut['lastFundingRate']) * 100
            
            res_24h = http_session.get(f"https://api.binance.com/api/v3/ticker/24hr?symbol={simbolo_rest}", timeout=5).json()
            if 'highPrice' in res_24h: 
                high_24h = float(res_24h['highPrice'])
                low_24h = float(res_24h['lowPrice'])

            res_oi = http_session.get(f"https://fapi.binance.com/fapi/v1/openInterest?symbol={simbolo_rest}", timeout=5).json()
            if 'openInterest' in res_oi: open_interest = float(res_oi['openInterest'])

            try:
                res_ls = http_session.get(f"https://fapi.binance.com/futures/data/globalLongShortAccountRatio?symbol={simbolo_rest}&period=1h&limit=1", timeout=5).json()
                if res_ls and isinstance(res_ls, list) and len(res_ls) > 0 and 'longShortRatio' in res_ls[0]:
                    ls_ratio = float(res_ls[0]['longShortRatio'])
                elif ls_ratio == 0.0: ls_ratio = 1.0 
            except Exception:
                if ls_ratio == 0.0: ls_ratio = 1.0

            for tf in timeframes:
                url = f"https://api.binance.com/api/v3/klines?symbol={simbolo_rest}&interval={tf}&limit=1000"
                res = http_session.get(url, timeout=5).json()
                indicadores[tf] = procesar_indicadores(res)
                klines_data[tf] = indicadores[tf]['closes']

            if simbolo_rest != "BTCUSDT":
                res_btc = http_session.get("https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=4h&limit=100", timeout=5).json()
                df_btc = pd.DataFrame(res_btc)[4].astype(float)
                ema10_btc = df_btc.ewm(span=10, adjust=False).mean().iloc[-1]
                ema55_btc = df_btc.ewm(span=55, adjust=False).mean().iloc[-1]
                close_btc = df_btc.iloc[-1]
                if ema10_btc > ema55_btc and close_btc > ema55_btc: btc_macro_trend = "ALCISTA"
                elif ema10_btc < ema55_btc and close_btc < ema55_btc: btc_macro_trend = "BAJISTA"
                else: btc_macro_trend = "RANGO"
            else:
                if '4h' in indicadores and 'ema10' in indicadores['4h']:
                    btc_macro_trend = "ALCISTA" if indicadores['4h']['ema10'] > indicadores['4h']['ema55'] else "BAJISTA"
                
            if precio_actual > 0:
                with data_lock:
                    cvd_history.append({'precio': precio_actual, 'cvd': stats_mercado['cvd_sesion']})
                
        except Exception as e:
            logging.warning(f"Error actualizando datos REST: {e}")
        time.sleep(15) 

def obtener_snapshot():
    global bids_local, asks_local, last_update_id, snapshot_loaded
    url = f"https://api.binance.com/api/v3/depth?symbol={simbolo_rest}&limit=5000"
    try:
        response = http_session.get(url, timeout=10); data = response.json()
        with data_lock:
            last_update_id = data['lastUpdateId']
            bids_local.clear(); asks_local.clear()
            for p, q in data['bids']: bids_local[float(p)] = float(q)
            for p, q in data['asks']: asks_local[float(p)] = float(q)
            snapshot_loaded = True
    except: pass

def on_message_spot(ws, message):
    global eventos_en_cola, bids_local, asks_local, last_update_id, precio_actual, stats_mercado, recent_trades_vp
    global tape_trades_count, tape_speed, last_tape_time
    
    if not is_running: return
    data = json.loads(message)
    if 'stream' not in data: return
    stream_name = data['stream']
    payload = data['data']
    
    with data_lock:
        if '@depth' in stream_name:
            if not snapshot_loaded: eventos_en_cola.append(payload)
            else:
                if eventos_en_cola:
                    for ev in eventos_en_cola: aplicar_evento(ev)
                    eventos_en_cola.clear()
                aplicar_evento(payload)
                
        elif '@aggTrade' in stream_name:
            p, q = float(payload['p']), float(payload['q'])
            vol_usd = p * q
            is_sell = payload['m']
            
            tape_trades_count += 1
            now = time.time()
            if now - last_tape_time >= 1.0:
                tape_speed = tape_trades_count / (now - last_tape_time)
                tape_trades_count = 0
                last_tape_time = now
            
            recent_trades_vp.append((p, vol_usd, is_sell))
            
            if is_sell:
                stats_mercado['cvd_sesion'] -= vol_usd
                stats_mercado['vol_ventas'] += vol_usd
            else:
                stats_mercado['cvd_sesion'] += vol_usd
                stats_mercado['vol_compras'] += vol_usd

def aplicar_evento(data):
    global bids_local, asks_local, last_update_id, precio_actual
    if data['u'] <= last_update_id: return
    for p, q in data['b']:
        if float(q) == 0: bids_local.pop(float(p), None)
        else: bids_local[float(p)] = float(q)
    for p, q in data['a']:
        if float(q) == 0: asks_local.pop(float(p), None)
        else: asks_local[float(p)] = float(q)
    last_update_id = data['u']
    
    if bids_local and asks_local:
        precio_actual = (max(bids_local.keys()) + min(asks_local.keys())) / 2

def on_message_liq(ws, message):
    global stats_mercado
    if not is_running: return
    data = json.loads(message)
    if 'o' in data: 
        o = data['o']
        vol_liq = float(o['p']) * float(o['q'])
        with data_lock:
            if o['S'] == 'SELL': stats_mercado['liq_longs'] += vol_liq
            else: stats_mercado['liq_shorts'] += vol_liq

def iniciar_websocket_spot():
    while is_running:
        try:
            ws_url = f"wss://stream.binance.com:9443/stream?streams={simbolo_ws}@depth@100ms/{simbolo_ws}@aggTrade"
            ws = websocket.WebSocketApp(ws_url, on_message=on_message_spot)
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            time.sleep(5)

def iniciar_websocket_futuros_liq():
    while is_running:
        try:
            ws_url = f"wss://fstream.binance.com/ws/{simbolo_ws}@forceOrder"
            ws = websocket.WebSocketApp(ws_url, on_message=on_message_liq)
            ws.run_forever(ping_interval=30, ping_timeout=10)
        except Exception as e:
            time.sleep(5)

# =========================================================
# BUCLE PRINCIPAL (RENDERIZADO MEJORADO)
# =========================================================
def main():
    global simbolo_rest, simbolo_ws, stats_mercado, timeframes, is_running, ls_ratio, high_24h, btc_macro_trend, cache_proy
    
    cargar_configuracion()

    console.clear()
    console.print(Panel(Align.center(f"[bold cyan]🚀 RADAR QUANT INSTITUCIONAL v3.0[/]\n[italic]TradingLatino + HFT Order Flow Dashboard[/]"), border_style="cyan"))
    
    par_input = console.input("\n[bold white]>> 🪙 Moneda a analizar (Ej: BTCUSDT): [/]").strip().upper()
    if par_input: simbolo_rest = par_input; simbolo_ws = par_input.lower()
    moneda_base = simbolo_rest.replace('USDT', '').replace('BUSD', '').replace('USDC', '')

    # --- PANTALLA DE CARGA CON ANIMACIÓN ---
    threading.Thread(target=actualizar_datos_globales, daemon=True).start()
    threading.Thread(target=iniciar_websocket_spot, daemon=True).start()
    threading.Thread(target=iniciar_websocket_futuros_liq, daemon=True).start()
    threading.Thread(target=obtener_snapshot, daemon=True).start()
    
    tiempo_inicio_carga = time.time()
    
    with Status("[bold yellow]Iniciando Motores Quant y Conectando Nodos...", spinner="dots12") as status:
        while is_running:
            book_ok = snapshot_loaded
            klines_ok = all(tf in indicadores and 'ema55' in indicadores[tf] and not math.isnan(indicadores[tf]['ema55']) for tf in timeframes)
            macro_ok = high_24h > 0
            
            if time.time() - tiempo_inicio_carga > 15:
                if ls_ratio == 0.0: ls_ratio = 1.0 
                if high_24h == 0: high_24h = precio_actual if precio_actual > 0 else 1.0

            ls_ok = ls_ratio > 0.0

            k_st = "[green]✓[/]" if klines_ok else "[yellow]Descargando...[/]"
            b_st = f"[green]✓ ({len(bids_local)+len(asks_local)} Nodos)[/]" if book_ok else "[yellow]Conectando...[/]"
            m_st = "[green]✓[/]" if macro_ok else "[yellow]Obteniendo...[/]"
            ls_st = "[green]✓[/]" if ls_ok else "[yellow]Calculando...[/]"

            status.update(f"[bold cyan]Sincronización en curso[/]\nKlines: {k_st} | L/S Ratio: {ls_st}\nOrderbook: {b_st} | Macro: {m_st}")
            
            if book_ok and klines_ok and macro_ok and ls_ok:
                break
            time.sleep(0.5)
        
    time.sleep(0.5)
    start_time = time.time()

    frames_spinner = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    
    # INICIO DE RICH LIVE (SIN PARPADEO)
    with Live(refresh_per_second=4, screen=True) as live:
        while is_running:
            time.sleep(0.25)
            
            with data_lock:
                bids_snapshot = dict(bids_local)
                asks_snapshot = dict(asks_local)
                trades_snapshot = list(recent_trades_vp)
                cvd_snapshot = list(cvd_history)

            frame_actual = frames_spinner[int(time.time() * 10) % len(frames_spinner)]

            # 0. MADUREZ
            elapsed_sec = time.time() - start_time
            madurez_pct = min(100, (elapsed_sec / 180) * 100) 
            col_madurez = RED if madurez_pct < 40 else YELLOW if madurez_pct < 100 else GREEN
            txt_madurez = "INICIANDO" if madurez_pct < 40 else "CALIBRANDO" if madurez_pct < 100 else "ÓPTIMO"
            barra_madurez = dibujar_barra_madurez(madurez_pct)

            # 1. HFT Y PERFIL DE VOLUMEN
            bin_size = precio_actual * 0.002 
            b_clust, a_clust = {}, {}
            vol_bids_total = 0.0
            vol_asks_total = 0.0
            
            for p, q in bids_snapshot.items():
                if p < precio_actual and p > precio_actual * 0.8:
                    k = math.floor(p / bin_size) * bin_size; b_clust[k] = b_clust.get(k, 0) + q
                    vol_bids_total += q
            for p, q in asks_snapshot.items():
                if p > precio_actual and p < precio_actual * 1.2:
                    k = math.ceil(p / bin_size) * bin_size; a_clust[k] = a_clust.get(k, 0) + q
                    vol_asks_total += q
                    
            top_bids = sorted(b_clust.items(), key=lambda x: x[1], reverse=True)
            top_asks = sorted(a_clust.items(), key=lambda x: x[1], reverse=True)
            
            master_bid = top_bids[0] if top_bids else (0,0)
            master_ask = top_asks[0] if top_asks else (0,0)
            scalp_bid = sorted(top_bids[:5], key=lambda x: x[0], reverse=True)[0] if top_bids else (0,0)
            scalp_ask = sorted(top_asks[:5], key=lambda x: x[0])[0] if top_asks else (0,0)

            total_book_vol = vol_bids_total + vol_asks_total if (vol_bids_total + vol_asks_total) > 0 else 1
            pct_compradores = (vol_bids_total / total_book_vol) * 100

            # VWAP BANDS Y WHALE DOMINANCE
            vp_bins = {}
            vwap_actual = precio_actual
            vwap_std = 0.0
            pct_ballenas = 0.0
            pct_minorista = 0.0
            
            if len(trades_snapshot) > 0:
                vp_step = precio_actual * 0.002 
                sum_pv = 0.0
                sum_v = 0.0
                vol_ballenas = 0.0
                vol_minorista = 0.0
                
                for tp_price, tv_vol, _ in trades_snapshot:
                    b = round(tp_price / vp_step) * vp_step
                    vp_bins[b] = vp_bins.get(b, 0) + tv_vol
                    sum_pv += (tp_price * tv_vol)
                    sum_v += tv_vol
                    
                    if tv_vol >= 20000: vol_ballenas += tv_vol
                    elif tv_vol < 1000: vol_minorista += tv_vol
                    
                poc_price = max(vp_bins, key=vp_bins.get) if vp_bins else precio_actual
                if sum_v > 0:
                    vwap_actual = sum_pv / sum_v
                    variance = sum((tv_vol * (tp_price - vwap_actual)**2) for tp_price, tv_vol, _ in trades_snapshot) / sum_v
                    vwap_std = math.sqrt(variance)
                    pct_ballenas = (vol_ballenas / sum_v) * 100
                    pct_minorista = (vol_minorista / sum_v) * 100
            else:
                poc_price = precio_actual

            # MAPA DE CALOR DE LIQUIDACIONES Y CALCULO DE VOLUMEN
            liq_short_100x = poc_price * 1.01 
            liq_short_50x = poc_price * 1.02  
            liq_short_25x = poc_price * 1.04  
            liq_long_100x = poc_price * 0.99
            liq_long_50x = poc_price * 0.98
            liq_long_25x = poc_price * 0.96

            # Calcular volumen real del Order Book cerca de las zonas de liquidación (rango del 0.4%)
            def get_vol_near(price, book):
                return sum(q for p, q in book.items() if abs(p - price) / price <= 0.004)

            v_s_100x = get_vol_near(liq_short_100x, asks_snapshot)
            v_s_50x = get_vol_near(liq_short_50x, asks_snapshot)
            v_s_25x = get_vol_near(liq_short_25x, asks_snapshot)
            
            v_l_100x = get_vol_near(liq_long_100x, bids_snapshot)
            v_l_50x = get_vol_near(liq_long_50x, bids_snapshot)
            v_l_25x = get_vol_near(liq_long_25x, bids_snapshot)

            # 2. DIVERGENCIAS DE CVD
            divergencia_cvd = "NEUTRA (Flujo Normal) 〰️"
            col_div = DARK_GRAY
            if len(cvd_snapshot) >= 12:
                p_ant = cvd_snapshot[0]['precio']
                c_ant = cvd_snapshot[0]['cvd']
                p_act = cvd_snapshot[-1]['precio']
                c_act = cvd_snapshot[-1]['cvd']
                
                if p_act < p_ant * 0.999 and c_act > c_ant:
                    divergencia_cvd = "ABSORCIÓN ALCISTA (Ballenas Comprando) 🚀"
                    col_div = GREEN
                elif p_act > p_ant * 1.001 and c_act < c_ant:
                    divergencia_cvd = "DISTRIBUCIÓN BAJISTA (Ballenas Vendiendo) ☄️"
                    col_div = RED

            estado_tape = f"{RED}EXTREMA ⚡{RESET}" if tape_speed > 30 else f"{YELLOW}ALTA 🔥{RESET}" if tape_speed > 10 else f"{GREEN}NORMAL 🌊{RESET}"

            # 3. TRADINGLATINO MULTITEMPORAL
            ind_1d, ind_4h, ind_1h = indicadores['1d'], indicadores['4h'], indicadores['1h']

            tend_1d = "ALCISTA" if ind_1d['ema10'] > ind_1d['ema55'] and precio_actual > ind_1d['ema55'] else "BAJISTA" if ind_1d['ema10'] < ind_1d['ema55'] and precio_actual < ind_1d['ema55'] else "RANGO"
            v_1d_icon = formatear_valle(ind_1d['valle_color'], ind_1d['valle'])
            
            tend_4h = "ALCISTA" if ind_4h['ema10'] > ind_4h['ema55'] and precio_actual > ind_4h['ema55'] else "BAJISTA" if ind_4h['ema10'] < ind_4h['ema55'] and precio_actual < ind_4h['ema55'] else "RANGO"
            v_4h_icon = formatear_valle(ind_4h['valle_color'], ind_4h['valle'])
            dist_4h = abs(precio_actual - ind_4h['ema55']) / ind_4h['ema55'] * 100
            
            sqz_state_4h = f"{RED}[COMPRESIÓN]{RESET}" if ind_4h.get('sqz_on', False) else f"{GREEN}[EXPANSIÓN]{RESET}"
            
            tend_1h = "ALCISTA" if ind_1h['ema10'] > ind_1h['ema55'] and precio_actual > ind_1h['ema55'] else "BAJISTA" if ind_1h['ema10'] < ind_1h['ema55'] and precio_actual < ind_1h['ema55'] else "RANGO"
            v_1h_icon = formatear_valle(ind_1h['valle_color'], ind_1h['valle'])
            dist_1h = abs(precio_actual - ind_1h['ema55']) / ind_1h['ema55'] * 100
            
            sqz_state_1h = f"{RED}[COMPRESIÓN]{RESET}" if ind_1h.get('sqz_on', False) else f"{GREEN}[EXPANSIÓN]{RESET}"

            # 4. CEREBRO OPERATIVO Y SCORING DE CONFLUENCIA
            dir_1h_calc = "LONG 🚀" if ind_1h['valle'] < 0 else "SHORT ☄️"
            col_d_1h = GREEN if "LONG" in dir_1h_calc else RED
            tend_str_1h = "A Favor (4H)" if ("LONG" in dir_1h_calc and "ALCISTA" in tend_4h) or ("SHORT" in dir_1h_calc and "BAJISTA" in tend_4h) else "Contra (4H)"
            
            # Explicación Lógica Scalp 1H
            if "LONG" in dir_1h_calc:
                logica_1h = f"Oscilador direccional en Valle Inferior (Rojo) perdiendo fuerza bajista. Se busca un [bold green]impulso alcista[/] hacia la media móvil."
            else:
                logica_1h = f"Oscilador direccional en Valle Superior (Verde) perdiendo fuerza alcista. Se busca un [bold red]retroceso bajista[/] hacia la media móvil."

            # --- DETECCIÓN DE LIMITES DEL RANGO ---
            rango_alto = ind_4h['hh_20']
            rango_bajo = ind_4h['ll_20']
            
            escudo_usd_scalp = 0
            if "LONG" in dir_1h_calc:
                candidatos_s = [p for p in [poc_price, vwap_actual, scalp_bid[0]] if p < precio_actual]
                entrada_scalp = max(candidatos_s) if candidatos_s else precio_actual
                sl_por_muro = scalp_bid[0] * 0.998
                sl_por_atr = entrada_scalp - (ind_1h['atr'] * 1.5)
                sl_scalp = min(sl_por_muro, sl_por_atr) 
                if sl_scalp >= entrada_scalp: sl_scalp = entrada_scalp * 0.99
                tp_scalp = entrada_scalp + ((entrada_scalp - sl_scalp) * 1.5)
                escudo_usd_scalp = scalp_bid[1] * scalp_bid[0] if scalp_bid[0] > 0 else 0
            else:
                candidatos_r = [p for p in [poc_price, vwap_actual, scalp_ask[0]] if p > precio_actual]
                entrada_scalp = min(candidatos_r) if candidatos_r else precio_actual
                sl_por_muro = scalp_ask[0] * 1.002
                sl_por_atr = entrada_scalp + (ind_1h['atr'] * 1.5)
                sl_scalp = max(sl_por_muro, sl_por_atr) 
                if sl_scalp <= entrada_scalp: sl_scalp = entrada_scalp * 1.01
                tp_scalp = entrada_scalp - ((sl_scalp - entrada_scalp) * 1.5)
                escudo_usd_scalp = scalp_ask[1] * scalp_ask[0] if scalp_ask[0] > 0 else 0

            if dir_1h_calc != cache_proy['1h']['dir'] or cache_proy['1h']['entrada'] == 0 or abs(entrada_scalp - cache_proy['1h']['entrada']) / entrada_scalp > 0.002:
                cache_proy['1h'] = {'dir': dir_1h_calc, 'entrada': entrada_scalp, 'sl': sl_scalp, 'tp': tp_scalp}
            
            e_s_show = cache_proy['1h']['entrada']
            sl_s_show = cache_proy['1h']['sl']
            tp_s_show = cache_proy['1h']['tp']
            dist_sl_pct_1h = abs(e_s_show - sl_s_show) / e_s_show if e_s_show > 0 else 0
            dist_tp_pct_1h = abs(tp_s_show - e_s_show) / e_s_show if e_s_show > 0 else 0

            score_scalp = 0
            if "A Favor" in tend_str_1h: score_scalp += 20
            if dist_sl_pct_1h < 0.015: score_scalp += 20
            if "LONG" in dir_1h_calc and ("ABSORCIÓN" in divergencia_cvd or "Normal" in divergencia_cvd): score_scalp += 20
            if "SHORT" in dir_1h_calc and ("DISTRIBUCIÓN" in divergencia_cvd or "Normal" in divergencia_cvd): score_scalp += 20
            if 40 <= ind_1h['rsi'] <= 60: score_scalp += 20
            if vwap_std > 0:
                if "LONG" in dir_1h_calc and e_s_show > (vwap_actual + vwap_std): score_scalp -= 25
                if "SHORT" in dir_1h_calc and e_s_show < (vwap_actual - vwap_std): score_scalp -= 25
            
            col_score_sc = GREEN if score_scalp >= 75 else YELLOW if score_scalp >= 50 else RED

            signal_scalp = f"{DARK_GRAY}⏳ ESPERAR PATRÓN / SIN FUERZA{RESET}"
            if dist_1h < 1.5 and (ind_1h['adx_slope'] < 0 or ind_1h['adx'] < 23):
                if "LONG" in dir_1h_calc and "ROJO OSCURO" in ind_1h['valle_color']: 
                    if ind_1h['rsi'] >= 65: signal_scalp = f"{YELLOW}🚫 BLOQUEADO: RSI Sobrecomprado ({ind_1h['rsi']:.1f}){RESET}"
                    elif ls_ratio > 2.5: signal_scalp = f"{RED}🚫 BLOQUEADO: Minoristas muy LONG ({ls_ratio:.2f}){RESET}"
                    elif simbolo_rest != "BTCUSDT" and btc_macro_trend == "BAJISTA": signal_scalp = f"{RED}🚫 BLOQUEADO: BTC Trend Bajista{RESET}"
                    elif "DISTRIBUCIÓN" in divergencia_cvd: signal_scalp = f"{RED}🚫 BLOQUEADO: Distribución Detectada{RESET}"
                    else: signal_scalp = f"{GREEN}{BOLD}✅ GATILLO LONG CONFIRMADO{RESET}"
                elif "SHORT" in dir_1h_calc and "VERDE OSCURO" in ind_1h['valle_color']: 
                    if ind_1h['rsi'] <= 35: signal_scalp = f"{YELLOW}🚫 BLOQUEADO: RSI Sobrevendido ({ind_1h['rsi']:.1f}){RESET}"
                    elif ls_ratio < 0.6: signal_scalp = f"{RED}🚫 BLOQUEADO: Minoristas muy SHORT ({ls_ratio:.2f}){RESET}"
                    elif simbolo_rest != "BTCUSDT" and btc_macro_trend == "ALCISTA": signal_scalp = f"{RED}🚫 BLOQUEADO: BTC Trend Alcista{RESET}"
                    elif "ABSORCIÓN" in divergencia_cvd: signal_scalp = f"{RED}🚫 BLOQUEADO: Absorción Detectada{RESET}"
                    else: signal_scalp = f"{RED}{BOLD}✅ GATILLO SHORT CONFIRMADO{RESET}"

            # --- SWING (4H) ---
            dir_4h_calc = "LONG 🚀" if ind_4h['valle'] < 0 else "SHORT ☄️"
            col_d_4h = GREEN if "LONG" in dir_4h_calc else RED
            tend_str_4h = "A Favor (Diario)" if ("LONG" in dir_4h_calc and "ALCISTA" in tend_1d) or ("SHORT" in dir_4h_calc and "BAJISTA" in tend_1d) else "Contra (Diario)"
            
            # Explicación Lógica Swing 4H
            if "LONG" in dir_4h_calc:
                logica_4h = f"Oscilador direccional en Valle Inferior (Rojo) perdiendo fuerza bajista. Se busca un [bold green]impulso alcista[/] hacia la media móvil."
            else:
                logica_4h = f"Oscilador direccional en Valle Superior (Verde) perdiendo fuerza alcista. Se busca un [bold red]retroceso bajista[/] hacia la media móvil."

            escudo_usd_swing = 0
            if "LONG" in dir_4h_calc:
                candidatos_s_m = [p for p in [poc_price, vwap_actual, master_bid[0]] if p < precio_actual]
                entrada_swing = max(candidatos_s_m) if candidatos_s_m else precio_actual
                sl_por_muro = master_bid[0] * 0.995
                sl_por_atr = entrada_swing - (ind_4h['atr'] * 2.0)
                sl_swing = min(sl_por_muro, sl_por_atr)
                if sl_swing >= entrada_swing: sl_swing = entrada_swing * 0.98
                tp_swing = entrada_swing + ((entrada_swing - sl_swing) * 2.0)
                escudo_usd_swing = master_bid[1] * master_bid[0] if master_bid[0] > 0 else 0
            else:
                candidatos_r_m = [p for p in [poc_price, vwap_actual, master_ask[0]] if p > precio_actual]
                entrada_swing = min(candidatos_r_m) if candidatos_r_m else precio_actual
                sl_por_muro = master_ask[0] * 1.005
                sl_por_atr = entrada_swing + (ind_4h['atr'] * 2.0)
                sl_swing = max(sl_por_muro, sl_por_atr)
                if sl_swing <= entrada_swing: sl_swing = entrada_swing * 1.02
                tp_swing = entrada_swing - ((sl_swing - entrada_swing) * 2.0)
                escudo_usd_swing = master_ask[1] * master_ask[0] if master_ask[0] > 0 else 0

            if dir_4h_calc != cache_proy['4h']['dir'] or cache_proy['4h']['entrada'] == 0 or abs(entrada_swing - cache_proy['4h']['entrada']) / entrada_swing > 0.002:
                cache_proy['4h'] = {'dir': dir_4h_calc, 'entrada': entrada_swing, 'sl': sl_swing, 'tp': tp_swing}
            
            e_sw_show = cache_proy['4h']['entrada']
            sl_sw_show = cache_proy['4h']['sl']
            tp_sw_show = cache_proy['4h']['tp']
            dist_sl_pct_4h = abs(e_sw_show - sl_sw_show) / e_sw_show if e_sw_show > 0 else 0
            dist_tp_pct_4h = abs(tp_sw_show - e_sw_show) / e_sw_show if e_sw_show > 0 else 0

            score_swing = 0
            if "A Favor" in tend_str_4h: score_swing += 20
            if dist_sl_pct_4h < 0.03: score_swing += 20
            if "LONG" in dir_4h_calc and ("ABSORCIÓN" in divergencia_cvd or "Normal" in divergencia_cvd): score_swing += 20
            if "SHORT" in dir_4h_calc and ("DISTRIBUCIÓN" in divergencia_cvd or "Normal" in divergencia_cvd): score_swing += 20
            if 40 <= ind_4h['rsi'] <= 60: score_swing += 20
            if vwap_std > 0:
                if "LONG" in dir_4h_calc and e_sw_show > (vwap_actual + vwap_std): score_swing -= 25 
                if "SHORT" in dir_4h_calc and e_sw_show < (vwap_actual - vwap_std): score_swing -= 25 

            col_score_sw = GREEN if score_swing >= 75 else YELLOW if score_swing >= 50 else RED

            signal_swing = f"{DARK_GRAY}⏳ ESPERAR PATRÓN / SIN FUERZA{RESET}"
            if dist_4h < 3.0 and (ind_4h['adx_slope'] < 0 or ind_4h['adx'] < 23):
                if "LONG" in dir_4h_calc and "ROJO OSCURO" in ind_4h['valle_color']: 
                    if ind_4h['rsi'] >= 70: signal_swing = f"{YELLOW}🚫 BLOQUEADO: RSI Sobrecomprado ({ind_4h['rsi']:.1f}){RESET}"
                    elif ls_ratio > 2.5: signal_swing = f"{RED}🚫 BLOQUEADO: Minoristas muy LONG ({ls_ratio:.2f}){RESET}"
                    elif simbolo_rest != "BTCUSDT" and btc_macro_trend == "BAJISTA": signal_swing = f"{RED}🚫 BLOQUEADO: BTC Trend Bajista{RESET}"
                    elif "DISTRIBUCIÓN" in divergencia_cvd: signal_swing = f"{RED}🚫 BLOQUEADO: Distribución Detectada{RESET}"
                    else: signal_swing = f"{GREEN}{BOLD}✅ GATILLO LONG CONFIRMADO{RESET}"
                elif "SHORT" in dir_4h_calc and "VERDE OSCURO" in ind_4h['valle_color']: 
                    if ind_4h['rsi'] <= 30: signal_swing = f"{YELLOW}🚫 BLOQUEADO: RSI Sobrevendido ({ind_4h['rsi']:.1f}){RESET}"
                    elif ls_ratio < 0.6: signal_swing = f"{RED}🚫 BLOQUEADO: Minoristas muy SHORT ({ls_ratio:.2f}){RESET}"
                    elif simbolo_rest != "BTCUSDT" and btc_macro_trend == "ALCISTA": signal_swing = f"{RED}🚫 BLOQUEADO: BTC Trend Alcista{RESET}"
                    elif "ABSORCIÓN" in divergencia_cvd: signal_swing = f"{RED}🚫 BLOQUEADO: Absorción Detectada{RESET}"
                    else: signal_swing = f"{RED}{BOLD}✅ GATILLO SHORT CONFIRMADO{RESET}"

            # FILTRO DE MADUREZ
            if madurez_pct < 100:
                if "CONFIRMADO" in signal_scalp: signal_scalp = f"{col_madurez}🕒 PRE-SEÑAL (Estabilizando al {madurez_pct:.0f}%){RESET}"
                if "CONFIRMADO" in signal_swing: signal_swing = f"{col_madurez}🕒 PRE-SEÑAL (Estabilizando al {madurez_pct:.0f}%){RESET}"

            # ALERTAS Y CSV
            if madurez_pct == 100 and ("CONFIRMADO" in signal_scalp or "CONFIRMADO" in signal_swing):
                emitir_sonido()
                msg_tg = (
                    f"🚨 <b>[ALERTA DE TRADING] {simbolo_rest}</b> 🚨\n\n"
                    f"<b>SCALPING (1H):</b>\nDir: {dir_1h_calc}\nEntrada: ${e_s_show:,.2f}\nTP: ${tp_s_show:,.2f}\nSL: ${sl_s_show:,.2f}\nScore: {score_scalp}%\n\n"
                    f"<b>SWING (4H):</b>\nDir: {dir_4h_calc}\nEntrada: ${e_sw_show:,.2f}\nTP: ${tp_sw_show:,.2f}\nSL: ${sl_sw_show:,.2f}\nScore: {score_swing}%\n\n"
                    f"<i>TradingLatino + Order Flow</i>"
                )
                enviar_telegram(msg_tg)
                
                fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                if "CONFIRMADO" in signal_scalp:
                    datos_scalp = [fecha_actual, simbolo_rest, "1H", dir_1h_calc, round(e_s_show, 2), round(tp_s_show, 2), round(sl_s_show, 2), tend_str_1h, round(poc_price, 2), round(vwap_actual, 2), round(ls_ratio, 2), divergencia_cvd]
                    registrar_alerta_csv(datos_scalp)
                if "CONFIRMADO" in signal_swing:
                    datos_swing = [fecha_actual, simbolo_rest, "4H", dir_4h_calc, round(e_sw_show, 2), round(tp_sw_show, 2), round(sl_sw_show, 2), tend_str_4h, round(poc_price, 2), round(vwap_actual, 2), round(ls_ratio, 2), divergencia_cvd]
                    registrar_alerta_csv(datos_swing)

            # ==================== RENDERIZADO VISUAL CON RICH TABLES (LAYOUT INSTITUCIONAL) ====================
            
            # --- HEADER ---
            header_text = f"{CYAN}{frame_actual} LIVE{RESET} | [bold white]{simbolo_rest}[/] | PRECIO: [bold yellow]${precio_actual:,.2f}[/] | POC: ${poc_price:,.2f} | VWAP: ${vwap_actual:,.2f}\n"
            header_text += f"Calibración de Algoritmo: [{barra_madurez}] {col_madurez}{madurez_pct:.0f}% ({txt_madurez}){RESET}"
            panel_header = Panel(Align.center(Text.from_markup(header_text)), border_style="cyan", padding=(1, 0))

            # --- TABLA 1: ESTRATEGIA TRADINGLATINO ---
            table_tl = Table(show_header=True, header_style="bold magenta", expand=True, border_style="dim")
            table_tl.add_column("TF", justify="center", width=4)
            table_tl.add_column("Tendencia", justify="left")
            table_tl.add_column("Valle Direccional", justify="left")
            table_tl.add_column("Fuerza & Squeeze", justify="left")

            table_tl.add_row(
                "[bold]1D[/]", formatear_tendencia(tend_1d), v_1d_icon, 
                f"RSI: {WHITE}{ind_1d['rsi']:.0f}{RESET} | ADX: {WHITE}{ind_1d['adx']:.0f}{RESET}"
            )
            table_tl.add_row(
                "[bold]4H[/]", formatear_tendencia(tend_4h), v_4h_icon, 
                f"{sqz_state_4h} | RSI: {WHITE}{ind_4h['rsi']:.0f}{RESET} | ADX: {WHITE}{ind_4h['adx']:.0f}{RESET}"
            )
            table_tl.add_row(
                "[bold]1H[/]", formatear_tendencia(tend_1h), v_1h_icon, 
                f"{sqz_state_1h} | RSI: {WHITE}{ind_1h['rsi']:.0f}{RESET} | ADX: {WHITE}{ind_1h['adx']:.0f}{RESET}"
            )
            panel_tl = Panel(table_tl, title="[1] MATRIZ TRADINGLATINO (1D - 4H - 1H)", border_style="magenta", title_align="left")

            # --- TABLA 2: CEREBRO OPERATIVO ---
            table_op = Table(show_header=False, expand=True, box=None)
            table_op.add_column("Info", ratio=1)
            
            # Sub-tabla Scalp
            t_scalp = Table(expand=True, border_style="cyan", padding=(0, 1))
            t_scalp.add_column("📊 SCALPING (1H)", justify="center", style="bold cyan")
            t_scalp.add_column("ENTRADA LIMIT", justify="center")
            t_scalp.add_column("STOP LOSS", justify="center")
            t_scalp.add_column("TAKE PROFIT", justify="center")
            t_scalp.add_row(
                f"{col_d_1h}{dir_1h_calc.replace('🚀', '').replace('☄️', '').strip()}{RESET} ({tend_str_1h})",
                f"{YELLOW}${e_s_show:,.2f}{RESET}",
                f"{RED}${sl_s_show:,.2f}{RESET} (-{dist_sl_pct_1h*100:.2f}%)",
                f"{GREEN}${tp_s_show:,.2f}{RESET} (+{dist_tp_pct_1h*100:.2f}%)"
            )
            
            # Sub-tabla Swing
            t_swing = Table(expand=True, border_style="cyan", padding=(0, 1))
            t_swing.add_column("📈 SWING (4H)", justify="center", style="bold cyan")
            t_swing.add_column("ENTRADA LIMIT", justify="center")
            t_swing.add_column("STOP LOSS", justify="center")
            t_swing.add_column("TAKE PROFIT", justify="center")
            t_swing.add_row(
                f"{col_d_4h}{dir_4h_calc.replace('🚀', '').replace('☄️', '').strip()}{RESET} ({tend_str_4h})",
                f"{YELLOW}${e_sw_show:,.2f}{RESET}",
                f"{RED}${sl_sw_show:,.2f}{RESET} (-{dist_sl_pct_4h*100:.2f}%)",
                f"{GREEN}${tp_sw_show:,.2f}{RESET} (+{dist_tp_pct_4h*100:.2f}%)"
            )

            str_op_extra = (
                f"🧠 [bold]Lógica Operativa (1H):[/] {logica_1h}\n"
                f"🎯 [bold]Confluencia Scalp:[/] {col_score_sc}{score_scalp}%{RESET} | Veredicto: {signal_scalp}\n"
                f"🛡️ [bold]Muro Scalp:[/] ${escudo_usd_scalp:,.0f} protegiendo SL.\n\n"
                f"🧠 [bold]Lógica Operativa (4H):[/] {logica_4h}\n"
                f"🎯 [bold]Confluencia Swing:[/] {col_score_sw}{score_swing}%{RESET} | Veredicto: {signal_swing}\n"
                f"🛡️ [bold]Muro Swing:[/] ${escudo_usd_swing:,.0f} protegiendo SL."
            )

            table_op.add_row(t_scalp)
            table_op.add_row(t_swing)
            table_op.add_row(Panel(Text.from_markup(str_op_extra), border_style="dim"))
            
            panel_op = Panel(table_op, title="[2] PROYECCIONES Y SEÑALES ALGORÍTMICAS", border_style="cyan", title_align="left")

            # --- TABLA 3: ORDER FLOW & HFT ---
            table_of = Table(show_header=False, expand=True, box=None)
            table_of.add_column("Col1")
            
            cvd = stats_mercado['cvd_sesion']
            c_fund = RED if funding_rate > 0.01 else GREEN if funding_rate < -0.01 else YELLOW
            vwap_up = vwap_actual + (vwap_std * 2)
            vwap_dn = vwap_actual - (vwap_std * 2)
            col_btc = GREEN if btc_macro_trend == "ALCISTA" else RED if btc_macro_trend == "BAJISTA" else YELLOW
            col_ls = RED if ls_ratio > 2.0 else GREEN if ls_ratio < 1.0 else YELLOW
            
            str_barra = dibujar_barra(pct_compradores)
            
            macro_text = (
                f"🐋 [bold]Dominancia Cintas:[/] {GREEN}Whales {pct_ballenas:.1f}%{RESET} vs {RED}Retail {pct_minorista:.1f}%{RESET}\n"
                f"👑 [bold]Tendencia Rey (BTC):[/] {col_btc}{btc_macro_trend}{RESET} | Open Int: {WHITE}{open_interest:,.0f}{RESET}\n"
                f"⚖️ [bold]Retail L/S Ratio:[/] {col_ls}{ls_ratio:.2f}{RESET} | Funding: {c_fund}{funding_rate:+.4f}%{RESET}\n"
                f"📊 [bold]Bandas VWAP (±2σ):[/] Alta: {RED}${vwap_up:,.0f}{RESET} / Baja: {GREEN}${vwap_dn:,.0f}{RESET}\n\n"
                f"📈 [bold]Divergencia CVD:[/] {col_div}{divergencia_cvd}{RESET}\n"
                f"⚡ [bold]Velocidad Tape:[/] {estado_tape} ({tape_speed:.1f} trades/s)"
            )
            
            hft_text = (
                f"📚 [bold]Imbalance Libro:[/] [{str_barra}]\n"
                f"   {GREEN}Toros {pct_compradores:.0f}%{RESET} vs {RED}Osos {100-pct_compradores:.0f}%{RESET}\n\n"
                f"🧱 [bold]Muro Resistencia:[/] {DARK_RED}${master_ask[0]:,.0f}{RESET} (+{(master_ask[0]-precio_actual)/precio_actual*100:.2f}%)\n"
                f"   Volumen: {master_ask[1]:,.2f} {moneda_base}\n"
                f"🛡️ [bold]Muro Soporte:[/] {DARK_GREEN}${master_bid[0]:,.0f}{RESET} ({(master_bid[0]-precio_actual)/precio_actual*100:.2f}%)\n"
                f"   Volumen: {master_bid[1]:,.2f} {moneda_base}"
            )
            
            liq_text = (
                f"[bold red]💥 Liquidaciones Arriba (Shorts)[/]\n"
                f"100x -> {formato_liq(liq_short_100x, precio_actual, v_s_100x, moneda_base)}\n"
                f" 50x -> {formato_liq(liq_short_50x, precio_actual, v_s_50x, moneda_base)}\n"
                f" 25x -> {formato_liq(liq_short_25x, precio_actual, v_s_25x, moneda_base)}\n\n"
                f"[bold green]💥 Liquidaciones Abajo (Longs)[/]\n"
                f"100x -> {formato_liq(liq_long_100x, precio_actual, v_l_100x, moneda_base)}\n"
                f" 50x -> {formato_liq(liq_long_50x, precio_actual, v_l_50x, moneda_base)}\n"
                f" 25x -> {formato_liq(liq_long_25x, precio_actual, v_l_25x, moneda_base)}"
            )

            table_of.add_row(Panel(Text.from_markup(macro_text), title="🌐 MACRO & ORDER FLOW", border_style="dim"))
            table_of.add_row(Panel(Text.from_markup(hft_text), title="🧱 MICROESTRUCTURA HFT", border_style="dim"))
            table_of.add_row(Panel(Text.from_markup(liq_text), title="🧲 MAPA DE LIQUIDACIONES", border_style="dim"))

            panel_right = Panel(table_of, title="[3] ANÁLISIS DE FLUJO INSTITUCIONAL", border_style="magenta", title_align="left")

            # --- SÍNTESIS DE MERCADO (TEXTO SINTETIZADO) ---
            txt_macro = f"Bitcoin dicta un sesgo [bold]{btc_macro_trend}[/]. "
            if ls_ratio > 2.5: txt_macro += f"Exceso de minoristas apostando al alza (L/S {ls_ratio:.1f}), alto riesgo de liquidaciones en cascada hacia [bold red]abajo[/]."
            elif ls_ratio < 0.8: txt_macro += f"Exceso de minoristas apostando a la baja (L/S {ls_ratio:.1f}), combustible para un probable [bold green]Short Squeeze[/]."
            else: txt_macro += f"Sentimiento minorista equilibrado (L/S {ls_ratio:.1f})."

            f_1d = "fuerte" if ind_1d['adx'] > 23 else "débil"
            txt_largo = f"Estructura [bold]{tend_1d}[/] {f_1d} (ADX: {ind_1d['adx']:.0f}). "
            if "ALCISTA" in tend_1d: txt_largo += "El panorama general favorece fuertemente las posiciones de [bold green]COMPRA[/] en soportes clave."
            elif "BAJISTA" in tend_1d: txt_largo += "El panorama general advierte cautela; priorizar posiciones [bold red]CORTAS[/] en los rebotes a medias móviles."
            else: txt_largo += "Fase de consolidación mayor; operar exclusivamente los [bold yellow]extremos del rango[/]."

            # Evaluacion del rango vs tendencia alineada
            if dir_1h_calc != dir_4h_calc:
                txt_medio = f"{YELLOW}⚠️ MERCADO EN RANGO / CONTRADICCIÓN{RESET} (1H apunta {dir_1h_calc.replace('🚀','').replace('☄️','').strip()} vs 4H apunta {dir_4h_calc.replace('🚀','').replace('☄️','').strip()}).\n"
                txt_medio += f"Límites Macro (4H): Techo del Rango {RED}${rango_alto:,.2f}{RESET} | Piso del Rango {GREEN}${rango_bajo:,.2f}{RESET}. "
                txt_medio += f"Es común operar rebotes dentro de los límites hasta que uno de los marcos rompa el rango con volumen."
            else:
                txt_medio = f"{GREEN}🔥 MERCADO ALINEADO TENDENCIALMENTE{RESET} (Fuerza {dir_1h_calc.replace('🚀','').replace('☄️','').strip()} confirmada en 1H y 4H).\n"
                txt_medio += f"Mayor probabilidad de éxito y ruptura fuerte. Priorizar posiciones a favor de esta dirección."
                
            if ind_4h.get('sqz_on', False): txt_medio += " [bold red]¡Atención! Compresión extrema de volatilidad detectada en 4H.[/]"

            txt_corto = f"Microestructura orientada al [bold]{dir_1h_calc.replace('🚀', '').replace('☄️', '').strip()}[/]. "
            if "ABSORCIÓN" in divergencia_cvd: txt_corto += "[bold green]Se detectan ballenas ABSORBIENDO ventas agresivas con órdenes pasivas (Soporte Institucional).[/]"
            elif "DISTRIBUCIÓN" in divergencia_cvd: txt_corto += "[bold red]Se detectan ballenas DISTRIBUYENDO en la parte alta contra compras retail (Resistencia Institucional).[/]"
            else: txt_corto += f"Presión del Orderbook: {pct_compradores:.0f}% alcista. Flujo de capital estándar."

            # -- RECOMENDACIÓN Y PROYECCIÓN MÁS PROBABLE --
            reco_txt = ""
            if "CONFIRMADO" in signal_scalp and "CONFIRMADO" in signal_swing and dir_1h_calc == dir_4h_calc:
                reco_txt = f"[bold green]ALTA PROBABILIDAD:[/bold green] Alineación temporal perfecta en {dir_1h_calc.replace('🚀','').replace('☄️','').strip()}. Ejecutar orden Limit respetando el SL propuesto."
            elif "CONFIRMADO" in signal_scalp:
                reco_txt = f"[bold yellow]SCALP ACTIVO:[/bold yellow] Gatillo direccional {dir_1h_calc.replace('🚀','').replace('☄️','').strip()} en 1H. Riesgo moderado, asegurar ganancias rápido."
            elif "CONFIRMADO" in signal_swing:
                reco_txt = f"[bold yellow]SWING ACTIVO:[/bold yellow] Gatillo direccional {dir_4h_calc.replace('🚀','').replace('☄️','').strip()} en 4H. Mayor recorrido, gestionar con paciencia."
            else:
                reco_txt = "[bold dark_gray]ESPERAR:[/bold dark_gray] Sin confirmaciones claras en este momento. Preservar capital y monitorear los muros o los extremos del rango."

            pool_arriba = max([(liq_short_100x, v_s_100x), (liq_short_50x, v_s_50x), (liq_short_25x, v_s_25x)], key=lambda x: x[1])
            pool_abajo = max([(liq_long_100x, v_l_100x), (liq_long_50x, v_l_50x), (liq_long_25x, v_l_25x)], key=lambda x: x[1])
            
            if "LONG" in dir_1h_calc:
                proy_txt = f"Barrido de liquidez superior hacia la zona de los [bold cyan]${pool_arriba[0]:,.0f}[/bold cyan] ({pool_arriba[1]:,.0f} {moneda_base} descansando)."
            else:
                proy_txt = f"Búsqueda de stops e imán de liquidaciones inferiores hacia los [bold cyan]${pool_abajo[0]:,.0f}[/bold cyan] ({pool_abajo[1]:,.0f} {moneda_base} vulnerables)."
                
            if ind_1h.get('sqz_on', False) or ind_4h.get('sqz_on', False):
                proy_txt += " [bold red]Alta probabilidad de ruptura brusca pronto.[/]"

            table_sintesis = Table(show_header=False, expand=True, box=None, padding=(0, 1))
            table_sintesis.add_column("Periodo", style="bold white", width=22)
            table_sintesis.add_column("Análisis", justify="left")
            
            table_sintesis.add_row("🌍 [bold cyan]Visión Macro[/]", txt_macro)
            table_sintesis.add_row("📅 [bold magenta]Largo Plazo (1D)[/]", txt_largo)
            table_sintesis.add_row("⏳ [bold yellow]Medio Plazo (4H)[/]", txt_medio)
            table_sintesis.add_row("⚡ [bold green]Corto Plazo (1H)[/]", txt_corto)
            table_sintesis.add_row("", "")
            table_sintesis.add_row("🎯 [bold yellow]Recomendación[/]", reco_txt)
            table_sintesis.add_row("🔮 [bold cyan]Proy. Algorítmica[/]", proy_txt)

            panel_sintesis = Panel(table_sintesis, title="[4] SÍNTESIS CONTEXTUAL DEL MERCADO", border_style="green", title_align="left")

            # --- CONSTRUCCIÓN DE LA GRILLA PRINCIPAL ---
            main_grid = Table.grid(expand=True, padding=(0, 1))
            main_grid.add_column(ratio=6) # Columna Izquierda (Estrategia)
            main_grid.add_column(ratio=4) # Columna Derecha (Order Flow)
            
            left_group = Group(panel_tl, panel_op)
            main_grid.add_row(left_group, panel_right)

            # --- RENDER FINAL ---
            footer = Text.from_markup(f"{DARK_GRAY}Presiona Ctrl+C para salir | Sonidos: {'ON 🔊' if ALERTAS_SONORAS else 'OFF 🔇'} | Auto-Guardado CSV: Activo{RESET}", justify="center")
            
            pantalla = Group(panel_header, main_grid, panel_sintesis, footer)
            live.update(pantalla)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        is_running = False 
        logging.info("Apagado seguro iniciado por el usuario.")
        console.print(f"\n{RED}Saliendo del Radar... ¡Éxitos en tu trading! 🚀{RESET}")
