"""Bounded AI collaboration for forex paper trading. Agents have no execution tools."""
import json,os,math,urllib.request
ROLES=[("Market researcher","Summarize only supplied FX prices, trend and data quality."),("Macro analyst","Identify relevant supplied FX context and challenge unsupported assumptions."),("Strategy analyst","Propose paper entries or exits only for supplied currency pairs."),("Risk critic","Challenge the proposal and favor abstention when evidence is uncertain."),("Portfolio coordinator","Choose final paper actions while respecting every deterministic risk limit.")]
def validate_output(value,allowed,held):
 if not isinstance(value,dict) or set(value)!={"summary","approve","exit","concerns"}:raise ValueError("Invalid agent response fields")
 if not isinstance(value["summary"],str) or len(value["summary"])>3000:raise ValueError("Invalid summary")
 for k in ("approve","exit","concerns"):
  if not isinstance(value[k],list) or len(value[k])>30 or any(not isinstance(x,str) or len(x)>100 for x in value[k]):raise ValueError("Invalid agent list")
 if not set(value["approve"])<=set(allowed) or not set(value["exit"])<=set(held):raise ValueError("Agent named an unauthorized FX pair")
 return value
class ModelClient:
 def __init__(self,provider="scripted",model=""):
  if provider not in ("scripted","openai","ollama"):raise ValueError("Unknown provider")
  if provider!="scripted" and not model:raise ValueError("Model is required")
  if provider=="openai" and not os.environ.get("OPENAI_API_KEY"):raise ValueError("OPENAI_API_KEY is not configured")
  self.provider=provider;self.model=model
 def call(self,role,instructions,context,reports):
  if self.provider=="scripted":
   return {"summary":"SCRIPTED FX review: deterministic paper mode.","approve":[],"exit":[],"concerns":["No model inference was requested."]}
  payload={"model":self.model,"input":instructions+"\nContext:\n"+json.dumps(context)+"\nReports:\n"+json.dumps(reports),"store":False}
  if self.provider=="openai":
   req=urllib.request.Request("https://api.openai.com/v1/responses",data=json.dumps(payload).encode(),headers={"Content-Type":"application/json","Authorization":"Bearer "+os.environ["OPENAI_API_KEY"]})
  else: raise ValueError("Only scripted/OpenAI inference is enabled in the forex migration.")
  with urllib.request.urlopen(req,timeout=30) as response:raw=json.loads(response.read(500000))
  text=raw.get("output_text","")
  result=json.loads(text)
  return validate_output(result,context.get("pairs",[]),context.get("held",[]))
