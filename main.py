"""
SnapFeed — Telegram Photo Feed Mini App
Render.com ready — single file
"""
import os, json, sqlite3, hashlib, hmac, time, threading
from datetime import datetime, date
from urllib.parse import parse_qsl
from flask import Flask, request, jsonify, Response, make_response
import requests

# ============================================================
# CONFIG (Render Environment Variables)
# ============================================================
BOT_TOKEN = os.environ.get("BOT_TOKEN", "PASTE_YOUR_BOT_TOKEN")
WEBAPP_URL = os.environ.get("WEBAPP_URL", "")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")
PORT = int(os.environ.get("PORT", 8080))

DATA_DIR = os.environ.get("DATA_DIR", os.path.dirname(os.path.abspath(__file__)))
os.makedirs(DATA_DIR, exist_ok=True)
CFG_FILE = os.path.join(DATA_DIR, "config.json")
DB_FILE = os.path.join(DATA_DIR, "data.db")

DEFAULT = {
    "bot_token": BOT_TOKEN,
    "webapp_url": WEBAPP_URL or "https://your-app.onrender.com",
    "admin_password": ADMIN_PASSWORD,
    "admin_tg_ids": [],
    "site_name": "SnapFeed",
    "tagline": "Scroll. Smile. Share.",
    "welcome_message": "Welcome to SnapFeed!",
    "primary_color": "#0088cc",
    "bg_color": "#000000",
    "text_color": "#ffffff",
    "enable_likes": True,
    "enable_comments": True,
    "enable_upload": True,
    "enable_share": True,
    "upload_limit_per_day": 10,
    "feed_page_size": 10,
    "max_caption": 500,
    "require_approval": False,
    "footer_text": "SnapFeed",
    "ads_text": "",
    "show_premium_badge": True,
}

def load_cfg():
    if not os.path.exists(CFG_FILE):
        with open(CFG_FILE, "w", encoding="utf-8") as f:
            json.dump(DEFAULT, f, indent=2, ensure_ascii=False)
    with open(CFG_FILE, "r", encoding="utf-8") as f:
        c = json.load(f)
    for k, v in DEFAULT.items():
        c.setdefault(k, v)
    c["bot_token"] = BOT_TOKEN or c["bot_token"]
    if WEBAPP_URL:
        c["webapp_url"] = WEBAPP_URL
    if ADMIN_PASSWORD:
        c["admin_password"] = ADMIN_PASSWORD
    return c

def save_cfg(c):
    with open(CFG_FILE, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=2, ensure_ascii=False)

CFG = load_cfg()

