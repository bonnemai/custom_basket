import asyncio
import json
import os
import websockets

API_TOKEN = os.getenv("EODHD_API_TOKEN")
URL = f"wss://ws.eodhd.com/ws?api_token={API_TOKEN}"

async def subscribe(ws, symbols):
    # symbols = ["AAPL.US", "SPY.US", ...]
    await ws.send(json.dumps({"action": "subscribe", "symbols": symbols}))

async def unsubscribe(ws, symbols):
    await ws.send(json.dumps({"action": "unsubscribe", "symbols": symbols}))

async def receiver(ws):
    while True:
        msg = await ws.recv()
        data = json.loads(msg)
        print(data)  # -> {"s":"AAPL.US","p":..., "t":"...Z"}

async def main():
    if not API_TOKEN:
        raise ValueError("Set EODHD_API_TOKEN env variable")
    async with websockets.connect(URL) as ws:
        # Abonnement initial
        await subscribe(ws, ["AAPL.US", "MSFT.US", "TSLA.US", "BNP.PA", "SHEL.L", "SAP.DE",
                             "SPY.US", "EWG.US", "EWQ.US", "EZU.US"])

        # Tâche de réception en parallèle
        recv_task = asyncio.create_task(receiver(ws))

        # Démo: ajout/retrait dynamique
        await asyncio.sleep(5)
        print(">> Ajout dynamique de NVDA.US")
        await subscribe(ws, ["NVDA.US"])

        await asyncio.sleep(5)
        print(">> Désabonnement de TSLA.US")
        await unsubscribe(ws, ["TSLA.US"])

        # Boucle interactive optionnelle (tu peux taper : add NVDA.US / del AAPL.US / quit)
        async def interactive():
            while True:
                cmd = input("cmd (add <sym> | del <sym> | quit): ").strip()
                if cmd == "quit":
                    break
                if cmd.startswith("add "):
                    sym = cmd.split(None, 1)[1].strip()
                    await subscribe(ws, [sym])
                elif cmd.startswith("del "):
                    sym = cmd.split(None, 1)[1].strip()
                    await unsubscribe(ws, [sym])

        # Sur certains environnements, input() bloque le loop ; sinon, commente cette ligne.
        # await interactive()

        await asyncio.sleep(30)
        recv_task.cancel()

asyncio.run(main())
