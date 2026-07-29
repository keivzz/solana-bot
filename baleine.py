import requests
import time
import base58
from nacl.signing import SigningKey
import json

# ==========================================
# TES INFORMATIONS (À REMPLIR)
# ==========================================
WHALE_ADDRESS = "FneHsyttC7TuJrp1br112nf5NsTNKTuQqhRi6bnXj317"
VOTRE_ADRESSE_PHANTOM = "8wxEktqpmJ5NNnWaTijK1uxEtekJEKbcfYhNx6tYEM1T"
CLE_PRIVEE_BASE58 = "PW1Lc8G5RCh4hBrrW8A6cHCACmVQiKsnzSZu553CeTmkRQ2rENB2B92tj8ppVbJib7vsTkSBEdL5bZFsJ4BBisn"  # La vraie clé du nouveau compte

# Montant à investir par trade (en USDC)
MONTANT_USDC = 10

# Dictionnaire pour stocker les tokens achetés et leur prix
portefeuille = {}

# ==========================================
# FONCTIONS DE SWAP VIA JUPITER
# ==========================================

def execute_swap(token_out, amount_usdt, is_buy=True):
    """
    is_buy=True : swap USDC -> Token (achat)
    is_buy=False : swap Token -> USDC (vente)
    """
    try:
        # 1. Obtenir la route
        if is_buy:
            input_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC
            output_mint = token_out
        else:
            input_mint = token_out
            output_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC

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
            # Signer et envoyer
            tx_bytes = base58.b58decode(swap_data['swapTransaction'])
            private_key_bytes = base58.b58decode(CLE_PRIVEE_BASE58)
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
# SURVEILLANCE DE LA BALEINE
# ==========================================

def check_whale():
    global portefeuille
    try:
        url = f"https://api.dexscreener.com/latest/dex/tokens/{WHALE_ADDRESS}"
        data = requests.get(url).json()
        
        if 'trades' in data and len(data['trades']) > 0:
            trade = data['trades'][0]  # Dernier trade
            side = trade['side']       # 'BUY' ou 'SELL'
            token = trade['tokenAddress']
            volume = float(trade['volume'])
            
            # Ignorer les petits mouvements
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
                    execute_swap(token, MONTANT_USDC, is_buy=False)  # On vend environ la même quantité
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
    print("🚀 BOT BALEINE AUTO (ACHAT + VENTE)")
    print(f"🎯 Cible: {WHALE_ADDRESS}")
    print(f"💰 Montant par trade: {MONTANT_USDC} USDC")
    print("🔄 Vérification toutes les 20 secondes...")
    print("📌 Si la baleine achète, j'achète. Si elle vend, je vends.\n")
    
    while True:
        check_whale()
        time.sleep(20)