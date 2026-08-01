import os
import time
import json
import requests
import base58
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from nacl.signing import SigningKey

# ==========================================
# 1. CONFIGURATION (variables d'environnement)
# ==========================================

WHALE_ADDRESS = "FneHsyttC7TuJrp1br112nf5NsTNKTuQqhRi6bnXj317"
VOTRE_ADRESSE_PHANTOM = "BF9xJASwDX5K3pRpPmFoDHe6RUmtTrMSBZXwHzwqtipt"

# Clé privée lue depuis l'environnement Render
CLE_PRIVEE_PHANTOM = os.getenv("CLE_PRIVEE_PHANTOM")
if CLE_PRIVEE_PHANTOM is None:
    print("❌ ERREUR : La variable CLE_PRIVEE_PHANTOM n'est pas définie.")
    exit(1)

MONTANT_USDC = 10
portefeuille = {}

# ==========================================
# 2. SERVEUR FACTICE (pour Render)
# ==========================================

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_dummy_server():
    # Utilise le port attribué par Render (ou 10000 par défaut)
    port = int(os.getenv('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), DummyHandler)
    print(f"🌐 Serveur factice démarré sur le port {port}")
    server.serve_forever()

# Lance le serveur factice dans un thread séparé (non bloquant)
threading.Thread(target=run_dummy_server, daemon=True).start()

# ==========================================
# 3. FONCTIONS DE SWAP (Solana)
# ==========================================

def execute_swap(token_out, amount_usdt, is_buy=True):
    try:
        if is_buy:
            input_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC
            output_mint = token_out
        else:
            input_mint = token_out
            output_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC

        # 1. Obtenir la route de swap via Jupiter
        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={int(amount_usdt * 1_000_000)}&slippageBps=500"
        quote_response = requests.get(quote_url)
        quote = quote_response.json()

        if "error" in quote:
            print(f"❌ Erreur de route: {quote['error']}")
            return

        # 2. Construire la transaction de swap
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

        # 3. Décoder, signer et envoyer la transaction
        tx_bytes = base58.b58decode(swap_data['swapTransaction'])
        private_key_bytes = base58.b58decode(CLE_PRIVEE_PHANTOM)
        signing_key = SigningKey(private_key_bytes[:32])
        signature = signing_key.sign(tx_bytes).signature
        signed_tx = tx_bytes + signature
        signed_tx_base58 = base58.b58encode(signed_tx).decode()

        rpc_url = "https://api.mainnet-beta.solana.com"
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "sendTransaction",
            "params": [signed_tx_base58, {"encoding": "base58"}]
        }
        response = requests.post(rpc_url, json=payload)
        result = response.json()

        if 'result' in result:
            print(f"✅ {'Achat' if is_buy else 'Vente'} réussi ! Signature: {result['result']}")
        else:
            print(f"❌ Erreur RPC: {result}")

    except Exception as e:
        print(f"⚠️ Erreur swap: {e}")

# ==========================================
# 4. SURVEILLANCE DE LA BALEINE
# ==========================================

def check_whale():
    global portefeuille
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{WHALE_ADDRESS}"
        response = requests.get(url)
        data = response.json()

        if 'trades' in data and len(data['trades']) > 0:
            trade = data['trades'][0]
            side = trade['side']
            token = trade['tokenAddress']
            volume = float(trade['volume'])

            # Ignorer les micro-mouvements
            if volume < 50:
                return

            if side == 'BUY':
                print(f"🔍 Baleine ACHÈTE {token} (Volume: {volume})")
                if token not in portefeuille:
                    print(f"💰 Achat de {MONTANT_USDC} USDC sur {token}...")
                    execute_swap(token, MONTANT_USDC, is_buy=True)
                    portefeuille[token] = True
                else:
                    print("⏳ Token déjà en portefeuille, on ignore.")

            elif side == 'SELL':
                print(f"🔍 Baleine VEND {token} (Volume: {volume})")
                if token in portefeuille:
                    print(f"💸 Vente du token {token}...")
                    execute_swap(token, MONTANT_USDC, is_buy=False)
                    del portefeuille[token]
                else:
                    print("⏳ Token non détenu, on ignore.")
        else:
            print("⏳ Aucun achat récent.")

    except Exception as e:
        print(f"⚠️ Erreur scan: {e}")

# ==========================================
# 5. BOUCLE PRINCIPALE
# ==========================================

if __name__ == "__main__":
    print("🚀 BOT BALEINE AUTO (ACHAT + VENTE) - SANS CLÉ EN CLAIR")
    print(f"🎯 Cible: {WHALE_ADDRESS}")
    print(f"💰 Montant par trade: {MONTANT_USDC} USDC")
    print("🔄 Vérification toutes les 20 secondes...\n")

    while True:
        check_whale()
        time.sleep(20)
