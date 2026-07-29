from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_dummy_server():
    server = HTTPServer(('0.0.0.0', 10000), DummyHandler)
    server.serve_forever()

# Lance le serveur factice dans un thread séparé
threading.Thread(target=run_dummy_server, daemon=True).start()



import requests
import time
import base58
from nacl.signing import SigningKey
import json
import os
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading

# ==========================================
# PARAMÈTRES (AUCUNE CLÉ PRIVÉE EN CLAIR)
# ==========================================
WHALE_ADDRESS = "FneHsyttC7TuJrp1br112nf5NsTNKTuQqhRi6bnXj317"
VOTRE_ADRESSE_PHANTOM = "8wxEktqpmJ5NNnWaTijK1uxEtekJEKbcfYhNx6tYEM1T"

# La clé privée est lue depuis l'environnement (Render)
CLE_PRIVEE_PHANTOM = os.getenv("CLE_PRIVEE_PHANTOM")
# ⚠️ Si tu testes en local, tu peux la mettre en dur ici pour le test,
# mais SURTOUT PAS sur GitHub. Pour Render, cette ligne doit rester comme
# elle est. Si la variable n'est pas trouvée, le bot ne fonctionnera pas.

if CLE_PRIVEE_PHANTOM is None:
    print("❌ ERREUR : La variable d'environnement CLE_PRIVEE_PHANTOM n'est pas définie.")
    exit(1)

MONTANT_USDC = 10
portefeuille = {}

# ==========================================
# SERVEUR FACTICE POUR RENDER (GRATUIT)
# ==========================================
class DummyHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is running")

def run_dummy_server():
    server = HTTPServer(('0.0.0.0', 10000), DummyHandler)
    server.serve_forever()

# Lance le serveur factice dans un thread séparé
threading.Thread(target=run_dummy_server, daemon=True).start()

# ==========================================
# FONCTIONS DE SWAP
# ==========================================
def execute_swap(token_out, amount_usdt, is_buy=True):
    try:
        if is_buy:
            input_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            output_mint = token_out
        else:
            input_mint = token_out
            output_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={int(amount_usdt * 1_000_000)}&slippageBps=500"
        quote = requests.get(quote_url).json()
        
        if "error" in quote:
            print(f"❌ Erreur de route: {quote['error']}")
            return
        
        swap_payload = {
            "quoteResponse": quote,
            "userPublicKey": VOTRE_ADRESSE_PHANTOM,
            "wrapAndUnwrapSol": True,
            "dynamicComputeUnitLimit": True
        }
        swap_response = requests.post("https://quote-api.jup.ag/v6/swap", json=swap_payload)
        swap_data = swap_response.json()
        
        if 'swapTransaction' in swap_data:
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
                print(f"❌ Erreur transaction: {result}")
        else:
            print("❌ Données de swap invalides.")
    except Exception as e:
        print(f"⚠️ Erreur: {e}")

# ==========================================
# SURVEILLANCE
# ==========================================
def check_whale():
    global portefeuille
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{WHALE_ADDRESS}"
        data = requests.get(url).json()
        
        if 'trades' in data and len(data['trades']) > 0:
            trade = data['trades'][0]
            side = trade['side']
            token = trade['tokenAddress']
            volume = float(trade['volume'])
            
            if volume < 50:
                return
            
            if side == 'BUY':
                print(f"🔍 Baleine ACHÈTE {token} (Volume: {volume})")
                if token not in portefeuille:
                    print(f"💰 Achat de {MONTANT_USDC} USDC sur {token}...")
                    execute_swap(token, MONTANT_USDC, is_buy=True)
                    portefeuille[token] = True
                else:
                    print("⏳ Déjà en portefeuille.")
                    
            elif side == 'SELL':
                print(f"🔍 Baleine VEND {token} (Volume: {volume})")
                if token in portefeuille:
                    print(f"💸 Vente du token {token}...")
                    execute_swap(token, MONTANT_USDC, is_buy=False)
                    del portefeuille[token]
                else:
                    print("⏳ Pas en portefeuille, on ignore.")
        else:
            print("⏳ Aucun achat récent.")
    except Exception as e:
        print(f"⚠️ Erreur scan: {e}")

# ==========================================
# BOUCLE PRINCIPALE
# ==========================================
if __name__ == "__main__":
    print("🚀 BOT BALEINE AUTO (ACHAT + VENTE) - SANS CLÉ EN CLAIR")
    print(f"🎯 Cible: {WHALE_ADDRESS}")
    print(f"💰 Montant par trade: {MONTANT_USDC} USDC")
    print("🔄 Vérification toutes les 20 secondes...\n")
    
    while True:
        check_whale()
        time.sleep(20)