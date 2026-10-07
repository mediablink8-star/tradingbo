// Public discovery only. No API key, wallet, trading endpoint or metered stream.
const ENDPOINT = 'wss://pumpportal.fun/api/data';
const emit = value => process.stdout.write(JSON.stringify(value) + '\n');
if (typeof WebSocket !== 'function') {
  emit({type:'status',status:'error',message:'Node.js 22+ with built-in WebSocket is required.'});
  process.exit(1);
}
let socket, retryTimer, heartbeat, openingTimer, stopped=false, backoff=5000;
function connect() {
  if(stopped)return;
  emit({type:'status',status:'connecting',message:'Connecting to the public PumpPortal discovery feed.'});
  socket=new WebSocket(ENDPOINT);let openedAt=0;
  openingTimer=setTimeout(()=>socket.close(),15000);
  socket.onopen=()=>{
    clearTimeout(openingTimer);openedAt=Date.now();
    socket.send(JSON.stringify({method:'subscribeNewToken'}));
    socket.send(JSON.stringify({method:'subscribeMigration'}));
    emit({type:'status',status:'connected',message:'Socket open; waiting for subscription acknowledgements.'});
    heartbeat=setInterval(()=>emit({type:'heartbeat'}),10000);
  };
  socket.onmessage=event=>{
    if(typeof event.data!=='string' || event.data.length>1000000){emit({type:'status',status:'warning',message:'Oversized or non-text message rejected.'});return;}
    try{emit({type:'event',payload:JSON.parse(event.data)});}
    catch{emit({type:'status',status:'warning',message:'Invalid JSON message rejected.'});}
  };
  socket.onerror=()=>emit({type:'status',status:'error',message:'PumpPortal socket connection failed. Check network access or provider availability.'});
  socket.onclose=()=>{
    clearInterval(heartbeat);clearTimeout(openingTimer);
    if(stopped)return;
    if(openedAt && Date.now()-openedAt>30000)backoff=5000;
    emit({type:'status',status:'reconnecting',message:`Disconnected; data gap recorded. Retry in ${backoff/1000}s.`});
    retryTimer=setTimeout(connect,backoff);backoff=Math.min(backoff*2,60000);
  };
}
function stop(){stopped=true;clearTimeout(retryTimer);clearTimeout(openingTimer);clearInterval(heartbeat);socket?.close();process.exit(0);}
process.on('SIGTERM',stop);process.on('SIGINT',stop);connect();
