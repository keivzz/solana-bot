import os
import time
import json
import requests
import base58
import threading
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler
from nacl.signing import SigningKey

# Force l'affichage des logs en temps réel (pour Render)
sys.stdout.reconfigure(line_buffering=True)

# ==========================================
# 1. CONFIGURATION
# ==========================================

WHALE_ADDRESSES = [
    "FneHsyttC7TuJrp1br112nf5NsTNKTuQqhRi6bnXj317",
    "GcV9T51UcwskWnqqM67FWJ9SMHKCPS4hMUKqEVEh3CjU",
]

VOTRE_ADRESSE_PHANTOM = "BF9xJASwDX5K3pRpPmFoDHe6RUmtTrMSBZXwHzwqtipt"
CLE_PRIVEE_PHANTOM = os.getenv("CLE_PRIVEE_PHANTOM")
if CLE_PRIVEE_PHANTOM is None:
    print("❌ ERREUR : CLE_PRIVEE_PHANTOM non définie.")
    exit(1)

MONTANT_USDC = 20
ARBITRAGE_MONTANT = 10
ARBITRAGE_SEUIL = 0.012

portefeuille_global = {}

# ==========================================
# 2. SERVEUR FACTICE (pour Render)
# ==========================================

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_dummy_server():
    port = int(os.getenv('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    server.serve_forever()

threading.Thread(target=run_dummy_server, daemon=True).start()

# ==========================================
# 3. PING AUTOMATIQUE (anti-veille Render)
# ==========================================

def self_ping():
    """Envoie une requête à son propre service toutes les 5 minutes."""
    url = "https://solana-bot-4jom.onrender.com"  # à ajuster si ton URL change
    while True:
        try:
            requests.get(url, timeout=5)
            print("💓 Ping envoyé pour éviter la veille.")
        except:
            pass
        time.sleep(300)  # 5 minutes

threading.Thread(target=self_ping, daemon=True).start()

# ==========================================
# 4. FONCTION DE REQUÊTE ROBUSTE
# ==========================================

def requete_robuste(url, max_retries=3, delay=10):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    for i in range(max_retries):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                return response.json()
            else:
                print(f"⚠️ Statut HTTP {response.status_code}, tentative {i+1}/{max_retries}")
        except Exception as e:
            print(f"⚠️ Erreur requête (tentative {i+1}/{max_retries}): {e}")
        time.sleep(delay)
    return None

# ==========================================
# 5. FONCTIONS DE SWAP
# ==========================================

def swap_solana(token_out, amount_usdt, is_buy=True):
    try:
        input_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" if is_buy else token_out
        output_mint = token_out if is_buy else "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={int(amount_usdt * 1_000_000)}&slippageBps=500"
        quote = requete_robuste(quote_url)
        if quote is None or "error" in quote:
            print(f"❌ Erreur quote: {quote.get('error', 'inconnue') if quote else 'timeout'}")
            return

        swap_payload = {
            "quoteResponse": quote,
            "userPublicKey": VOTRE_ADRESSE_PHANTOM,
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True
        }
        swap_response = requests.post("https://quote-api.jup.ag/v6/swap", json=swap_payload)
        swap_data = swap_response.json()

        if 'swapTransaction' not in swap_data:
            print("❌ Données de swap invalides.")
            return

        tx_bytes = base58.b58decode(swap_data['swapTransaction'])
        private_key_bytes = base58.b58decode(CLE_PRIVEE_PHANTOM)
        signing_key = SigningKey(private_key_bytes[:32])
        signature = signing_key.sign(tx_bytes).signature
        signed_tx = tx_bytes + signature
        signed_tx_base58 = base58.b58encode(signed_tx).decode()

        rpc_payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [signed_tx_base58, {"encoding": "base58"}]
        }
        result = requests.post("https://api.mainnet-beta.solana.com", json=rpc_payload).json()

        if 'result' in result:
            print(f"✅ {'Achat' if is_buy else 'Vente'} réussi ! Sig: {result['result'][:16]}...")
        else:
            print(f"❌ Erreur RPC: {result}")

    except Exception as e:
        print(f"⚠️ Erreur swap: {e}")

# ==========================================
# 6. ARBITRAGE
# ==========================================

def arbitrage_dex(token_address, amount_usdt):
    try:
        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&outputMint={token_address}&amount={int(amount_usdt * 1_000_000)}&slippageBps=100"
        quote = requete_robuste(quote_url)
        if quote is None or 'routePlan' not in quote:
            return

        dex_prices = {}
        for route in quote['routePlan']:
            dex_id = route['swapInfo']['ammKey']
            price = route['swapInfo']['price']
            dex_prices[dex_id] = float(price)

        if len(dex_prices) < 2:
            return

        min_price = min(dex_prices.values())
        max_price = max(dex_prices.values())
        spread = (max_price - min_price) / min_price

        if spread > ARBITRAGE_SEUIL:
            print(f"💰 Spread {spread:.2%} détecté ! Gain potentiel : {amount_usdt * spread:.2f} USDC")
        else:
            print(f"⏳ Spread {spread:.2%} < seuil ({ARBITRAGE_SEUIL*100:.1f}%)")

    except Exception as e:
        print(f"⚠️ Erreur arbitrage: {e}")

# ==========================================
# 7. SURVEILLANCE DES BALEINES
# ==========================================

def check_whale(whale_address):
    global portefeuille_global
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{whale_address}"
        data = requete_robuste(url)
        if data is None:
            print(f"⏳ Baleine {whale_address[:8]}... injoignable, réessai plus tard.")
            return

        if 'trades' not in data or len(data['trades']) == 0:
            return

        trade = data['trades'][0]
        side = trade['side']
        token = trade['tokenAddress']
        volume = float(trade['volume'])

        if volume < 50:
            return

        if side == 'BUY' and token not in portefeuille_global:
            print(f"🐋 {whale_address[:8]}... ACHÈTE {token[:12]} (Vol: {volume:.0f})")
            swap_solana(token, MONTANT_USDC, is_buy=True)
            portefeuille_global[token] = True
            arbitrage_dex(token, ARBITRAGE_MONTANT)

        elif side == 'SELL' and token in portefeuille_global:
            print(f"🐋 {whale_address[:8]}... VEND {token[:12]} (Vol: {volume:.0f})")
            swap_solana(token, MONTANT_USDC, is_buy=False)
            del portefeuille_global[token]

    except Exception as e:
        print(f"⚠️ Erreur scan {whale_address[:8]}: {e}")

# ==========================================
# 8. BOUCLE PRINCIPALE
# ==========================================

if __name__ == "__main__":
    print("🚀 BOT MULTI-BALEINES + ARBITRAGE LANCÉ")
    print(f"🎯 {len(WHALE_ADDRESSES)} baleines surveillées")
    print(f"💰 Montant par trade: {MONTANT_USDC} USDC")
    print(f"🔄 Arbitrage: {ARBITRAGE_MONTANT} USDC (seuil {ARBITRAGE_SEUIL*100:.1f}%)")
    print("🔄 Vérification toutes les 15 secondes...\n")

    while True:
        for whale in WHALE_ADDRESSES:
            check_whale(whale)
        time.sleep(15)