# ============================================================
# DATABASE
# ============================================================
def db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        tg_id INTEGER UNIQUE, username TEXT, first_name TEXT, photo_url TEXT,
        joined_at TEXT, is_banned INTEGER DEFAULT 0,
        is_premium INTEGER DEFAULT 0, is_admin INTEGER DEFAULT 0,
        upload_count_today INTEGER DEFAULT 0, last_upload_date TEXT);
    CREATE TABLE IF NOT EXISTS posts(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER, file_id TEXT, file_type TEXT, caption TEXT,
        created_at TEXT, is_approved INTEGER DEFAULT 1, is_hidden INTEGER DEFAULT 0,
        views INTEGER DEFAULT 0, likes INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS likes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER, user_id INTEGER, created_at TEXT,
        UNIQUE(post_id, user_id));
    CREATE TABLE IF NOT EXISTS comments(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        post_id INTEGER, user_id INTEGER, text TEXT, created_at TEXT);
    """)
    conn.commit(); conn.close()

init_db()

# ============================================================
# TELEGRAM HELPERS
# ============================================================
def tg(method, **params):
    if not CFG["bot_token"] or "PASTE" in CFG["bot_token"]:
        return {"ok": False}
    try:
        r = requests.post(
            "https://api.telegram.org/bot" + CFG["bot_token"] + "/" + method,
            data=params, timeout=30)
        return r.json()
    except Exception as e:
        print("[TG]", method, e)
        return {"ok": False}

def tg_file(file_id):
    r = tg("getFile", file_id=file_id)
    if not r.get("ok"):
        return None
    return "https://api.telegram.org/file/bot" + CFG["bot_token"] + "/" + r["result"]["file_path"]

def validate_init(init_data):
    if not init_data:
        return None
    try:
        p = dict(parse_qsl(init_data, keep_blank_values=True))
        h = p.pop("hash", None)
        if not h:
            return None
        dcs = "\n".join(k + "=" + v for k, v in sorted(p.items()))
        secret = hmac.new(b"WebAppData", CFG["bot_token"].encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, dcs.encode(), hashlib.sha256).hexdigest()
        if calc != h:
            return None
        if "user" in p:
            p["user"] = json.loads(p["user"])
        return p
    except Exception:
        return None

# ============================================================
# FLASK
# ============================================================
app = Flask(__name__)

def ensure_user(tid, u):
    conn = db(); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE tg_id=?", (tid,))
    row = c.fetchone()
    is_admin = 1 if tid in CFG.get("admin_tg_ids", []) else 0
    if not row:
        c.execute("INSERT INTO users(tg_id,username,first_name,photo_url,joined_at,is_admin) "
                  "VALUES(?,?,?,?,?,?)",
                  (tid, u.get("username"), u.get("first_name"),
                   u.get("photo_url"), datetime.utcnow().isoformat(), is_admin))
        conn.commit()
        c.execute("SELECT * FROM users WHERE tg_id=?", (tid,))
        row = c.fetchone()
    conn.close()
    if row["is_banned"]:
        return None
    return dict(row)

def get_user():
    init = request.headers.get("X-Init-Data") or request.args.get("init_data", "")
    p = validate_init(init)
    if not p:
        return None
    u = p.get("user", {})
    tid = u.get("id")
    if not tid:
        return None
    return ensure_user(tid, u)

def admin_ok():
    tok = hashlib.sha256((CFG["admin_password"] + CFG["bot_token"]).encode()).hexdigest()
    return request.cookies.get("asess") == tok

# ============================================================
# MINI APP HTML
# ============================================================
APP_HTML = r"""<!DOCTYPE html><html><head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no,viewport-fit=cover">
<title>SnapFeed</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
:root{--p:#0088cc;--bg:#000;--tx:#fff;--muted:rgba(255,255,255,.55);--safe-top:env(safe-area-inset-top,0px);--safe-bot:env(safe-area-inset-bottom,0px)}
*{margin:0;padding:0;box-sizing:border-box;-webkit-tap-highlight-color:transparent;-webkit-user-select:none;user-select:none}
html,body{height:100%;overflow:hidden;background:var(--bg);color:var(--tx);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;-webkit-font-smoothing:antialiased;overscroll-behavior:none}
img,video{-webkit-user-drag:none}
#hdr{position:fixed;top:0;left:0;right:0;z-index:30;padding:calc(12px + var(--safe-top)) 16px 12px;display:flex;justify-content:space-between;align-items:center;background:linear-gradient(180deg,rgba(0,0,0,.75),transparent);pointer-events:none}
#hdr .brand{display:flex;align-items:center;gap:8px;pointer-events:auto}
#hdr .dot{width:8px;height:8px;border-radius:50%;background:var(--p);box-shadow:0 0 12px var(--p);animation:pulse 2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
#hdr h1{font-size:19px;font-weight:800;letter-spacing:-.5px;background:linear-gradient(135deg,#fff,var(--p));-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent}
#hdr .hbtns{display:flex;gap:6px;pointer-events:auto}
#hdr .hbtn{width:38px;height:38px;border-radius:50%;background:rgba(255,255,255,.12);backdrop-filter:blur(16px);border:1px solid rgba(255,255,255,.1);color:#fff;font-size:17px;cursor:pointer;display:flex;align-items:center;justify-content:center}
#hdr .hbtn:active{transform:scale(.9)}
#view{position:relative;height:100vh;overflow:hidden}
.feed{height:100vh;overflow-y:scroll;scroll-snap-type:y mandatory;-webkit-overflow-scrolling:touch;overscroll-behavior-y:contain}
.feed::-webkit-scrollbar{display:none}
.post{height:100vh;scroll-snap-align:start;scroll-snap-stop:always;position:relative;display:flex;align-items:center;justify-content:center;background:#000;overflow:hidden}
.post .mw{width:100%;height:100%;display:flex;align-items:center;justify-content:center;position:relative}
.post img,.post video{width:100%;height:100%;object-fit:contain;background:#000}
.post .ml{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:34px;height:34px;border:3px solid rgba(255,255,255,.15);border-top-color:var(--p);border-radius:50%;animation:spin .8s linear infinite}
@keyframes spin{to{transform:translate(-50%,-50%) rotate(360deg)}}
.post .ov{position:absolute;bottom:0;left:0;right:0;padding:32px 18px 110px;background:linear-gradient(0deg,rgba(0,0,0,.9) 0%,rgba(0,0,0,.5) 40%,transparent);pointer-events:none}
.post .ov .un{display:flex;align-items:center;gap:10px;margin-bottom:10px;pointer-events:auto}
.post .ov .av{width:40px;height:40px;border-radius:50%;object-fit:cover;border:2.5px solid var(--p)}
.post .ov .nm{font-weight:700;font-size:16px}
.post .ov .cap{font-size:14.5px;line-height:1.45;opacity:.95;word-break:break-word;max-height:3.9em;overflow:hidden;text-shadow:0 1px 3px rgba(0,0,0,.8)}
.post .ov .cap.ex{max-height:none}
.post .ov .time{font-size:11px;color:var(--muted);margin-top:6px}
.actions{position:absolute;right:12px;bottom:130px;display:flex;flex-direction:column;gap:18px;z-index:5}
.actions .item{display:flex;flex-direction:column;align-items:center;gap:4px}
.actions .ab{width:48px;height:48px;border-radius:50%;background:rgba(0,0,0,.45);backdrop-filter:blur(12px);border:1px solid rgba(255,255,255,.08);color:#fff;font-size:22px;cursor:pointer;display:flex;align-items:center;justify-content:center}
.actions .ab:active{transform:scale(.85)}
.actions .ab.liked{background:rgba(255,43,94,.2);animation:hb .4s}
@keyframes hb{0%{transform:scale(1)}40%{transform:scale(1.3)}70%{transform:scale(.9)}100%{transform:scale(1)}}
.actions .cnt{font-size:11.5px;font-weight:700;text-shadow:0 1px 3px rgba(0,0,0,.9);min-width:24px;text-align:center}
.nav{position:fixed;bottom:0;left:0;right:0;z-index:20;display:flex;background:rgba(10,10,10,.85);backdrop-filter:blur(24px);border-top:1px solid rgba(255,255,255,.06);padding:8px 0 calc(8px + var(--safe-bot))}
.nav button{flex:1;background:none;border:none;color:rgba(255,255,255,.45);padding:6px;font-size:10.5px;font-weight:600;display:flex;flex-direction:column;align-items:center;gap:3px;cursor:pointer}
.nav button.on{color:var(--p)}
.nav button .ic{font-size:22px;line-height:1}
.modal{position:fixed;inset:0;z-index:100;background:rgba(0,0,0,.75);backdrop-filter:blur(8px);display:none;align-items:flex-end}
.modal.on{display:flex}
.modal .sh{background:#161616;width:100%;max-height:82vh;border-radius:22px 22px 0 0;padding:8px 20px calc(20px + var(--safe-bot));overflow-y:auto;border-top:1px solid rgba(255,255,255,.08)}
.modal .hd{width:40px;height:4px;background:rgba(255,255,255,.2);border-radius:2px;margin:0 auto 14px}
.modal h2{font-size:17px;font-weight:800;margin-bottom:14px}
.modal textarea,.modal input{width:100%;background:#000;color:#fff;border:1px solid rgba(255,255,255,.12);border-radius:12px;padding:12px 14px;font-size:14px;font-family:inherit;resize:none;outline:none}
.modal textarea:focus,.modal input:focus{border-color:var(--p)}
.btn{width:100%;padding:14px;background:linear-gradient(135deg,var(--p),#00a0e8);color:#fff;border:none;border-radius:12px;font-weight:700;font-size:15px;cursor:pointer;margin-top:10px}
.btn.g{background:rgba(255,255,255,.08)}
.cm{display:flex;gap:10px;padding:10px 0;border-bottom:1px solid rgba(255,255,255,.06)}
.cm .cav{width:34px;height:34px;border-radius:50%;object-fit:cover;flex-shrink:0;border:1.5px solid rgba(255,255,255,.15)}
.cm .cb{flex:1;min-width:0}
.cm .cn{font-size:13px;font-weight:700;color:var(--p)}
.cm .ct{font-size:14px;margin-top:3px;line-height:1.4;word-break:break-word}
.cm .cd{font-size:10.5px;color:var(--muted);margin-top:4px}
.pr{padding:calc(80px + var(--safe-top)) 20px calc(100px + var(--safe-bot));overflow-y:auto;height:100vh}
.pr .tp{display:flex;align-items:center;gap:16px;margin-bottom:22px}
.pr .av{width:86px;height:86px;border-radius:50%;object-fit:cover;border:3px solid var(--p);box-shadow:0 4px 24px rgba(0,136,204,.35)}
.pr .info h2{font-size:20px;font-weight:800}
.pr .info .un{font-size:13px;color:var(--muted);margin-top:3px}
.pr .bdg{display:flex;gap:6px;margin-top:8px;flex-wrap:wrap}
.pr .bg{font-size:10px;padding:3px 9px;border-radius:10px;font-weight:700;background:linear-gradient(135deg,var(--p),#00c8ff);color:#fff}
.pr .st{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;background:rgba(255,255,255,.04);border-radius:16px;padding:16px;margin-bottom:20px;border:1px solid rgba(255,255,255,.06)}
.pr .stat{text-align:center}
.pr .stat .n{font-size:20px;font-weight:800;color:var(--p)}
.pr .stat .l{font-size:11px;color:var(--muted);margin-top:2px;font-weight:600}
.pr .gr{display:grid;grid-template-columns:repeat(3,1fr);gap:3px;border-radius:12px;overflow:hidden}
.pr .gr .cl{position:relative;aspect-ratio:1;overflow:hidden;background:#111}
.pr .gr .cl img,.pr .gr .cl video{width:100%;height:100%;object-fit:cover}
.pr .gr .cl .co{position:absolute;bottom:0;right:0;padding:3px 6px;font-size:10px;font-weight:700;background:rgba(0,0,0,.6);border-radius:8px 0 0 0}
.empty{display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;padding:40px;text-align:center}
.empty .ic{font-size:70px;margin-bottom:16px}
.empty h3{font-size:20px;font-weight:800;margin-bottom:8px}
.empty p{color:var(--muted);font-size:14px;line-height:1.5}
.loader{display:flex;align-items:center;justify-content:center;height:100vh;flex-direction:column;gap:14px}
.loader .sp{width:38px;height:38px;border:3px solid rgba(255,255,255,.12);border-top-color:var(--p);border-radius:50%;animation:spin2 1s linear infinite}
@keyframes spin2{to{transform:rotate(360deg)}}
.toast{position:fixed;top:calc(70px + var(--safe-top));left:50%;transform:translateX(-50%) translateY(-30px);background:rgba(30,30,30,.95);backdrop-filter:blur(20px);color:#fff;padding:11px 20px;border-radius:24px;font-size:13px;font-weight:600;opacity:0;pointer-events:none;transition:all .3s;z-index:1000;border:1px solid rgba(255,255,255,.1)}
.toast.on{opacity:1;transform:translateX(-50%) translateY(0)}
</style></head><body>

<div id="ld" class="loader"><div class="sp"></div></div>

<div id="wrp" style="display:none">
  <div id="hdr">
    <div class="brand"><div class="dot"></div><h1 id="sn">SnapFeed</h1></div>
    <div class="hbtns"><button class="hbtn" id="rf">↻</button></div>
  </div>
  <div id="view"></div>
  <div class="nav">
    <button data-v="feed" class="on"><span class="ic">⊞</span>Feed</button>
    <button data-v="up"><span class="ic">⊕</span>Upload</button>
    <button data-v="pr"><span class="ic">◉</span>Profile</button>
  </div>
</div>

<div class="modal" id="cm"><div class="sh">
  <div class="hd"></div><h2>Comments</h2>
  <div id="cml" style="max-height:44vh;overflow-y:auto"></div>
  <div style="display:flex;gap:8px;margin-top:14px">
    <input id="cmi" placeholder="Add a comment..." maxlength="500" style="flex:1">
    <button class="btn" style="flex:0 0 74px;margin:0;padding:12px" id="cms">Send</button>
  </div>
</div></div>

<div class="modal" id="um"><div class="sh">
  <div class="hd"></div><h2>Upload</h2>
  <p style="color:var(--muted);font-size:13.5px;line-height:1.5;margin-bottom:14px">Open the bot chat and send your photo or video.</p>
  <div style="background:#000;border:2px dashed rgba(255,255,255,.15);border-radius:14px;padding:28px;text-align:center">
    <div style="font-size:48px;margin-bottom:8px">📸</div>
    <p style="color:var(--muted);font-size:13px">Send a photo to the bot</p>
  </div>
  <button class="btn g" id="uc" style="margin-top:14px">Close</button>
</div></div>

<div class="toast" id="toast"></div>

<script>
const tg=window.Telegram&&window.Telegram.WebApp;
if(tg){tg.ready();tg.expand();if(tg.disableVerticalSwipes)tg.disableVerticalSwipes();if(tg.setHeaderColor)tg.setHeaderColor('#000000');if(tg.setBackgroundColor)tg.setBackgroundColor('#000000');}
const ID=tg?tg.initData:'';
const H={'X-Init-Data':ID};
let CFG={},ME={},PID=null,PTID=null;
const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
function esc(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function timeAgo(iso){try{const d=new Date(iso+'Z');const s=Math.floor((Date.now()-d.getTime())/1000);if(s<60)return'just now';if(s<3600)return Math.floor(s/60)+'m ago';if(s<86400)return Math.floor(s/3600)+'h ago';if(s<604800)return Math.floor(s/86400)+'d ago';return d.toLocaleDateString();}catch(e){return'';}}
function toast(m){const t=$('#toast');t.textContent=m;t.classList.add('on');clearTimeout(t._t);t._t=setTimeout(()=>t.classList.remove('on'),2400);}
async function G(p){const r=await fetch(p,{headers:H});if(!r.ok)throw new Error('auth');return r.json();}
async function P(p,f){const r=await fetch(p,{method:'POST',headers:H,body:f});if(!r.ok)throw new Error('post');return r.json();}

(async function boot(){
  try{
    CFG=await G('/api/config');
    document.documentElement.style.setProperty('--p',CFG.primary_color);
    document.documentElement.style.setProperty('--bg',CFG.bg_color);
    document.documentElement.style.setProperty('--tx',CFG.text_color);
    ME=await G('/api/me');
    $('#sn').textContent=CFG.site_name||'SnapFeed';
    $('#ld').style.display='none';
    $('#wrp').style.display='block';
    feed();
  }catch(e){
    $('#ld').innerHTML='<div style="text-align:center;padding:30px;color:#888"><div style="font-size:50px;margin-bottom:14px">🔒</div><p>Open from Telegram</p></div>';
  }
})();

$$('.nav button').forEach(b=>b.onclick=()=>{
  $$('.nav button').forEach(x=>x.classList.remove('on'));
  b.classList.add('on');
  const v=b.dataset.v;
  if(v==='feed')feed();
  else if(v==='up')$('#um').classList.add('on');
  else if(v==='pr')profile(ME.tg_id);
});

$('#rf').onclick=()=>{
  const cur=document.querySelector('.nav .on').dataset.v;
  if(cur==='feed')feed(); else if(cur==='pr')profile(PTID);
  if(tg&&tg.HapticFeedback)tg.HapticFeedback.impactOccurred('light');
  toast('Refreshed');
};

async function feed(){
  const v=$('#view');
  v.innerHTML='<div class="loader" style="height:100vh"><div class="sp"></div></div>';
  try{
    const r=await G('/api/feed?page=1');
    if(!r.posts.length){v.innerHTML='<div class="empty"><div class="ic">📷</div><h3>No posts yet</h3><p>Be the first to share a photo!</p></div>';return;}
    v.innerHTML='<div class="feed" id="fd"></div>';
    const fd=$('#fd');
    r.posts.forEach(p=>fd.appendChild(renderPost(p)));
    let pg=1,loading=false;
    fd.onscroll=async()=>{
      if(loading)return;
      if(fd.scrollTop+fd.clientHeight>=fd.scrollHeight-500){
        loading=true;pg++;
        try{const x=await G('/api/feed?page='+pg);x.posts.forEach(p=>fd.appendChild(renderPost(p)));}catch(e){}
        loading=false;
      }
    };
  }catch(e){v.innerHTML='<div class="empty"><div class="ic">⚠️</div><h3>Error</h3><p>'+esc(e.message)+'</p></div>';}
}

function renderPost(p){
  const d=document.createElement('div');d.className='post';
  const av=p.photo_url||'https://telegram.org/img/t_logo.png';
  const isVideo=p.file_type==='video';
  const mediaTag=isVideo?'<video src="/media/'+p.file_id+'" autoplay muted loop playsinline preload="metadata"></video>':'<img src="/media/'+p.file_id+'" loading="lazy">';
  d.innerHTML='<div class="mw">'+mediaTag+'<div class="ml"></div></div>'
    +'<div class="ov"><div class="un"><img class="av" src="'+av+'"><span class="nm">'+esc(p.first_name||p.username||'User')+'</span></div>'
    +(p.caption?'<div class="cap">'+esc(p.caption)+'</div>':'')
    +(p.created_at?'<div class="time">'+timeAgo(p.created_at)+'</div>':'')
    +'</div><div class="actions">'
    +(CFG.enable_likes?'<div class="item"><button class="ab lb'+(p.liked?' liked':'')+'">'+(p.liked?'❤️':'🤍')+'</button><div class="cnt c'+p.id+'">'+p.likes+'</div></div>':'')
    +(CFG.enable_comments?'<div class="item"><button class="ab cb">💬</button><div class="cnt">'+(p.comment_count||0)+'</div></div>':'')
    +(CFG.enable_share?'<div class="item"><button class="ab sb">📤</button></div>':'')
    +'</div>';
  const media=d.querySelector('img,video');
  const loader=d.querySelector('.ml');
  if(media&&loader){const done=()=>loader.style.display='none';media.addEventListener('load',done);media.addEventListener('loadeddata',done);media.addEventListener('error',done);setTimeout(done,4000);}
  const lb=d.querySelector('.lb');
  if(lb)lb.onclick=async()=>{try{const r=await P('/api/like/'+p.id,new FormData());lb.textContent=r.liked?'❤️':'🤍';lb.classList.toggle('liked',r.liked);d.querySelector('.c'+p.id).textContent=r.likes;if(tg&&tg.HapticFeedback)tg.HapticFeedback.impactOccurred('light');}catch(e){toast('Error');}};
  const cb=d.querySelector('.cb');if(cb)cb.onclick=()=>openComments(p.id);
  const sb=d.querySelector('.sb');
  if(sb)sb.onclick=()=>{const u=CFG.webapp_url||location.origin;if(tg)tg.openTelegramLink('https://t.me/share/url?url='+encodeURIComponent(u)+'&text='+encodeURIComponent('Check SnapFeed!'));else if(navigator.share)navigator.share({url:u});};
  const cap=d.querySelector('.cap');if(cap)cap.onclick=()=>cap.classList.toggle('ex');
  return d;
}

async function openComments(id){
  PID=id;$('#cm').classList.add('on');
  const l=$('#cml');
  l.innerHTML='<div style="padding:30px;text-align:center"><div class="sp" style="display:inline-block;width:32px;height:32px;border:3px solid rgba(255,255,255,.15);border-top-color:var(--p);border-radius:50%;animation:spin2 1s linear infinite"></div></div>';
  try{
    const r=await G('/api/comments/'+id);
    if(!r.comments.length){l.innerHTML='<p style="color:var(--muted);text-align:center;padding:24px">No comments yet</p>';return;}
    l.innerHTML=r.comments.map(c=>{const av=c.photo_url||'https://telegram.org/img/t_logo.png';return '<div class="cm"><img class="cav" src="'+av+'"><div class="cb"><div class="cn">'+esc(c.first_name||c.username||'User')+'</div><div class="ct">'+esc(c.text)+'</div><div class="cd">'+timeAgo(c.created_at)+'</div></div></div>';}).join('');
  }catch(e){l.innerHTML='<p style="color:var(--muted);text-align:center;padding:24px">Error</p>';}
}

$('#cms').onclick=async()=>{
  const t=$('#cmi').value.trim();
  if(!t||!PID)return;
  const fd=new FormData();fd.append('text',t);
  try{await P('/api/comment/'+PID,fd);$('#cmi').value='';if(tg&&tg.HapticFeedback)tg.HapticFeedback.notificationOccurred('success');openComments(PID);}catch(e){toast('Error');}
};
$('#cmi').addEventListener('keydown',e=>{if(e.key==='Enter')$('#cms').click();});

async function profile(tid){
  PTID=tid;
  const v=$('#view');
  v.innerHTML='<div class="loader" style="height:100vh"><div class="sp"></div></div>';
  try{
    const r=await G('/api/profile/'+tid);
    const u=r.user;const av=u.photo_url||'https://telegram.org/img/t_logo.png';
    let h='<div class="pr"><div class="tp"><img class="av" src="'+av+'"><div class="info"><h2>'+esc(u.first_name||u.username||'User')+'</h2>'+(u.username?'<div class="un">@'+esc(u.username)+'</div>':'')+'<div class="bdg">'+(u.is_premium?'<span class="bg">Premium</span>':'')+(u.is_admin?'<span class="bg">Admin</span>':'')+'</div></div></div>';
    h+='<div class="st"><div class="stat"><div class="n">'+r.post_count+'</div><div class="l">POSTS</div></div><div class="stat"><div class="n">'+(r.total_likes||0)+'</div><div class="l">LIKES</div></div><div class="stat"><div class="n">'+(r.total_comments||0)+'</div><div class="l">COMMENTS</div></div></div>';
    if(r.posts.length){h+='<div class="gr">'+r.posts.map(p=>{if(p.file_type==='video')return '<div class="cl"><video src="/media/'+p.file_id+'" muted preload="metadata"></video><div class="co">▶ '+p.likes+'</div></div>';return '<div class="cl"><img src="/media/'+p.file_id+'" loading="lazy"><div class="co">❤ '+p.likes+'</div></div>';}).join('')+'</div>';}
    else h+='<p style="color:var(--muted);text-align:center;padding:30px">No posts yet</p>';
    h+='</div>';
    v.innerHTML=h;
  }catch(e){v.innerHTML='<div class="empty"><div class="ic">⚠️</div><h3>Error</h3><p>'+esc(e.message)+'</p></div>';}
}

$('#uc').onclick=()=>$('#um').classList.remove('on');
['cm','um'].forEach(id=>{const m=$('#'+id);m.onclick=e=>{if(e.target===m)m.classList.remove('on');};});
document.addEventListener('touchmove',e=>{if(e.target.closest('.feed'))e.stopPropagation();},{passive:false});
</script></body></html>"""

# ============================================================
# ADMIN HTML
# ============================================================
ADMIN_HTML = r"""<!DOCTYPE html><html><head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>SnapFeed Admin</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:#0a0a0a;color:#eee;padding:16px;max-width:960px;margin:0 auto}
h1{font-size:24px;margin-bottom:6px;background:linear-gradient(135deg,#4af,#08c);-webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;font-weight:800}
.sub{color:#666;font-size:13px;margin-bottom:20px}
h2{font-size:14px;margin:22px 0 10px;color:#4af;text-transform:uppercase;letter-spacing:1px;font-weight:700}
.card{background:#151515;padding:16px;border-radius:12px;margin-bottom:12px;border:1px solid #222}
label{display:block;font-size:12px;color:#999;margin-top:12px;font-weight:600}
input,textarea,select{width:100%;padding:10px 12px;background:#000;color:#fff;border:1px solid #2a2a2a;border-radius:8px;font-size:14px;font-family:inherit;margin-top:5px;outline:none}
input:focus,textarea:focus,select:focus{border-color:#4af}
.row{display:flex;gap:10px;flex-wrap:wrap}
.row>div{flex:1;min-width:140px}
button{padding:10px 16px;background:#4af;color:#fff;border:none;border-radius:8px;font-weight:700;cursor:pointer;margin-top:10px;font-size:13px}
button.danger{background:#c33}
button.ghost{background:#333}
.tabs{display:flex;gap:6px;margin-bottom:16px;flex-wrap:wrap}
.tabs button{padding:8px 16px;background:#1a1a1a;margin:0;font-size:13px;border:1px solid #2a2a2a}
.tabs button.on{background:#4af;border-color:#4af}
.stat{display:inline-block;background:#151515;padding:14px 20px;border-radius:10px;margin:4px;text-align:center;min-width:100px;border:1px solid #222}
.stat .n{font-size:24px;font-weight:800;color:#4af}
.stat .l{font-size:10px;color:#888;text-transform:uppercase;letter-spacing:1px;margin-top:3px}
.item{background:#151515;padding:12px;border-radius:10px;margin-bottom:8px;display:flex;gap:12px;align-items:center;border:1px solid #222}
.item img,.item video{width:64px;height:64px;object-fit:cover;border-radius:8px;flex-shrink:0}
.item .info{flex:1;font-size:13px;min-width:0}
.item .info .cap{color:#888;font-size:12px;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.item .info small{color:#666}
.item .btns{display:flex;gap:4px;flex-wrap:wrap;justify-content:flex-end}
.item .btns button{padding:6px 10px;font-size:11px;margin:0;min-width:auto}
.login{max-width:360px;margin:120px auto;text-align:center}
.msg{position:fixed;top:16px;right:16px;background:#4af;color:#fff;padding:12px 20px;border-radius:10px;display:none;z-index:1000;font-size:13px;font-weight:600}
</style></head><body>
<div class="msg" id="msg"></div>
<div id="app"></div>
<script>
const $=s=>document.querySelector(s);
const $$=s=>[...document.querySelectorAll(s)];
let CFG={},TAB='stats';
function toast(m){const e=$('#msg');e.textContent=m;e.style.display='block';setTimeout(()=>e.style.display='none',2400);}
function esc(s){return String(s||'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
async function api(p,o){const r=await fetch(p,{credentials:'include',...o});if(!r.ok)throw new Error(await r.text());return r.json();}

async function boot(){try{CFG=await api('/admin/api/settings');render();}catch(e){renderLogin();}}
function renderLogin(){$('#app').innerHTML='<div class="login"><h1>SnapFeed Admin</h1><p class="sub">Sign in</p><div class="card"><label>Password</label><input type="password" id="pw" autofocus><button onclick="doLogin()" style="width:100%;margin-top:14px">Login</button></div></div>';}
async function doLogin(){const pw=$('#pw').value;const r=await fetch('/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:pw}),credentials:'include'});if(r.ok){toast('OK');boot();}else toast('Wrong');}
function render(){$('#app').innerHTML='<h1>SnapFeed Admin</h1><p class="sub">Manage your app</p><div class="tabs"><button class="'+(TAB==='stats'?'on':'')+'" onclick="setTab(\'stats\')">Dashboard</button><button class="'+(TAB==='settings'?'on':'')+'" onclick="setTab(\'settings\')">Settings</button><button class="'+(TAB==='posts'?'on':'')+'" onclick="setTab(\'posts\')">Posts</button><button class="'+(TAB==='users'?'on':'')+'" onclick="setTab(\'users\')">Users</button><button class="'+(TAB==='broadcast'?'on':'')+'" onclick="setTab(\'broadcast\')">Broadcast</button><button onclick="logout()" style="margin-left:auto;background:#c33">Logout</button></div><div id="tab"></div>';if(TAB==='stats')tabStats();else if(TAB==='settings')tabSettings();else if(TAB==='posts')tabPosts();else if(TAB==='users')tabUsers();else if(TAB==='broadcast')tabBroadcast();}
function setTab(t){TAB=t;render();}
function logout(){fetch('/admin/logout',{method:'POST',credentials:'include'}).then(()=>location.reload());}
function field(k,label,type){type=type||'text';const v=CFG[k];if(type==='bool')return '<div><label>'+label+'</label><select data-k="'+k+'"><option value="true"'+(v?' selected':'')+'>ON</option><option value="false"'+(!v?' selected':'')+'>OFF</option></select></div>';if(type==='num')return '<div><label>'+label+'</label><input type="number" data-k="'+k+'" value="'+v+'"></div>';if(type==='color')return '<div><label>'+label+'</label><input type="color" data-k="'+k+'" value="'+v+'"></div>';if(type==='list')return '<div><label>'+label+'</label><input data-k="'+k+'" value="'+((v||[]).join(','))+'"></div>';return '<div><label>'+label+'</label><input data-k="'+k+'" value="'+esc(String(v||''))+'"></div>';}
function tabSettings(){$('#tab').innerHTML='<div class="card"><h2>Bot & Server</h2>'+field('bot_token','Bot Token')+field('webapp_url','WebApp URL')+field('admin_password','Admin Password')+field('admin_tg_ids','Admin TG IDs','list')+'</div>'
+'<div class="card"><h2>Appearance</h2>'+field('site_name','Site Name')+field('tagline','Tagline')+field('welcome_message','Welcome Message')+'<div class="row">'+field('primary_color','Primary','color')+field('bg_color','Background','color')+field('text_color','Text','color')+'</div>'+field('footer_text','Footer')+field('ads_text','Ads Text')+'</div>'
+'<div class="card"><h2>Features</h2><div class="row">'+field('enable_likes','Likes','bool')+field('enable_comments','Comments','bool')+field('enable_upload','Upload','bool')+field('enable_share','Share','bool')+'</div><div class="row">'+field('require_approval','Require Approval','bool')+'</div><div class="row">'+field('upload_limit_per_day','Upload Limit/Day','num')+field('feed_page_size','Page Size','num')+field('max_caption','Max Caption','num')+'</div></div>'
+'<button onclick="saveCfg()" style="width:100%;padding:14px;font-size:15px">Save All Settings</button>';}
async function saveCfg(){const upd={};$$('[data-k]').forEach(el=>{const k=el.dataset.k;let v=el.value;if(el.type==='number')v=Number(v);if(el.tagName==='SELECT')v=v==='true';if(k==='admin_tg_ids')v=v.split(',').map(s=>s.trim()).filter(Boolean).map(Number);upd[k]=v;});const r=await api('/admin/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(upd)});CFG=r.config;toast('Saved!');}
async function tabStats(){const s=await api('/admin/api/stats');$('#tab').innerHTML='<div class="card"><h2>Overview</h2><div><div class="stat"><div class="n">'+s.users+'</div><div class="l">Users</div></div><div class="stat"><div class="n">'+s.posts+'</div><div class="l">Posts</div></div><div class="stat"><div class="n">'+s.likes+'</div><div class="l">Likes</div></div><div class="stat"><div class="n">'+s.comments+'</div><div class="l">Comments</div></div><div class="stat"><div class="n">'+s.premium_users+'</div><div class="l">Premium</div></div><div class="stat"><div class="n">'+s.pending_posts+'</div><div class="l">Pending</div></div><div class="stat"><div class="n">'+s.banned_users+'</div><div class="l">Banned</div></div></div></div>';}
async function tabPosts(){const r=await api('/admin/api/posts?page=1&filter=all');$('#tab').innerHTML='<div class="card"><h2>Posts ('+r.posts.length+')</h2>'+r.posts.map(p=>{const m=p.file_type==='video'?'<video src="/media/'+p.file_id+'" muted></video>':'<img src="/media/'+p.file_id+'">';return '<div class="item">'+m+'<div class="info"><b>#'+p.id+'</b> '+esc(p.first_name||p.username||'?')+'<br><div class="cap">'+esc((p.caption||'(none)').slice(0,80))+'</div><small>❤ '+p.likes+' · '+(p.is_approved?'✅':'⏳')+' '+(p.is_hidden?'🚫':'')+'</small></div><div class="btns">'+(!p.is_approved?'<button onclick="pAct('+p.id+',\'approve\')">Approve</button>':'')+(p.is_hidden?'<button onclick="pAct('+p.id+',\'unhide\')">Unhide</button>':'<button class="ghost" onclick="pAct('+p.id+',\'hide\')">Hide</button>')+'<button class="danger" onclick="pAct('+p.id+',\'delete\')">Delete</button></div></div>';}).join('')+'</div>';}
async function pAct(id,a){if(a==='delete'&&!confirm('Delete #'+id+'?'))return;await api('/admin/api/posts/'+id+'/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:a})});toast('Done');tabPosts();}
async function tabUsers(){const r=await api('/admin/api/users?page=1');$('#tab').innerHTML='<div class="card"><h2>Users ('+r.users.length+')</h2>'+r.users.map(u=>{const av=u.photo_url||'https://telegram.org/img/t_logo.png';return '<div class="item"><img src="'+av+'"><div class="info"><b>'+esc(u.first_name||'')+' '+esc(u.username?'@'+u.username:'')+'</b><br><small>TG: '+u.tg_id+' '+(u.is_admin?'· 👑':'')+' '+(u.is_premium?'· ⭐':'')+' '+(u.is_banned?'· 🚫':'')+'</small></div><div class="btns">'+(u.is_banned?'<button onclick="uAct('+u.id+',\'unban\')">Unban</button>':'<button class="danger" onclick="uAct('+u.id+',\'ban\')">Ban</button>')+(u.is_premium?'<button class="ghost" onclick="uAct('+u.id+',\'remove_premium\')">-Prem</button>':'<button onclick="uAct('+u.id+',\'make_premium\')">+Prem</button>')+(u.is_admin?'<button class="ghost" onclick="uAct('+u.id+',\'remove_admin\')">-Admin</button>':'<button onclick="uAct('+u.id+',\'make_admin\')">+Admin</button>')+'</div></div>';}).join('')+'</div>';}
async function uAct(id,a){await api('/admin/api/users/'+id+'/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:a})});toast('Done');tabUsers();}
function tabBroadcast(){$('#tab').innerHTML='<div class="card"><h2>Broadcast</h2><textarea id="bt" rows="6" placeholder="Message"></textarea><button onclick="doBC()" style="width:100%">Send to All</button></div>';}
async function doBC(){const t=$('#bt').value.trim();if(!t)return;if(!confirm('Send to all?'))return;toast('Sending...');const r=await api('/admin/api/broadcast',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({text:t})});toast('Sent: '+r.sent+', Failed: '+r.failed);}
boot();
</script></body></html>"""

# ============================================================
# ROUTES
# ============================================================
@app.route("/")
def root():
    return Response(APP_HTML, mimetype="text/html")

@app.route("/admin")
def admin_page():
    return Response(ADMIN_HTML, mimetype="text/html")

@app.route("/admin/login", methods=["POST"])
def admin_login():
    if (request.get_json() or {}).get("password") == CFG["admin_password"]:
        tok = hashlib.sha256((CFG["admin_password"] + CFG["bot_token"]).encode()).hexdigest()
        r = make_response(jsonify(ok=True))
        r.set_cookie("asess", tok, httponly=True, max_age=86400*7)
        return r
    return jsonify(error="Wrong"), 401

@app.route("/admin/logout", methods=["POST"])
def admin_logout():
    r = make_response(jsonify(ok=True))
    r.delete_cookie("asess")
    return r

@app.route("/admin/api/settings")
def admin_get_settings():
    if not admin_ok():
        return jsonify(error="unauth"), 401
    return jsonify(CFG)

@app.route("/admin/api/settings", methods=["POST"])
def admin_set_settings():
    if not admin_ok():
        return jsonify(error="unauth"), 401
    for k, v in (request.get_json() or {}).items():
        if k in DEFAULT:
            CFG[k] = v
    save_cfg(CFG)
    return jsonify(ok=True, config=CFG)

@app.route("/admin/api/stats")
def admin_stats():
    if not admin_ok():
        return jsonify(error="unauth"), 401
    conn = db(); c = conn.cursor()
    def q(s):
        c.execute(s); return c.fetchone()[0]
    s = {
        "users": q("SELECT COUNT(*) FROM users"),
        "posts": q("SELECT COUNT(*) FROM posts"),
        "likes": q("SELECT COUNT(*) FROM likes"),
        "comments": q("SELECT COUNT(*) FROM comments"),
        "premium_users": q("SELECT COUNT(*) FROM users WHERE is_premium=1"),
        "banned_users": q("SELECT COUNT(*) FROM users WHERE is_banned=1"),
        "pending_posts": q("SELECT COUNT(*) FROM posts WHERE is_approved=0"),
    }
    conn.close()
    return jsonify(s)

@app.route("/admin/api/posts")
def admin_posts():
    if not admin_ok():
        return jsonify(error="unauth"), 401
    page = int(request.args.get("page", 1))
    f = request.args.get("filter", "all")
    where = ""
    if f == "pending":
        where = "WHERE p.is_approved=0"
    elif f == "hidden":
        where = "WHERE p.is_hidden=1"
    elif f == "approved":
        where = "WHERE p.is_approved=1 AND p.is_hidden=0"
    conn = db(); c = conn.cursor()
    c.execute("SELECT p.*, u.username, u.first_name FROM posts p "
              "JOIN users u ON p.user_id=u.id " + where +
              " ORDER BY p.id DESC LIMIT 20 OFFSET ?", ((page-1)*20,))
    posts = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(posts=posts, page=page)

@app.route("/admin/api/posts/<int:pid>/action", methods=["POST"])
def admin_post_action(pid):
    if not admin_ok():
        return jsonify(error="unauth"), 401
    a = (request.get_json() or {}).get("action")
    conn = db(); c = conn.cursor()
    if a == "approve":
        c.execute("UPDATE posts SET is_approved=1 WHERE id=?", (pid,))
    elif a == "hide":
        c.execute("UPDATE posts SET is_hidden=1 WHERE id=?", (pid,))
    elif a == "unhide":
        c.execute("UPDATE posts SET is_hidden=0 WHERE id=?", (pid,))
    elif a == "delete":
        c.execute("DELETE FROM posts WHERE id=?", (pid,))
        c.execute("DELETE FROM likes WHERE post_id=?", (pid,))
        c.execute("DELETE FROM comments WHERE post_id=?", (pid,))
    conn.commit(); conn.close()
    return jsonify(ok=True)

@app.route("/admin/api/users")
def admin_users():
    if not admin_ok():
        return jsonify(error="unauth"), 401
    page = int(request.args.get("page", 1))
    conn = db(); c = conn.cursor()
    c.execute("SELECT * FROM users ORDER BY id DESC LIMIT 20 OFFSET ?", ((page-1)*20,))
    users = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(users=users, page=page)

@app.route("/admin/api/users/<int:uid>/action", methods=["POST"])
def admin_user_action(uid):
    if not admin_ok():
        return jsonify(error="unauth"), 401
    a = (request.get_json() or {}).get("action")
    conn = db(); c = conn.cursor()
    if a == "ban":
        c.execute("UPDATE users SET is_banned=1 WHERE id=?", (uid,))
    elif a == "unban":
        c.execute("UPDATE users SET is_banned=0 WHERE id=?", (uid,))
    elif a == "make_premium":
        c.execute("UPDATE users SET is_premium=1 WHERE id=?", (uid,))
    elif a == "remove_premium":
        c.execute("UPDATE users SET is_premium=0 WHERE id=?", (uid,))
    elif a == "make_admin":
        c.execute("SELECT tg_id FROM users WHERE id=?", (uid,))
        r = c.fetchone()
        if r:
            ids = set(CFG.get("admin_tg_ids", []))
            ids.add(r["tg_id"])
            CFG["admin_tg_ids"] = list(ids)
            save_cfg(CFG)
            c.execute("UPDATE users SET is_admin=1 WHERE id=?", (uid,))
    elif a == "remove_admin":
        c.execute("SELECT tg_id FROM users WHERE id=?", (uid,))
        r = c.fetchone()
        if r:
            ids = set(CFG.get("admin_tg_ids", []))
            ids.discard(r["tg_id"])
            CFG["admin_tg_ids"] = list(ids)
            save_cfg(CFG)
            c.execute("UPDATE users SET is_admin=0 WHERE id=?", (uid,))
    conn.commit(); conn.close()
    return jsonify(ok=True)

@app.route("/admin/api/broadcast", methods=["POST"])
def admin_broadcast():
    if not admin_ok():
        return jsonify(error="unauth"), 401
    text = (request.get_json() or {}).get("text", "").strip()
    if not text:
        return jsonify(error="empty"), 400
    conn = db(); c = conn.cursor()
    c.execute("SELECT tg_id FROM users WHERE is_banned=0")
    ids = [r["tg_id"] for r in c.fetchall()]
    conn.close()
    sent = failed = 0
    for uid in ids:
        r = tg("sendMessage", chat_id=uid, text=text, parse_mode="HTML")
        if r.get("ok"):
            sent += 1
        else:
            failed += 1
        time.sleep(0.05)
    return jsonify(sent=sent, failed=failed)

# ============================================================
# MINI APP APIs
# ============================================================
@app.route("/api/config")
def api_config():
    keys = ["site_name","tagline","primary_color","bg_color","text_color",
            "enable_likes","enable_comments","enable_upload","enable_share",
            "max_caption","feed_page_size","footer_text","ads_text",
            "webapp_url","show_premium_badge"]
    return jsonify({k: CFG.get(k) for k in keys})

@app.route("/api/me")
def api_me():
    u = get_user()
    if not u:
        return jsonify(error="unauth"), 401
    return jsonify(u)

@app.route("/api/feed")
def api_feed():
    u = get_user()
    if not u:
        return jsonify(error="unauth"), 401
    page = int(request.args.get("page", 1))
    size = CFG["feed_page_size"]
    conn = db(); c = conn.cursor()
    c.execute("SELECT p.*, u.username, u.first_name, u.photo_url, u.is_premium "
              "FROM posts p JOIN users u ON p.user_id=u.id "
              "WHERE p.is_approved=1 AND p.is_hidden=0 "
              "ORDER BY p.id DESC LIMIT ? OFFSET ?",
              (size, (page-1)*size))
    posts = [dict(r) for r in c.fetchall()]
    for p in posts:
        c.execute("SELECT 1 FROM likes WHERE post_id=? AND user_id=?", (p["id"], u["id"]))
        p["liked"] = c.fetchone() is not None
        c.execute("SELECT COUNT(*) n FROM comments WHERE post_id=?", (p["id"],))
        p["comment_count"] = c.fetchone()["n"]
    conn.close()
    return jsonify(posts=posts, page=page)

@app.route("/api/like/<int:pid>", methods=["POST"])
def api_like(pid):
    u = get_user()
    if not u:
        return jsonify(error="unauth"), 401
    if not CFG["enable_likes"]:
        return jsonify(error="off"), 403
    conn = db(); c = conn.cursor()
    c.execute("SELECT 1 FROM likes WHERE post_id=? AND user_id=?", (pid, u["id"]))
    if c.fetchone():
        c.execute("DELETE FROM likes WHERE post_id=? AND user_id=?", (pid, u["id"]))
        c.execute("UPDATE posts SET likes=MAX(likes-1,0) WHERE id=?", (pid,))
        liked = False
    else:
        c.execute("INSERT INTO likes(post_id,user_id,created_at) VALUES(?,?,?)",
                  (pid, u["id"], datetime.utcnow().isoformat()))
        c.execute("UPDATE posts SET likes=likes+1 WHERE id=?", (pid,))
        liked = True
    conn.commit()
    c.execute("SELECT likes FROM posts WHERE id=?", (pid,))
    n = c.fetchone()["likes"]
    conn.close()
    return jsonify(liked=liked, likes=n)

@app.route("/api/comment/<int:pid>", methods=["POST"])
def api_comment(pid):
    u = get_user()
    if not u:
        return jsonify(error="unauth"), 401
    if not CFG["enable_comments"]:
        return jsonify(error="off"), 403
    text = (request.form.get("text") or "").strip()[:CFG["max_caption"]]
    if not text:
        return jsonify(error="empty"), 400
    conn = db(); c = conn.cursor()
    c.execute("INSERT INTO comments(post_id,user_id,text,created_at) VALUES(?,?,?,?)",
              (pid, u["id"], text, datetime.utcnow().isoformat()))
    conn.commit(); conn.close()
    return jsonify(ok=True)

@app.route("/api/comments/<int:pid>")
def api_comments(pid):
    u = get_user()
    if not u:
        return jsonify(error="unauth"), 401
    conn = db(); c = conn.cursor()
    c.execute("SELECT cm.*, u.username, u.first_name, u.photo_url "
              "FROM comments cm JOIN users u ON cm.user_id=u.id "
              "WHERE cm.post_id=? ORDER BY cm.id DESC LIMIT 50", (pid,))
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(comments=rows)

@app.route("/api/profile/<int:tid>")
def api_profile(tid):
    u = get_user()
    if not u:
        return jsonify(error="unauth"), 401
    conn = db(); c = conn.cursor()
    c.execute("SELECT * FROM users WHERE tg_id=?", (tid,))
    t = c.fetchone()
    if not t:
        conn.close()
        return jsonify(error="notfound"), 404
    c.execute("SELECT COUNT(*) n FROM posts WHERE user_id=? AND is_hidden=0", (t["id"],))
    pc = c.fetchone()["n"]
    c.execute("SELECT COALESCE(SUM(likes),0) s FROM posts WHERE user_id=? AND is_hidden=0", (t["id"],))
    tl = c.fetchone()["s"]
    c.execute("SELECT COUNT(*) n FROM comments cm JOIN posts p ON cm.post_id=p.id WHERE p.user_id=? AND p.is_hidden=0", (t["id"],))
    tc = c.fetchone()["n"]
    c.execute("SELECT * FROM posts WHERE user_id=? AND is_hidden=0 ORDER BY id DESC LIMIT 30", (t["id"],))
    posts = [dict(r) for r in c.fetchall()]
    conn.close()
    return jsonify(user=dict(t), post_count=pc, total_likes=tl, total_comments=tc, posts=posts)

@app.route("/media/<file_id>")
def media(file_id):
    url = tg_file(file_id)
    if not url:
        return "Not found", 404
    r = requests.get(url, stream=True, timeout=60)
    ct = r.headers.get("Content-Type", "image/jpeg")
    return Response(r.content, mimetype=ct, headers={"Cache-Control": "public, max-age=86400"})

# ============================================================
# BOT
# ============================================================
def handle_update(up):
    msg = up.get("message")
    if not msg:
        return
    chat = msg["chat"]["id"]
    user = msg.get("from", {})
    tid = user.get("id")
    text = msg.get("text", "")
    if not tid:
        return

    if "photo" in msg or "video" in msg:
        ftype = "photo" if "photo" in msg else "video"
        fid = msg["photo"][-1]["file_id"] if ftype == "photo" else msg["video"]["file_id"]
        cap = msg.get("caption", "")
        row = ensure_user(tid, user)
        if not row:
            tg("sendMessage", chat_id=chat, text="You are banned.")
            return
        today = date.today().isoformat()
        cnt = row["upload_count_today"] if row["last_upload_date"] == today else 0
        if not row["is_premium"] and cnt >= CFG["upload_limit_per_day"]:
            tg("sendMessage", chat_id=chat, text="Daily limit reached")
            return
        approved = 0 if CFG["require_approval"] else 1
        conn = db(); c = conn.cursor()
        c.execute("INSERT INTO posts(user_id,file_id,file_type,caption,created_at,is_approved) "
                  "VALUES(?,?,?,?,?,?)",
                  (row["id"], fid, ftype, cap[:CFG["max_caption"]],
                   datetime.utcnow().isoformat(), approved))
        c.execute("UPDATE users SET upload_count_today=?, last_upload_date=? WHERE id=?",
                  (cnt+1, today, row["id"]))
        conn.commit(); conn.close()
        if approved:
            kb = {"inline_keyboard": [[{"text": "Open SnapFeed", "web_app": {"url": CFG["webapp_url"]}}]]}
            tg("sendMessage", chat_id=chat, text="Uploaded!", reply_markup=json.dumps(kb))
        else:
            tg("sendMessage", chat_id=chat, text="Submitted for review")
        return

    if text.startswith("/start"):
        ensure_user(tid, user)
        name = user.get("first_name", "there")
        kb = {"inline_keyboard": [[{"text": "Open SnapFeed", "web_app": {"url": CFG["webapp_url"]}}]]}
        tg("sendMessage", chat_id=chat,
           text=CFG["welcome_message"] + "\n\nHi " + name + "!\n\nSend me a photo/video to upload.",
           reply_markup=json.dumps(kb))
        return

    if text.startswith("/help"):
        tg("sendMessage", chat_id=chat,
           text="Send photo/video to upload.\nOpen Mini App to browse.")
        return

    if text.startswith("/admin"):
        tg("sendMessage", chat_id=chat, text="Admin: " + CFG["webapp_url"] + "/admin")

def bot_loop():
    if not CFG["bot_token"] or "PASTE" in CFG["bot_token"]:
        print("[BOT] No token")
        return
    print("[BOT] Polling started")
    offset = 0
    while True:
        try:
            r = requests.get("https://api.telegram.org/bot" + CFG["bot_token"] + "/getUpdates",
                             params={"offset": offset, "timeout": 30}, timeout=40)
            data = r.json()
            if not data.get("ok"):
                time.sleep(5)
                continue
            for up in data.get("result", []):
                offset = up["update_id"] + 1
                try:
                    handle_update(up)
                except Exception as e:
                    print("[BOT]", e)
        except Exception as e:
            print("[BOT]", e)
            time.sleep(5)

# ============================================================
# START
# ============================================================
threading.Thread(target=bot_loop, daemon=True).start()

if __name__ == "__main__":
    print("SnapFeed starting on port " + str(PORT))
    app.run(host="0.0.0.0", port=PORT, threaded=True, debug=False)
