"""Ember Forex Trading Lab HTTP application."""
import argparse,json,os
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from pathlib import Path
from forex_lab import ForexLab
ROOT=Path(__file__).resolve().parent
LAB=ForexLab(ROOT/"lab.sqlite")
class Handler(BaseHTTPRequestHandler):
    def send_json(self,data,status=200):
        raw=json.dumps(data,allow_nan=False).encode();self.send_response(status);self.send_header("Content-Type","application/json");self.send_header("Cache-Control","no-store");self.end_headers();self.wfile.write(raw)
    def do_GET(self):
        if self.path=="/api/forex":self.send_json(LAB.tick());return
        if self.path=="/":self.send_response(200);self.send_header("Content-Type","text/html; charset=utf-8");self.end_headers();self.wfile.write((ROOT/"index.html").read_bytes());return
        self.send_json({"error":"not found"},404)
    def do_POST(self):
        if self.path not in ("/api/forex/open","/api/forex/close"):self.send_json({"error":"not found"},404);return
        if self.headers.get("Content-Type")!="application/json":self.send_json({"error":"JSON required"},400);return
        try:
            n=int(self.headers.get("Content-Length","0"))
            if not 1<=n<=10000:raise ValueError("Invalid request size")
            data=json.loads(self.rfile.read(n))
            if self.path=="/api/forex/open":
                result=LAB.open(data.get("pair"),data.get("side"),float(data.get("notional")))
            else:result=LAB.close(data.get("id"))
            self.send_json(result)
        except Exception as exc:self.send_json({"error":str(exc)},400)
if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--port",type=int,default=8765);args=parser.parse_args()
    print(f"Ember Forex Trading Lab: http://127.0.0.1:{args.port}",flush=True)
    ThreadingHTTPServer(("127.0.0.1",args.port),Handler).serve_forever()
