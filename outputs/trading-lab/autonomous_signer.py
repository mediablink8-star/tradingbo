"""External signer boundary for autonomous Solana execution.

The trading process never receives a private key. A separate signer/HSM/MPC service
must accept a fully built transaction and return the signed transaction bytes.
"""
import base64, json, os, re, urllib.request

class SignerClient:
    def __init__(self, endpoint=None, api_token=None, timeout=10):
        self.endpoint=(endpoint or os.environ.get("SIGNER_ENDPOINT","")).rstrip("/")
        self.api_token=api_token or os.environ.get("SIGNER_API_TOKEN","")
        self.timeout=timeout
    def configured(self): return bool(self.endpoint and self.api_token)
    def sign(self, *, wallet, transaction_b64, intent_id, message_hash):
        if not self.configured(): raise ValueError("External signer is not configured.")
        if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", wallet): raise ValueError("Invalid signer wallet.")
        if not isinstance(transaction_b64,str) or not transaction_b64: raise ValueError("Missing transaction.")
        if not re.fullmatch(r"[0-9a-f]{64}", message_hash): raise ValueError("Invalid message hash.")
        payload={"wallet":wallet,"transaction":transaction_b64,"intent_id":intent_id,"message_hash":message_hash}
        req=urllib.request.Request(self.endpoint+"/v1/sign",data=json.dumps(payload,separators=(",",":")).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer "+self.api_token,"Idempotency-Key":intent_id,"User-Agent":"TradingLabSignerClient/1.0"})
        try:
            with urllib.request.urlopen(req,timeout=self.timeout) as response: result=json.loads(response.read(200000))
        except Exception as exc: raise ValueError("External signer request failed; transaction was not broadcast by this process.") from exc
        signed=result.get("signedTransaction")
        if not isinstance(signed,str): raise ValueError("Signer did not return a signed transaction.")
        try: raw=base64.b64decode(signed,validate=True)
        except Exception as exc: raise ValueError("Signer returned invalid transaction encoding.") from exc
        if not 100<=len(raw)<=1232: raise ValueError("Signer returned an invalid transaction size.")
        return signed
