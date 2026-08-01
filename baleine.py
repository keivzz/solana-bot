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

# ---- Liste des baleines (tu peux en ajouter d'autres) ----
WHALE_ADDRESSES = [
    "FneHsyttC7TuJrp1br112nf5NsTNKTuQqhRi6bnXj317",  # Baleine 1 (l'originale)
    "GcV9T51UcwskWnqqM67FWJ9SMHKCPS4hMUKqEVEh3CjU",  # Baleine 2 (la nouvelle)
]

# ---- Ton wallet Phantom ----
VOTRE_ADRESSE_PHANTOM = "BF9xJASwDX5K3pRpPmFoDHe6RUmtTrMSBZXwHzwqtipt"
CLE_PRIVEE_PHANTOM = os.getenv("CLE_PRIVEE_PHANTOM")
if CLE_PRIVEE_PHANTOM is None:
    print("❌ ERREUR : CLE_PRIVEE_PHANTOM non définie.")
    exit(1)

# ---- Montants ----
MONTANT_USDC = 20            # Montant principal par trade
ARBITRAGE_MONTANT = 10       # Montant pour tenter l'arbitrage
ARBITRAGE_SEUIL = 0.012      # 1.2% d'écart minimum pour arbitrer

# ---- Suivi des tokens achetés ----
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
# 3. FONCTIONS DE SWAP (Solana)
# ==========================================

def swap_solana(token_out, amount_usdt, is_buy=True):
    try:
        input_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v" if is_buy else token_out
        output_mint = token_out if is_buy else "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={int(amount_usdt * 1_000_000)}&slippageBps=500"
        quote = requests.get(quote_url).json()
        if "error" in quote:
            print(f"❌ Erreur quote: {quote['error']}")
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
# 4. ARBITRAGE (exploite les écarts de prix entre DEX)
# ==========================================

def arbitrage_dex(token_address, amount_usdt):
    try:
        print(f"🔄 Tentative d'arbitrage sur {token_address[:12]}...")
        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint=EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v&outputMint={token_address}&amount={int(amount_usdt * 1_000_000)}&slippageBps=100"
        quote = requests.get(quote_url).json()

        if 'routePlan' not in quote:
            return

        dex_prices = {}
        for route in quote['routePlan']:
            dex_id = route['swapInfo']['ammKey']
            price = route['swapInfo']['price']
            dex_prices[dex_id] = float(price)

        if len(dex_prices) < 2:
            print("⚠️ Pas assez de DEX pour l'arbitrage.")
            return

        min_price = min(dex_prices.values())
        max_price = max(dex_prices.values())
        spread = (max_price - min_price) / min_price

        if spread > ARBITRAGE_SEUIL:
            print(f"💰 Spread {spread:.2%} détecté ! Gain potentiel : {amount_usdt * spread:.2f} USDC")
            # Pour un arbitrage réel, il faudrait deux transactions signées.
            # Ici, on le signale pour que tu saches qu'une opportunité existe.
        else:
            print(f"⏳ Spread {spread:.2%} < seuil ({ARBITRAGE_SEUIL*100:.1f}%), pas d'arbitrage.")

    except Exception as e:
        print(f"⚠️ Erreur arbitrage: {e}")

# ==========================================
# 5. SURVEILLANCE DES BALEINES
# ==========================================

def check_whale(whale_address):
    global portefeuille_global
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{whale_address}"
        data = requests.get(url).json()

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
            # Lance l'arbitrage juste après l'achat
            arbitrage_dex(token, ARBITRAGE_MONTANT)

        elif side == 'SELL' and token in portefeuille_global:
            print(f"🐋 {whale_address[:8]}... VEND {token[:12]} (Vol: {volume:.0f})")
            swap_solana(token, MONTANT_USDC, is_buy=False)
            del portefeuille_global[token]

    except Exception as e:
        print(f"⚠️ Erreur scan {whale_address[:8]}: {e}")

# ==========================================
# 6. BOUCLE PRINCIPALE
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
