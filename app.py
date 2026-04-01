import os, json, re, math, shutil, warnings, html, ast, operator, io, time, tempfile, base64
from urllib.parse import quote
import pandas as pd
import streamlit as st
import google.generativeai as genai
import streamlit.components.v1 as components
from datetime import datetime, timedelta
import hashlib

os.environ['STREAMLIT_PYARROW'] = 'false'
warnings.filterwarnings("ignore")

CONFIG_FILE  = 'config.json'
MASTER_FILE  = 'master_data.xlsx'
LEDGER_FILE  = 'ledger_data.xlsx'
TRASH_FILE   = 'trash_data.xlsx'
PURCHASE_FILE = 'purchase_data.xlsx'
PAYABLE_FILE = 'payable_data.xlsx'
MEMORY_FILE  = 'agent_memory.json'
CHAT_MEMORY_FILE = 'agent_chat_memory.json'
AUDIT_FILE   = 'audit_log.json'
USERS_FILE   = 'users.json'
SESSION_IDLE_SEC = 30 * 60  # ၃၀ မိနစ် အလုပ်မလုပ်ရင် ထွက်
if os.path.exists('/sdcard/Download'):
    DOWNLOAD_DIR = '/sdcard/Download/'
else:
    DOWNLOAD_DIR = os.path.join(os.path.expanduser('~'), 'Downloads')

# ══════════════════════════════════════════════════════════════════
#  DB / CONFIG
# ══════════════════════════════════════════════════════════════════
def init_db():
    if not os.path.exists(MASTER_FILE):
        with pd.ExcelWriter(MASTER_FILE, engine='openpyxl') as w:
            pd.DataFrame(columns=["CustomerName"]).to_excel(w, sheet_name='Customers', index=False)
            pd.DataFrame(columns=["Item", "Price"]).to_excel(w, sheet_name='Menu', index=False)
            pd.DataFrame(columns=["CreditorName"]).to_excel(w, sheet_name='Creditors', index=False)
            pd.DataFrame(columns=["ItemName", "RefPrice"]).to_excel(w, sheet_name='PurchaseCatalog', index=False)
    else:
        try:
            existing_sheets = pd.ExcelFile(MASTER_FILE).sheet_names
            if 'Menu' not in existing_sheets:
                customers_df = pd.read_excel(MASTER_FILE, sheet_name='Customers') if 'Customers' in existing_sheets else pd.DataFrame(columns=["CustomerName"])
                with pd.ExcelWriter(MASTER_FILE, engine='openpyxl') as w:
                    customers_df.to_excel(w, sheet_name='Customers', index=False)
                    pd.DataFrame(columns=["Item", "Price"]).to_excel(w, sheet_name='Menu', index=False)
        except:
            pass

    if os.path.exists(MASTER_FILE):
        try:
            _sheets = pd.read_excel(MASTER_FILE, sheet_name=None)
            _chg = False
            if "Creditors" not in _sheets:
                _sheets["Creditors"] = pd.DataFrame(columns=["CreditorName"])
                _chg = True
            if "PurchaseCatalog" not in _sheets:
                _sheets["PurchaseCatalog"] = pd.DataFrame(columns=["ItemName", "RefPrice"])
                _chg = True
            if _chg:
                with pd.ExcelWriter(MASTER_FILE, engine="openpyxl") as w:
                    for _sn, _d in _sheets.items():
                        _d.to_excel(w, sheet_name=_sn, index=False)
        except Exception:
            pass

    for f, cols in [(LEDGER_FILE, ["Date","Name","Description","Amount","Status","SettledAt","SettledBy"]),
                    (TRASH_FILE,  ["Date","Name","Description","Amount","Status","DeletedAt"]),
                    (PURCHASE_FILE, ["Date", "ItemName", "Price"]),
                    (PAYABLE_FILE, ["Date", "CreditorName", "Description", "Amount", "Status", "SettledAt", "SettledBy"])]:
        if not os.path.exists(f):
            pd.DataFrame(columns=cols).to_excel(f, index=False)

    if os.path.exists(LEDGER_FILE):
        try:
            _ldf = pd.read_excel(LEDGER_FILE)
            w = False
            if "SettledAt" not in _ldf.columns:
                _ldf["SettledAt"] = pd.NaT
                w = True
            if "SettledBy" not in _ldf.columns:
                _ldf["SettledBy"] = ""
                w = True
            if w:
                _ldf.to_excel(LEDGER_FILE, index=False)
                sync_to_download(LEDGER_FILE)
        except Exception:
            pass

    if os.path.exists(PAYABLE_FILE):
        try:
            _pdf = pd.read_excel(PAYABLE_FILE)
            pw = False
            if "SettledAt" not in _pdf.columns:
                _pdf["SettledAt"] = pd.NaT
                pw = True
            if "SettledBy" not in _pdf.columns:
                _pdf["SettledBy"] = ""
                pw = True
            if "Status" not in _pdf.columns:
                _pdf["Status"] = "Unpaid"
                pw = True
            if pw:
                _pdf.to_excel(PAYABLE_FILE, index=False)
                sync_to_download(PAYABLE_FILE)
        except Exception:
            pass

    if not os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump({"api_key":"","model_name":"gemini-2.0-flash","skip_login": True}, f, ensure_ascii=False)
    else:
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
        w = False
        if cfg.get('model_name', '').startswith('google/'):
            cfg['model_name'] = cfg['model_name'].replace('google/','',1)
            w = True
        if 'skip_login' not in cfg:
            cfg['skip_login'] = True
            w = True
        if w:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f: json.dump(cfg, f, ensure_ascii=False)

    if not os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, 'w', encoding='utf-8') as f: json.dump([], f)
    if not os.path.exists(CHAT_MEMORY_FILE):
        with open(CHAT_MEMORY_FILE, 'w', encoding='utf-8') as f: json.dump([], f)
    if not os.path.exists(AUDIT_FILE):
        with open(AUDIT_FILE, 'w', encoding='utf-8') as f: json.dump([], f)

    maybe_daily_backup()

def init_users():
    default_users = {
        "admin": {
            "password": hashlib.sha256("admin123".encode()).hexdigest(),
            "role": "admin",
            "name": "စီမံခန့်ခွဲသူ"
        },
        "cashier1": {
            "password": hashlib.sha256("cash123".encode()).hexdigest(),
            "role": "cashier",
            "name": "ငွေကိုင် ၁"
        },
    }

    def write_default_users():
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(default_users, f, ensure_ascii=False)

    if not os.path.exists(USERS_FILE):
        write_default_users()
        return

    try:
        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            users = json.load(f)
        if not isinstance(users, dict) or not users:
            raise ValueError("empty or invalid users")
    except (json.JSONDecodeError, ValueError, OSError):
        bak = USERS_FILE + f".bad.{datetime.now().strftime('%Y%m%d%H%M%S')}"
        try:
            shutil.move(USERS_FILE, bak)
        except OSError:
            try:
                os.remove(USERS_FILE)
            except OSError:
                pass
        write_default_users()

def check_login(username, password):
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        users = json.load(f)
    if username in users:
        hashed = hashlib.sha256(password.encode()).hexdigest()
        if users[username]['password'] == hashed:
            return users[username]
    return None

def default_auto_login_user():
    """skip_login ဖွင့်ထားချိန် — စကားဝှက်မထည့်ဘဲ Admin အနေနဲ့ တန်းဝင်ရန်"""
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        users = json.load(f)
    if not users:
        return {"role": "admin", "name": "စီမံခန့်ခွဲသူ"}
    if "admin" in users:
        u = users["admin"]
        return {"role": u["role"], "name": u["name"]}
    for _uid, u in users.items():
        if u.get("role") == "admin":
            return {"role": u["role"], "name": u["name"]}
    uid, u = next(iter(users.items()))
    return {"role": u.get("role", "cashier"), "name": u.get("name", uid)}

def add_user(username, password, role, name):
    with open(USERS_FILE, 'r', encoding='utf-8') as f:
        users = json.load(f)
    if username not in users:
        users[username] = {
            "password": hashlib.sha256(password.encode()).hexdigest(),
            "role": role,
            "name": name
        }
        with open(USERS_FILE, 'w', encoding='utf-8') as f:
            json.dump(users, f, ensure_ascii=False)
        return True
    return False

def get_config():
    """config.json + Streamlit Secrets (Cloud မှာ GEMINI_API_KEY စသည်) ပေါင်းစပ်၊ Secrets က အရေးပါတဲ့ တန်ဖိုးတွေကို ဦးစားပေး"""
    cfg = {"api_key": "", "model_name": "gemini-2.0-flash", "skip_login": True}
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg.update(json.load(f))
        except Exception:
            pass
    try:
        sec = st.secrets
        if "GEMINI_API_KEY" in sec:
            cfg["api_key"] = str(sec["GEMINI_API_KEY"])
        elif "api_key" in sec:
            cfg["api_key"] = str(sec["api_key"])
        if "GEMINI_MODEL" in sec:
            cfg["model_name"] = str(sec["GEMINI_MODEL"])
        elif "model_name" in sec:
            cfg["model_name"] = str(sec["model_name"])
        if "skip_login" in sec:
            sl = sec["skip_login"]
            if isinstance(sl, str):
                cfg["skip_login"] = sl.lower() in ("1", "true", "yes")
            else:
                cfg["skip_login"] = bool(sl)
    except Exception:
        pass
    return cfg

def save_config(api_key, model_name, skip_login=None):
    model_name = model_name.replace('google/','',1) if model_name.startswith('google/') else model_name
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                cfg = json.load(f)
        except Exception:
            cfg = {}
    else:
        cfg = {}
    cfg['api_key'] = api_key
    cfg['model_name'] = model_name
    if skip_login is not None:
        cfg['skip_login'] = bool(skip_login)
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False)

def sync_to_download(file):
    if os.path.exists(DOWNLOAD_DIR):
        try: shutil.copy(file, os.path.join(DOWNLOAD_DIR, os.path.basename(file)))
        except: pass

def write_master_sheet(sheet_name, df):
    try:    sheets = pd.read_excel(MASTER_FILE, sheet_name=None)
    except: sheets = {}
    sheets[sheet_name] = df
    with pd.ExcelWriter(MASTER_FILE, engine='openpyxl') as w:
        for s, d in sheets.items(): d.to_excel(w, sheet_name=s, index=False)

def read_master_sheet_safe(sheet_name, columns):
    try:
        xl = pd.ExcelFile(MASTER_FILE)
        if sheet_name not in xl.sheet_names:
            return pd.DataFrame(columns=columns)
        df = pd.read_excel(MASTER_FILE, sheet_name=sheet_name)
        for c in columns:
            if c not in df.columns:
                df[c] = 0.0 if c == "RefPrice" else ""
        return df
    except Exception:
        return pd.DataFrame(columns=columns)

_PUR_CUSTOM = "— ကိုယ်တိုင် ရေးမည် —"
_PAY_CRED_CUSTOM = "— ကိုယ်တိုင် ရေးမည် —"

# ══════════════════════════════════════════════════════════════════
#  LONG-TERM MEMORY
# ══════════════════════════════════════════════════════════════════
def load_memory():
    try:
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f: return json.load(f)
    except: return []

def save_memory(mem: list):
    with open(MEMORY_FILE, 'w', encoding='utf-8') as f: json.dump(mem[-40:], f, ensure_ascii=False)

def add_memory(role: str, text: str):
    mem = load_memory()
    mem.append({"role": role, "text": text, "ts": datetime.now().strftime("%Y-%m-%d %H:%M")})
    save_memory(mem)

def memory_context() -> str:
    mem = load_memory()
    if not mem: return ""
    lines = [f"[{m['ts']}] {m['role']}: {m['text']}" for m in mem[-10:]]
    return "=== ယခင် လုပ်ငန်းမှတ်တမ်း (Agent memory) ===\n" + "\n".join(lines) + "\n"

def load_chat_memory():
    try:
        with open(CHAT_MEMORY_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return []

def append_chat_memory(user_txt: str, bot_txt: str):
    m = load_chat_memory()
    m.append({
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "user": (user_txt or "")[:2000],
        "bot": (bot_txt or "")[:2000],
    })
    with open(CHAT_MEMORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(m[-80:], f, ensure_ascii=False)

def clear_chat_memory_file():
    with open(CHAT_MEMORY_FILE, 'w', encoding='utf-8') as f:
        json.dump([], f)

def chat_context() -> str:
    m = load_chat_memory()
    if not m:
        return ""
    lines = []
    for x in m[-8:]:
        u = str(x.get("user", ""))[:160]
        b = str(x.get("bot", ""))[:160]
        lines.append(f"[{x.get('ts','')}] User: {u} → Bot: {b}")
    return "=== လတ်တလော Agent စကားပြောမှတ်တမ်း ===\n" + "\n".join(lines) + "\n"

def _audit_user_label():
    try:
        u = st.session_state.get("user") or {}
        return (u.get("name") or u.get("role") or "—").strip() or "—"
    except Exception:
        return "—"

def append_audit(action: str, detail: str):
    try:
        ent = {
            "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "user": _audit_user_label(),
            "action": (action or "")[:120],
            "detail": (detail or "")[:800],
        }
        log = []
        if os.path.exists(AUDIT_FILE):
            try:
                with open(AUDIT_FILE, 'r', encoding='utf-8') as f:
                    log = json.load(f)
            except Exception:
                log = []
        if not isinstance(log, list):
            log = []
        log.append(ent)
        with open(AUDIT_FILE, 'w', encoding='utf-8') as f:
            json.dump(log[-400:], f, ensure_ascii=False)
    except Exception:
        pass

def load_audit_log():
    try:
        with open(AUDIT_FILE, 'r', encoding='utf-8') as f:
            x = json.load(f)
        return x if isinstance(x, list) else []
    except Exception:
        return []

def _resolve_data_path(fn: str) -> str:
    """app.py ဖိုလ်ဒါ (သို့) လက်ရှိ cwd တွင် ရှာသည်"""
    b = os.path.dirname(os.path.abspath(__file__))
    p1 = os.path.join(b, fn)
    if os.path.exists(p1):
        return p1
    if os.path.exists(fn):
        return os.path.abspath(fn)
    return p1

def maybe_daily_backup():
    """နေ့စဉ် တစ်ကြိမ် အရေးပါဖိုင်များ backups/YYYY-MM-DD/ သို့ ကော်ပီ"""
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        base = os.path.dirname(os.path.abspath(__file__))
        bdir = os.path.join(base, "backups", today)
        sentinel = os.path.join(bdir, ".ok")
        if os.path.exists(sentinel):
            return
        os.makedirs(bdir, exist_ok=True)
        for fn in (
            LEDGER_FILE, MASTER_FILE, TRASH_FILE, PURCHASE_FILE, PAYABLE_FILE,
            USERS_FILE, MEMORY_FILE, CHAT_MEMORY_FILE, AUDIT_FILE,
        ):
            fp = _resolve_data_path(fn)
            if os.path.exists(fp):
                shutil.copy2(fp, os.path.join(bdir, os.path.basename(fn)))
        with open(sentinel, "w", encoding="utf-8") as f:
            f.write("ok")
    except Exception:
        pass

# ══════════════════════════════════════════════════════════════════
#  TOOLS
# ══════════════════════════════════════════════════════════════════
TOOL_REGISTRY = {}

def tool(name):
    def decorator(fn):
        TOOL_REGISTRY[name] = fn
        return fn
    return decorator

def _agent_actor_label():
    """Agent က ငွေရှင်း/အကြွေးရှင်းမှတ်တမ်းမှာ သုံးမည့် နာမည်"""
    try:
        u = st.session_state.get("user") or {}
        nm = (u.get("name") or "").strip()
        if nm:
            return f"Agent · {nm}"
    except Exception:
        pass
    return "Agent"

def _require_admin_tool(tool_label: str):
    """ငွေကိုင် မဟုတ်ရင် None၊ ငွေကိုင် ဖြစ်ရင် မြန်မာ error စာသား"""
    try:
        if (st.session_state.get("user") or {}).get("role") == "admin":
            return None
    except Exception:
        return None
    return f"⚠️ '{tool_label}' ကို Agent မှ **စီမံခန့်ခွဲသူ** သာလုပ်ခွင့်ရှိပါသည်။"

def _safe_calculate_ast(expr: str):
    """+ - * / ** %၊ ခေါင်းစဉ်ကွင်းများ၊ sqrt/ceil/floor စသည် math တစ်ချို့သာ — eval မသုံးပါ"""
    _bin = {
        ast.Add: operator.add,
        ast.Sub: operator.sub,
        ast.Mult: operator.mul,
        ast.Div: operator.truediv,
        ast.Pow: operator.pow,
        ast.Mod: operator.mod,
    }
    _un = {ast.USub: operator.neg, ast.UAdd: operator.pos}
    _fn = {
        "sqrt": math.sqrt,
        "ceil": math.ceil,
        "floor": math.floor,
        "fabs": math.fabs,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "log": math.log,
        "log10": math.log10,
        "exp": math.exp,
        "degrees": math.degrees,
        "radians": math.radians,
    }
    _names = {"pi": math.pi, "e": math.e, "tau": getattr(math, "tau", 2 * math.pi)}

    def _eval(n):
        if isinstance(n, ast.Expression):
            return _eval(n.body)
        if isinstance(n, ast.Constant):
            if isinstance(n.value, (int, float)) and not isinstance(n.value, bool):
                return float(n.value)
            raise ValueError("ဂဏန်းမဟုတ်သော တန်ဖိုး")
        if isinstance(n, ast.UnaryOp) and type(n.op) in _un:
            return _un[type(n.op)](_eval(n.operand))
        if isinstance(n, ast.BinOp) and type(n.op) in _bin:
            return _bin[type(n.op)](_eval(n.left), _eval(n.right))
        if isinstance(n, ast.Call):
            if isinstance(n.func, ast.Name) and n.func.id in _fn:
                args = [_eval(a) for a in n.args]
                return float(_fn[n.func.id](*args))
            raise ValueError(f"ခွင့်မပြုသော ဖန်ရှင်: {getattr(n.func, 'id', '?')}")
        if isinstance(n, ast.Name):
            if n.id in _names:
                return float(_names[n.id])
            raise ValueError(f"မသိသော အမည်: {n.id}")
        raise ValueError("ခွင့်မပြုသော ဖော်မြူလာ")

    tree = ast.parse(expr.strip(), mode="eval")
    return _eval(tree)

@tool("calculate")
def tool_calculate(expression: str) -> str:
    try:
        r = _safe_calculate_ast(expression)
        if isinstance(r, float) and not math.isnan(r) and abs(r - int(r)) < 1e-9:
            return _fmt_int_commas(int(r))
        s = f"{float(r):,.6f}".rstrip("0").rstrip(".")
        return s
    except Exception as e:
        return f"ERROR: {e}"

@tool("get_ledger_summary")
def tool_ledger_summary(name: str = "") -> str:
    df = pd.read_excel(LEDGER_FILE)
    df = df[df['Status'] == 'Unpaid']
    if name:
        df = df[df["Name"].astype(str).str.contains(name, case=False, na=False, regex=False)]
    if df.empty:
        return "မရှင်းရသေးသော စာရင်း မရှိပါ။" if name else "စာရင်း လုံးဝ မရှိပါ။"
    lines = []
    for n, grp in df.groupby('Name'):
        total = grp['Amount'].sum()
        lines.append(f"{n}: {total:,.0f} Ks ({len(grp)} မှာယူမှု)")
    return "\n".join(lines)

@tool("get_customer_detail")
def tool_customer_detail(name: str) -> str:
    df = pd.read_excel(LEDGER_FILE)
    rows = df[
        (df["Name"].astype(str).str.contains(name, case=False, na=False, regex=False))
        & (df["Status"] == "Unpaid")
    ]
    if rows.empty: return f"{name} ၏ မရှင်းရသောစာရင်း မရှိပါ။"
    out = []
    for _, r in rows.iterrows():
        out.append(f"  {r['Date']} | {r['Description']} | {r['Amount']:,.0f} Ks")
    total = rows['Amount'].sum()
    out.append(f"  ── စုစုပေါင်း: {total:,.0f} Ks")
    return "\n".join(out)

@tool("add_order")
def tool_add_order(name: str, food: str, qty: int, price: float, date=None) -> str:
    amount = qty * price
    save_to_ledger(name, f"{food} ({qty})", amount, date=date)
    return f"✅ {name} — {food} × {qty} = {amount:,.0f} Ks သွင်းပြီးပါပြီ။"

@tool("settle_bill")
def tool_settle_bill(name: str) -> str:
    msg = _require_admin_tool("settle_bill")
    if msg:
        return msg
    ok = clear_customer_bill(name, settled_by=_agent_actor_label())
    return f"✅ {name} ၏ ငွေရှင်းပြီးပါပြီ။" if ok else f"⚠️ {name} ၏ မရှင်းရသောစာရင်း မရှိပါ။"

@tool("get_menu")
def tool_get_menu(_: str = "") -> str:
    try:
        df = pd.read_excel(MASTER_FILE, sheet_name='Menu')
        if df.empty: return "Menu မရှိသေးပါ။"
        return "\n".join(f"  {r['Item']}: {r['Price']:,.0f} Ks" for _, r in df.iterrows())
    except:
        return "Menu စာရင်း ဖတ်လို့မရပါ။"

@tool("get_customers")
def tool_get_customers(_: str = "") -> str:
    df = pd.read_excel(MASTER_FILE, sheet_name='Customers')
    if df.empty: return "Customer မရှိသေးပါ။"
    return ", ".join(df['CustomerName'].tolist())

@tool("lookup_menu_price")
def tool_lookup_menu_price(query: str) -> str:
    """Menu ထဲက အစားအစာနှင့် ဈေးကို ရှာပေးသည် (စာကြောင်းအစိတ်အပိုင်း ချိန်ဆိုင်)"""
    q = (query or "").strip()
    if not q:
        return "အစားအစာ အမည် (သို့) စာကြောင်းအပိုင်း ထည့်ပါ။"
    try:
        df = pd.read_excel(MASTER_FILE, sheet_name="Menu")
    except Exception:
        return "Menu ဖတ်မရပါ။"
    if df.empty:
        return "Menu ဗလာ။"
    m = df[df["Item"].astype(str).str.contains(q, case=False, na=False)]
    if m.empty:
        return f"\"{q}\" နှင့် ကိုက်ညီသော menu မတွေ့ပါ။ get_menu ဖြင့် စာရင်းကြည့်ပါ။"
    lines = [f"  {r['Item']}: {float(r['Price']):,.0f} Ks" for _, r in m.iterrows()]
    return "\n".join(lines[:15]) + ("\n  … (ထပ်မံပြသရန် ရှာစာကို တိတိထည့်ပါ)" if len(m) > 15 else "")

@tool("get_today_unpaid")
def tool_get_today_unpaid(_: str = "") -> str:
    """ယနေ့ မရှင်းရသေးသော မှာယူမှုများ — ဖောက်သည်အလိုက် စုစုပေါင်း"""
    today = datetime.now().strftime("%Y-%m-%d")
    df = _ledger_read()
    dcol = pd.to_datetime(df["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    sub = df[(dcol == today) & (df["Status"].astype(str).str.strip() == "Unpaid")]
    if sub.empty:
        return "ယနေ့ မရှင်းရသေးသော မှာယူမှု မရှိပါ။"
    lines = []
    for n, grp in sub.groupby("Name", sort=False):
        lines.append(f"  {n}: {float(grp['Amount'].sum()):,.0f} Ks ({len(grp)} ကြောင်း)")
    lines.append(f"  ── ယနေ့ စုစုပေါင်း: {float(sub['Amount'].sum()):,.0f} Ks")
    return "\n".join(lines)

@tool("record_purchase")
def tool_record_purchase(json_str: str) -> str:
    try:
        j = json.loads(json_str)
    except json.JSONDecodeError as e:
        return f"JSON အမှား: {e}"
    item = j.get("item") or j.get("item_name") or ""
    ok, err = save_purchase_record(item, j.get("price"), j.get("date"))
    if ok:
        p = float(j.get("price") or 0)
        return f"✅ အဝယ် သွင်းပြီး — {(item or '').strip()} · {p:,.0f} Ks"
    return err or "မအောင်မြင်ပါ"

@tool("get_purchase_summary")
def tool_get_purchase_summary(days_arg: str = "7") -> str:
    """နောက်ဆုံး N ရက်အတွင်း အဝယ်စာရင်း ချုပ် (ပုံမှန် ၇)"""
    try:
        n = max(1, min(365, int((days_arg or "7").strip() or 7)))
    except ValueError:
        n = 7
    try:
        df = pd.read_excel(PURCHASE_FILE)
    except Exception:
        return "အဝယ်ဖိုင် ဖတ်မရပါ။"
    if df.empty:
        return "အဝယ် မှတ်တမ်း မရှိပါ။"
    df = df.copy()
    df["_d"] = pd.to_datetime(df["Date"], errors="coerce")
    cut = datetime.now().date() - timedelta(days=n)
    sub = df[df["_d"].dt.date >= cut]
    if sub.empty:
        return f"နောက်ဆုံး {n} ရက်အတွင်း အဝယ် မရှိပါ။"
    tot = float(sub["Price"].sum())
    head = sub.sort_values("_d", ascending=False).head(12)
    lines = [f"  {r['Date']} | {r['ItemName']} | {float(r['Price']):,.0f} Ks" for _, r in head.iterrows()]
    return f"နောက်ဆုံး {n} ရက် · စုစုပေါင်း {tot:,.0f} Ks · {len(sub)} ကြောင်း\n" + "\n".join(lines)

@tool("get_creditors")
def tool_get_creditors(_: str = "") -> str:
    cr = read_master_sheet_safe("Creditors", ["CreditorName"])
    names = cr["CreditorName"].dropna().astype(str).str.strip()
    names = names[names != ""].unique().tolist()
    if not names:
        return "Master မှာ ဈေးသမား/ပေးရမည့်သူ စာရင်း မရှိသေးပါ။"
    return ", ".join(sorted(names))

@tool("get_purchase_catalog")
def tool_get_purchase_catalog(_: str = "") -> str:
    df = read_master_sheet_safe("PurchaseCatalog", ["ItemName", "RefPrice"])
    if df.empty:
        return "ဝယ်ပစ္စည်း စာရင်း မရှိသေးပါ။"
    lines = []
    for _, r in df.iterrows():
        rp = r["RefPrice"]
        try:
            p = float(rp) if pd.notna(rp) else 0.0
        except (TypeError, ValueError):
            p = 0.0
        lines.append(f"  {r['ItemName']}: မှတ်သားဈေး {p:,.0f} Ks")
    return "\n".join(lines[:25]) + ("\n  …" if len(lines) > 25 else "")

@tool("record_payable")
def tool_record_payable(json_str: str) -> str:
    msg = _require_admin_tool("record_payable")
    if msg:
        return msg
    try:
        j = json.loads(json_str)
    except json.JSONDecodeError as e:
        return f"JSON အမှား: {e}"
    creditor = j.get("creditor") or j.get("creditor_name") or ""
    desc = j.get("description") or j.get("note") or ""
    ok, err = save_payable_record(creditor, desc, j.get("amount"), j.get("date"))
    if ok:
        a = float(j.get("amount") or 0)
        return f"✅ အကြွေး မှတ်ပြီး — {(creditor or '').strip()} · {a:,.0f} Ks"
    return err or "မအောင်မြင်ပါ"

@tool("get_payable_summary")
def tool_get_payable_summary(name: str = "") -> str:
    df = _payable_read()
    up = df[df["Status"].astype(str).str.strip() == "Unpaid"]
    if name:
        up = up[up["CreditorName"].astype(str).str.contains(name, case=False, na=False)]
    if up.empty:
        return "မရှင်းရသေးသော အကြွေး မရှိပါ။" if not name else f"\"{name}\" နှင့် ကိုက်ညီသော အကြွေး မရှိပါ။"
    lines = []
    for c, grp in up.groupby("CreditorName", sort=False):
        lines.append(f"  {c}: {float(grp['Amount'].sum()):,.0f} Ks ({len(grp)} ကြောင်း)")
    lines.append(f"  ── စုစုပေါင်း: {float(up['Amount'].sum()):,.0f} Ks")
    return "\n".join(lines)

@tool("settle_payable")
def tool_settle_payable(creditor_name: str) -> str:
    """ဈေးသမား/ပေးရမည့်သူ တစ်ဦးချင်း၏ မရှင်းရအကြွေးအားလုံး ရှင်းသည် — စီမံခန့်ခွဲသူသာ"""
    try:
        if (st.session_state.get("user") or {}).get("role") != "admin":
            return "⚠️ အကြွေးငွေရှင်းခြင်းကို Agent မှ **စီမံခန့်ခွဲသူ** သာလုပ်ခွင့်ရှိပါသည်။ ငွေကိုင်အနေဖြင့် ⚙️ အဝယ် စာမျက်နှာမှ ရှင်းပါ။"
    except Exception:
        pass
    cn = (creditor_name or "").strip()
    if not cn:
        return "ပေးရမည့်သူ နာမည် ထည့်ပါ။"
    ok = settle_payable_creditor_all(cn, settled_by=_agent_actor_label())
    return f"✅ {cn} ၏ အကြွေးအားလုံး ရှင်းပြီးပါပြီ။" if ok else f"⚠️ {cn} ၏ မရှင်းရအကြွေး မရှိပါ။"

@tool("list_unpaid_ledger_rows")
def tool_list_unpaid_ledger_rows(name_substr: str = "") -> str:
    """Unpaid လိုင်းများ — row_index သည် ပြင်ရန်/Trash သို့ ပို့ရန် သုံးပါ"""
    df = _ledger_read()
    sub = df[df["Status"].astype(str).str.strip() == "Unpaid"]
    q = (name_substr or "").strip()
    if q:
        sub = sub[sub["Name"].astype(str).str.contains(q, case=False, na=False)]
    if sub.empty:
        return "မရှင်းရသေးသော လိုင်း မရှိပါ။"
    lines = []
    for idx, r in sub.head(30).iterrows():
        lines.append(
            f"  row_index={int(idx)} | {r['Date']} | {r['Name']} | {r['Description']} | {float(r['Amount']):,.0f} Ks"
        )
    if len(sub) > 30:
        lines.append(f"  … စုစုပေါင်း {len(sub)} ကြောင်း (ပထမ ၃၀ သာ)")
    return "\n".join(lines)

@tool("edit_ledger_line")
def tool_edit_ledger_line(json_str: str) -> str:
    msg = _require_admin_tool("edit_ledger_line")
    if msg:
        return msg
    try:
        j = json.loads(json_str)
    except json.JSONDecodeError as e:
        return f"JSON အမှား: {e}"
    try:
        idx = int(j["row_index"])
    except (KeyError, TypeError, ValueError):
        return "row_index လိုအပ်ပါသည်။"
    ok, err = update_ledger_row(
        idx,
        str(j.get("date", "")).strip() or datetime.now().strftime("%Y-%m-%d"),
        j.get("description", ""),
        j.get("amount", 0),
    )
    return "✅ စာရင်း ပြင်ပြီး။" if ok else (err or "မအောင်မြင်ပါ")

@tool("move_ledger_to_trash")
def tool_move_ledger_to_trash(row_arg: str) -> str:
    msg = _require_admin_tool("move_ledger_to_trash")
    if msg:
        return msg
    try:
        idx = int(str(row_arg).strip())
    except ValueError:
        return "row_index ကို ဂဏန်း ထည့်ပါ။"
    df = _ledger_read()
    if idx not in df.index:
        return "row_index မတွေ့ပါ။ list_unpaid_ledger_rows ဖြင့် စစ်ပါ။"
    try:
        move_to_trash(idx)
        return f"✅ row {idx} ကို Trash သို့ ပို့ပြီးပါပြီ။"
    except Exception as e:
        return f"ERROR: {e}"

@tool("list_trash_recent")
def tool_list_trash_recent(n_arg: str = "15") -> str:
    try:
        n = max(1, min(50, int(str(n_arg).strip() or 15)))
    except ValueError:
        n = 15
    try:
        tdf = pd.read_excel(TRASH_FILE)
    except Exception:
        return "Trash ဖတ် မရပါ။"
    if tdf.empty:
        return "Trash ဗလာ။"
    if "DeletedAt" in tdf.columns:
        tdf = tdf.copy()
        tdf["_s"] = pd.to_datetime(tdf["DeletedAt"], errors="coerce")
        tdf = tdf.sort_values("_s", ascending=False, na_position="last")
    lines = []
    for idx, r in tdf.head(n).iterrows():
        lines.append(
            f"  trash_row_index={int(idx)} | {r.get('Date','')} | {r.get('Name','')} | {r.get('Description','')} | {float(r.get('Amount',0)):,.0f} Ks"
        )
    return "\n".join(lines)

@tool("restore_trash_line")
def tool_restore_trash_line(row_arg: str) -> str:
    msg = _require_admin_tool("restore_trash_line")
    if msg:
        return msg
    try:
        idx = int(str(row_arg).strip())
    except ValueError:
        return "trash_row_index ဂဏန်း ထည့်ပါ။"
    ok, err = restore_from_trash(idx)
    return "✅ Ledger သို့ ပြန်ထည့်ပြီး။" if ok else (err or "မအောင်မြင်ပါ")

@tool("purge_trash_line")
def tool_purge_trash_line(row_arg: str) -> str:
    msg = _require_admin_tool("purge_trash_line")
    if msg:
        return msg
    try:
        idx = int(str(row_arg).strip())
    except ValueError:
        return "trash_row_index ဂဏန်း ထည့်ပါ။"
    if purge_trash_row(idx):
        return f"✅ Trash row {idx} အပြီးဖျက်ပြီး။"
    return "မတွေ့ပါ။"

@tool("list_payable_unpaid_lines")
def tool_list_payable_unpaid_lines(creditor_substr: str = "") -> str:
    df = _payable_read()
    up = df[df["Status"].astype(str).str.strip() == "Unpaid"]
    q = (creditor_substr or "").strip()
    if q:
        up = up[up["CreditorName"].astype(str).str.contains(q, case=False, na=False)]
    if up.empty:
        return "မရှင်းရသေးသော အကြွေးလိုင်း မရှိပါ။"
    lines = []
    for idx, r in up.head(35).iterrows():
        lines.append(
            f"  row_index={int(idx)} | {r['Date']} | {r['CreditorName']} | {r['Description']} | {float(r['Amount']):,.0f} Ks"
        )
    return "\n".join(lines)

@tool("settle_payable_line")
def tool_settle_payable_line(json_str: str) -> str:
    msg = _require_admin_tool("settle_payable_line")
    if msg:
        return msg
    try:
        j = json.loads(json_str)
        idx = int(j["row_index"])
    except Exception:
        return "JSON: {\"row_index\": နံပါတ်} ထည့်ပါ။"
    if settle_payable_row(idx, settled_by=_agent_actor_label()):
        return f"✅ အကြွေး row {idx} ရှင်းပြီး။"
    return "မရှင်းနိုင် သို့မဟုတ် မတွေ့ပါ။"

@tool("get_dashboard_stats")
def tool_get_dashboard_stats(period: str = "today") -> str:
    p = (period or "today").strip().lower()
    df = _ledger_read()
    paid = df[df["Status"].astype(str).str.strip() == "Paid"].copy()
    unpaid = df[df["Status"].astype(str).str.strip() == "Unpaid"]
    u_tot = float(unpaid["Amount"].sum()) if not unpaid.empty else 0.0
    if paid.empty:
        return f"ငွေရှင်းပြီး မှတ်တမ်း မရှိပါ။ မရှင်းရစုစုပေါင်း: {u_tot:,.0f} Ks"
    paid["Date"] = pd.to_datetime(paid["Date"], errors="coerce")
    s_set = pd.to_datetime(paid["SettledAt"], errors="coerce") if "SettledAt" in paid.columns else pd.Series(pd.NaT, index=paid.index)
    paid["_rd"] = s_set.dt.date.where(s_set.notna(), paid["Date"].dt.date)
    now = datetime.now()
    today_d = now.date()
    if p in ("today", "ယနေ့"):
        fl = paid[paid["_rd"] == today_d]
    elif p in ("week", "ဒီတစ်ပတ်", "7"):
        cut = (now - timedelta(days=7)).date()
        fl = paid[paid["_rd"] >= cut]
    elif p in ("month", "ဒီလ"):
        cut = now.replace(day=1).date()
        fl = paid[paid["_rd"] >= cut]
    elif p in ("year", "တစ်နှစ်", "365"):
        cut = (now - timedelta(days=365)).date()
        fl = paid[paid["_rd"] >= cut]
    elif p in ("all", "အားလုံး"):
        fl = paid
    else:
        fl = paid
    rev = float(fl["Amount"].sum()) if not fl.empty else 0.0
    n = len(fl)
    avg = rev / n if n else 0.0
    return (
        f"ကာလ: {p}\n"
        f"  ငွေရှင်းပြီး ဝင်ငွေ: {rev:,.0f} Ks ({n} ကြောင်း)\n"
        f"  ပျမ်းမျှ: {avg:,.0f} Ks\n"
        f"  မရှင်းရ ကျန်ငွေ (Ledger): {u_tot:,.0f} Ks"
    )

@tool("get_customer_paid")
def tool_get_customer_paid(name: str) -> str:
    q = (name or "").strip()
    if not q:
        return "ဖောက်သည်နာမည် ထည့်ပါ။"
    df = _ledger_read()
    sub = df[(df["Name"].astype(str).str.contains(q, case=False, na=False)) & (df["Status"].astype(str).str.strip() == "Paid")]
    if sub.empty:
        return f"{q} ၏ ငွေရှင်းပြီး မှတ်တမ်း မရှိပါ။"
    sub = sub.copy()
    sub["_d"] = pd.to_datetime(sub["Date"], errors="coerce")
    cut = datetime.now().date() - timedelta(days=90)
    sub = sub[sub["_d"].dt.date >= cut]
    if sub.empty:
        return f"နောက်ဆုံး ၉၀ ရက်အတွင်း ငွေရှင်းပြီး မှတ်တမ်း မရှိပါ။"
    tot_all = float(sub["Amount"].sum())
    disp = sub.sort_values("_d", ascending=False).head(25)
    lines = [f"  {r['Date']} | {r['Description']} | {float(r['Amount']):,.0f} Ks | ရှင်း {r.get('SettledBy','—')}" for _, r in disp.iterrows()]
    return (
        f"နောက်ဆုံး ~၉၀ ရက် · {q} · စုစုပေါင်း {tot_all:,.0f} Ks ({len(sub)} ကြောင်း)\n"
        + "\n".join(lines)
        + (f"\n  … နောက်ထပ် {len(sub) - len(disp)} ကြောင်း" if len(sub) > len(disp) else "")
    )

@tool("master_add_customer")
def tool_master_add_customer(json_str: str) -> str:
    msg = _require_admin_tool("master_add_customer")
    if msg:
        return msg
    try:
        j = json.loads(json_str)
        name = (j.get("name") or "").strip()
    except json.JSONDecodeError as e:
        return f"JSON အမှား: {e}"
    if not name:
        return "name ထည့်ပါ။"
    try:
        cdf = pd.read_excel(MASTER_FILE, sheet_name="Customers")
    except Exception:
        cdf = pd.DataFrame(columns=["CustomerName"])
    if name in cdf["CustomerName"].astype(str).values:
        return "နာမည် ရှိပြီးသား။"
    cdf = pd.concat([cdf, pd.DataFrame([{"CustomerName": name}])], ignore_index=True)
    write_master_sheet("Customers", cdf)
    return f"✅ ဖောက်သည် {name} ထည့်ပြီး။"

@tool("master_add_menu")
def tool_master_add_menu(json_str: str) -> str:
    msg = _require_admin_tool("master_add_menu")
    if msg:
        return msg
    try:
        j = json.loads(json_str)
        item = (j.get("item") or j.get("name") or "").strip()
        price = float(j.get("price", 0))
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        return f"အမှား: {e}"
    if not item:
        return "item နှင့် price ထည့်ပါ။"
    try:
        mdf = pd.read_excel(MASTER_FILE, sheet_name="Menu")
    except Exception:
        mdf = pd.DataFrame(columns=["Item", "Price"])
    if item in mdf["Item"].astype(str).values:
        return "menu နာမည် ရှိပြီးသား။"
    mdf = pd.concat([mdf, pd.DataFrame([{"Item": item, "Price": price}])], ignore_index=True)
    write_master_sheet("Menu", mdf)
    return f"✅ Menu {item} · {price:,.0f} Ks ထည့်ပြီး။"

@tool("master_add_creditor")
def tool_master_add_creditor(json_str: str) -> str:
    msg = _require_admin_tool("master_add_creditor")
    if msg:
        return msg
    try:
        j = json.loads(json_str)
        name = (j.get("name") or j.get("creditor") or "").strip()
    except json.JSONDecodeError as e:
        return f"JSON အမှား: {e}"
    if not name:
        return "name ထည့်ပါ။"
    cr = read_master_sheet_safe("Creditors", ["CreditorName"])
    if name in cr["CreditorName"].astype(str).str.strip().values:
        return "ရှိပြီးသား။"
    cr = pd.concat([cr, pd.DataFrame([{"CreditorName": name}])], ignore_index=True)
    write_master_sheet("Creditors", cr)
    return f"✅ ဈေးသမား {name} ထည့်ပြီး။"

@tool("master_add_pcat")
def tool_master_add_pcat(json_str: str) -> str:
    msg = _require_admin_tool("master_add_pcat")
    if msg:
        return msg
    try:
        j = json.loads(json_str)
        item = (j.get("item") or j.get("item_name") or "").strip()
        ref = float(j.get("ref_price", j.get("price", 0)))
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        return f"အမှား: {e}"
    if not item:
        return "item ထည့်ပါ။"
    pc = read_master_sheet_safe("PurchaseCatalog", ["ItemName", "RefPrice"])
    if item in pc["ItemName"].astype(str).str.strip().values:
        return "ပစ္စည်း ရှိပြီးသား။"
    pc = pd.concat([pc, pd.DataFrame([{"ItemName": item, "RefPrice": ref}])], ignore_index=True)
    write_master_sheet("PurchaseCatalog", pc)
    return f"✅ ဝယ်ပစ္စည်း {item} · မှတ်ဈေး {ref:,.0f} Ks"

TOOLS_DESC = """
Available tools (one line): THINK:... OR TOOL:<name>:<arg> OR DONE:...
**ငွေကိုင်** ခွင့်ပြု: calculate, get_*, lookup_menu_price, add_order, record_purchase, list_unpaid_ledger_rows, list_trash_recent, list_payable_unpaid_lines, get_dashboard_stats, get_customer_paid
**စီမံခန့်ခွဲသူ သာ**: settle_bill, settle_payable, settle_payable_line, record_payable, edit_ledger_line, move_ledger_to_trash, restore_trash_line, purge_trash_line, master_add_*
JSON (တစ်ကြောင်းတည်း): add_order, record_purchase, record_payable, edit_ledger_line, settle_payable_line, master_add_customer, master_add_menu, master_add_creditor, master_add_pcat
- calculate:<expr>
- get_ledger_summary:<name_or_empty>
- get_customer_detail:<name>
- add_order:<json>  {"name","food","qty","price" [,"date"]}
- settle_bill:<name>
- get_menu:<>  get_customers:<>
- lookup_menu_price:<text>
- get_today_unpaid:<>
- record_purchase:<json>  {"item","price" [,"date"]}
- get_purchase_summary:<days>
- get_purchase_catalog:<>  get_creditors:<>
- record_payable:<json>  {"creditor","amount" [,"description" [,"date"]]}
- get_payable_summary:<name_or_empty>
- settle_payable:<creditor>
- list_unpaid_ledger_rows:<name_or_empty>
- edit_ledger_line:<json>  {"row_index","date","description","amount"}
- move_ledger_to_trash:<row_index>
- list_trash_recent:<n_or_empty>
- restore_trash_line:<trash_row_index>
- purge_trash_line:<trash_row_index>
- list_payable_unpaid_lines:<creditor_or_empty>
- settle_payable_line:<json>  {"row_index":N}
- get_dashboard_stats:<today|week|month|year|all>
- get_customer_paid:<name>
- master_add_customer:<json>  {"name"}
- master_add_menu:<json>  {"item","price"}
- master_add_creditor:<json>  {"name"}
- master_add_pcat:<json>  {"item","ref_price"}
- DONE:<မြန်မာအဖြေ>
"""

# ══════════════════════════════════════════════════════════════════
#  LEDGER CORE
# ══════════════════════════════════════════════════════════════════
def _ledger_read():
    df = pd.read_excel(LEDGER_FILE)
    if "SettledAt" not in df.columns:
        df["SettledAt"] = pd.NaT
    if "SettledBy" not in df.columns:
        df["SettledBy"] = ""
    return df

def save_to_ledger(name, desc, amount, date=None):
    df = _ledger_read()
    date = date or datetime.now().strftime("%Y-%m-%d")
    df = pd.concat([df, pd.DataFrame([{"Date": date, "Name": name, "Description": desc,
                    "Amount": amount, "Status": "Unpaid", "SettledAt": pd.NaT, "SettledBy": ""}])], ignore_index=True)
    df.to_excel(LEDGER_FILE, index=False)
    sync_to_download(LEDGER_FILE)

def save_purchase_record(item_name, price, date=None):
    item_name = (item_name or "").strip()
    if not item_name:
        return False, "ပစ္စည်းအမည် ထည့်ပါ။"
    try:
        p = float(price)
    except (TypeError, ValueError):
        return False, "ဈေးနှုန်း မှန်ကန်စွာ ထည့်ပါ။"
    if p < 0:
        return False, "ဈေးနှုန်း သည် သုည သို့မဟုတ် အပေါင်းဖြစ်ရမည်။"
    date = date or datetime.now().strftime("%Y-%m-%d")
    df = pd.read_excel(PURCHASE_FILE)
    df = pd.concat(
        [df, pd.DataFrame([{"Date": date, "ItemName": item_name, "Price": p}])],
        ignore_index=True,
    )
    df.to_excel(PURCHASE_FILE, index=False)
    sync_to_download(PURCHASE_FILE)
    return True, None

def update_purchase_row(row_index, date_str, item_name, price):
    df = pd.read_excel(PURCHASE_FILE)
    if row_index not in df.index:
        return False, "စာကြောင်းမတွေ့ပါ။"
    item_name = (item_name or "").strip()
    if not item_name:
        return False, "ပစ္စည်းအမည် ထည့်ပါ။"
    try:
        p = float(price)
    except (TypeError, ValueError):
        return False, "ဈေးနှုန်း မှန်ကန်စွာ ထည့်ပါ။"
    if p < 0:
        return False, "ဈေးနှုန်း သည် သုည သို့မဟုတ် အပေါင်းဖြစ်ရမည်။"
    df.loc[row_index, "Date"] = date_str
    df.loc[row_index, "ItemName"] = item_name
    df.loc[row_index, "Price"] = p
    df.to_excel(PURCHASE_FILE, index=False)
    sync_to_download(PURCHASE_FILE)
    return True, None

def _payable_read():
    df = pd.read_excel(PAYABLE_FILE)
    if "SettledAt" not in df.columns:
        df["SettledAt"] = pd.NaT
    if "SettledBy" not in df.columns:
        df["SettledBy"] = ""
    return df

def save_payable_record(creditor_name, description, amount, date=None):
    creditor_name = (creditor_name or "").strip()
    if not creditor_name:
        return False, "ပေးရမည့်သူ (ဈေးသမား/ပြန်ပေးရမည့်နာမည်) ထည့်ပါ။"
    desc = (description or "").strip() or "—"
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return False, "ပမာဏ မှန်ကန်စွာ ထည့်ပါ။"
    if amt <= 0:
        return False, "ပမာဏ သည် သုညထက်ကြီးရမည်။"
    date = date or datetime.now().strftime("%Y-%m-%d")
    df = _payable_read()
    df = pd.concat(
        [df, pd.DataFrame([{
            "Date": date,
            "CreditorName": creditor_name,
            "Description": desc,
            "Amount": amt,
            "Status": "Unpaid",
            "SettledAt": pd.NaT,
            "SettledBy": "",
        }])],
        ignore_index=True,
    )
    df.to_excel(PAYABLE_FILE, index=False)
    sync_to_download(PAYABLE_FILE)
    return True, None

def update_payable_row(row_index, date_str, creditor_name, description, amount):
    df = _payable_read()
    if row_index not in df.index:
        return False, "စာကြောင်းမတွေ့ပါ။"
    if str(df.loc[row_index, "Status"]).strip() != "Unpaid":
        return False, "မရှင်းရသေးသော အကြွေးကိုသာ ပြင်နိုင်ပါသည်။"
    creditor_name = (creditor_name or "").strip()
    if not creditor_name:
        return False, "ပေးရမည့်သူ ထည့်ပါ။"
    desc = (description or "").strip() or "—"
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return False, "ပမာဏ မှန်ကန်စွာ ထည့်ပါ။"
    if amt <= 0:
        return False, "ပမာဏ သည် သုညထက်ကြီးရမည်။"
    df.loc[row_index, "Date"] = date_str
    df.loc[row_index, "CreditorName"] = creditor_name
    df.loc[row_index, "Description"] = desc
    df.loc[row_index, "Amount"] = amt
    df.to_excel(PAYABLE_FILE, index=False)
    sync_to_download(PAYABLE_FILE)
    return True, None

def settle_payable_row(row_index, settled_by=None):
    df = _payable_read()
    if row_index not in df.index:
        return False
    if str(df.loc[row_index, "Status"]).strip() != "Unpaid":
        return False
    who = (settled_by or "").strip() or "—"
    df.loc[row_index, "Status"] = "Paid"
    df.loc[row_index, "SettledAt"] = datetime.now().strftime("%Y-%m-%d")
    df.loc[row_index, "SettledBy"] = who
    df.to_excel(PAYABLE_FILE, index=False)
    sync_to_download(PAYABLE_FILE)
    return True

def settle_payable_creditor_all(creditor_name, settled_by=None):
    df = _payable_read()
    cn = str(creditor_name).strip()
    mask = (df["CreditorName"].astype(str).str.strip() == cn) & (df["Status"] == "Unpaid")
    if not mask.any():
        return False
    who = (settled_by or "").strip() or "—"
    df.loc[mask, "Status"] = "Paid"
    df.loc[mask, "SettledAt"] = datetime.now().strftime("%Y-%m-%d")
    df.loc[mask, "SettledBy"] = who
    df.to_excel(PAYABLE_FILE, index=False)
    sync_to_download(PAYABLE_FILE)
    return True

def clear_customer_bill(name, settled_by=None):
    df = _ledger_read()
    nm = str(name).strip()
    if not nm:
        return False
    # regex=False — နာမည်ထဲက + ( ) * စသည် regex အဖြစ် မသတ်မှတ်ရန် (ဥပမာ "ကို + ကို")
    mask = (
        df["Name"].astype(str).str.contains(nm, case=False, na=False, regex=False)
        & (df["Status"] == "Unpaid")
    )
    if mask.any():
        df.loc[mask,'Status']='Paid'
        df.loc[mask,'SettledAt'] = datetime.now().strftime("%Y-%m-%d")
        who = (settled_by or "").strip() or "—"
        df.loc[mask,'SettledBy'] = who
        df.to_excel(LEDGER_FILE, index=False)
        sync_to_download(LEDGER_FILE)
        return True
    return False

def move_to_trash(row_index):
    df = _ledger_read()
    trash_df = pd.read_excel(TRASH_FILE)
    row = df.iloc[[row_index]].copy()
    row['DeletedAt'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    trash_df = pd.concat([trash_df, row], ignore_index=True)
    df = df.drop(row_index).reset_index(drop=True)
    df.to_excel(LEDGER_FILE, index=False)
    trash_df.to_excel(TRASH_FILE, index=False)
    sync_to_download(LEDGER_FILE)

def restore_from_trash(trash_row_index):
    tdf = pd.read_excel(TRASH_FILE)
    if trash_row_index not in tdf.index:
        return False, "မတွေ့ပါ။"
    row = tdf.loc[trash_row_index]
    ldf = _ledger_read()
    rec = {
        "Date": row["Date"],
        "Name": row["Name"],
        "Description": row["Description"],
        "Amount": float(row["Amount"]),
        "Status": "Unpaid",
        "SettledAt": pd.NaT,
        "SettledBy": "",
    }
    ldf = pd.concat([ldf, pd.DataFrame([rec])], ignore_index=True)
    tdf = tdf.drop(trash_row_index).reset_index(drop=True)
    ldf.to_excel(LEDGER_FILE, index=False)
    tdf.to_excel(TRASH_FILE, index=False)
    sync_to_download(LEDGER_FILE)
    sync_to_download(TRASH_FILE)
    return True, None

def purge_trash_row(trash_row_index):
    tdf = pd.read_excel(TRASH_FILE)
    if trash_row_index not in tdf.index:
        return False
    tdf = tdf.drop(trash_row_index).reset_index(drop=True)
    tdf.to_excel(TRASH_FILE, index=False)
    sync_to_download(TRASH_FILE)
    return True

def restore_trash_batch(indices):
    """Trash ထဲက လိုင်းအများအပြားကို တစ်ကြိမ်သိမ်းဖြင့် ledger သို့ ပြန်ထည့်"""
    tdf = pd.read_excel(TRASH_FILE)
    ix = [i for i in indices if i in tdf.index]
    if not ix:
        return False, "0"
    ldf = _ledger_read()
    recs = []
    for i in ix:
        row = tdf.loc[i]
        recs.append({
            "Date": row["Date"],
            "Name": row["Name"],
            "Description": row["Description"],
            "Amount": float(row["Amount"]),
            "Status": "Unpaid",
            "SettledAt": pd.NaT,
            "SettledBy": "",
        })
    ldf = pd.concat([ldf, pd.DataFrame(recs)], ignore_index=True)
    tdf = tdf.drop(ix).reset_index(drop=True)
    ldf.to_excel(LEDGER_FILE, index=False)
    tdf.to_excel(TRASH_FILE, index=False)
    sync_to_download(LEDGER_FILE)
    sync_to_download(TRASH_FILE)
    return True, str(len(recs))

def purge_trash_batch(indices):
    tdf = pd.read_excel(TRASH_FILE)
    ix = [i for i in indices if i in tdf.index]
    if not ix:
        return False
    tdf = tdf.drop(ix).reset_index(drop=True)
    tdf.to_excel(TRASH_FILE, index=False)
    sync_to_download(TRASH_FILE)
    return True

def _recycle_key(*parts):
    return hashlib.md5("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:14]

def _ledger_cell_to_date(val):
    if val is None or (isinstance(val, float) and math.isnan(val)) or pd.isna(val):
        return datetime.now().date()
    if hasattr(val, "date") and callable(getattr(val, "date")):
        return val.date()
    return pd.to_datetime(val).date()

def update_ledger_row(row_index, date_str, description, amount):
    """Unpaid လိုင်းတစ်ခုကို တိုက်ရိုက် ပြင်ဆင်ရန် (Excel ထဲတန်ဖိုးအစားထိုး၊ ဖျက်မထား)"""
    df = _ledger_read()
    if row_index not in df.index:
        return False, "စာကြောင်းမတွေ့ပါ။"
    st_cell = df.loc[row_index, "Status"]
    if str(st_cell).strip() != "Unpaid":
        return False, "မရှင်းရသေးသော စာရင်းကိုသာ ပြင်နိုင်ပါသည်။"
    desc = (description or "").strip()
    if not desc:
        return False, "မှာယူမှုဖော်ပြချက် ထည့်ပါ။"
    try:
        amt = float(amount)
    except (TypeError, ValueError):
        return False, "ပမာဏ မှန်ကန်စွာ ထည့်ပါ။"
    if amt < 0:
        return False, "ပမာဏ သည် သုည သို့မဟုတ် အပေါင်းဖြစ်ရမည်။"
    df.loc[row_index, "Date"] = date_str
    df.loc[row_index, "Description"] = desc
    df.loc[row_index, "Amount"] = amt
    df.to_excel(LEDGER_FILE, index=False)
    sync_to_download(LEDGER_FILE)
    return True, None

# ══════════════════════════════════════════════════════════════════
#  AGENT LOOP
# ══════════════════════════════════════════════════════════════════
CASHIER_AGENT_TOOLS = frozenset({
    "calculate", "get_ledger_summary", "get_customer_detail", "add_order",
    "get_menu", "get_customers", "lookup_menu_price", "get_today_unpaid",
    "record_purchase", "get_purchase_summary", "get_purchase_catalog", "get_creditors",
    "get_payable_summary", "get_dashboard_stats", "get_customer_paid",
    "list_unpaid_ledger_rows", "list_trash_recent", "list_payable_unpaid_lines",
})

MUTATION_AGENT_TOOLS = frozenset({
    "add_order", "settle_bill", "record_purchase", "record_payable", "settle_payable", "settle_payable_line",
    "edit_ledger_line", "move_ledger_to_trash", "restore_trash_line", "purge_trash_line",
    "master_add_customer", "master_add_menu", "master_add_creditor", "master_add_pcat",
})

_JSON_TOOL_NAMES = frozenset({
    "add_order", "record_purchase", "record_payable", "edit_ledger_line", "settle_payable_line",
    "master_add_customer", "master_add_menu", "master_add_creditor", "master_add_pcat",
})

def agent_tool_gate(tool_name: str):
    try:
        role = (st.session_state.get("user") or {}).get("role")
    except Exception:
        role = None
    if role == "admin":
        return None
    if tool_name in CASHIER_AGENT_TOOLS:
        return None
    return (
        f"⚠️ ငွေကိုင် အနေဖြင့် Agent မှ [{tool_name}] ကို မသုံးနိုင်ပါ။ "
        "စီမံခန့်ခွဲသူ ဝင်ပါ (သို့) သက်ဆိုင်ရာ စာမျက်နှာမှ လုပ်ပါ။"
    )

def run_agent(user_input: str, gemini_model) -> tuple[str, list]:
    steps_log = []
    mem_ctx = memory_context()
    chat_ctx = chat_context()
    try:
        _role = (st.session_state.get("user") or {}).get("role", "—")
        _rname = (st.session_state.get("user") or {}).get("name", "—")
    except Exception:
        _role, _rname = "—", "—"

    system_prompt = f"""You are an expert restaurant & shop ledger assistant (Myanmar language UI).
Logged-in user: {_rname} (role: {_role}). If role is cashier, do NOT call admin-only tools — they will fail.
{TOOLS_DESC}
Rules:
- ONE line only per turn: THINK:<brief> OR TOOL:<name>:<arg> OR DONE:<answer>
- JSON tools must be one line (no raw newlines inside JSON).
- For ledger edit/trash: first list_unpaid_ledger_rows or list_trash_recent to get row_index.
- Prefer lookup_menu_price before add_order if price unknown.
- Be accurate. DONE = short Burmese answer.

{chat_ctx}{mem_ctx}
Current date: {datetime.now().strftime("%Y-%m-%d")}
"""
    messages = [{"role":"user", "parts":[system_prompt + "\nUser request: " + user_input]}]

    for _step_num in range(16):
        try:
            response = gemini_model.generate_content(messages)
            raw = (getattr(response, "text", None) or "").strip()
        except Exception as e:
            steps_log.append({"step": "⚠️", "content": str(e)})
            return f"မော်ဒယ် ချို့ယွင်းချက်: {e}", steps_log
        if not raw:
            return "မော်ဒယ် ပြန်စာမရှိပါ၊ API key / မော်ဒယ် စစ်ပြီး ထပ်စမ်းပါ။", steps_log
        line = raw.split("\n")[0].strip()

        if line.startswith("THINK:"):
            thought = line[6:].strip()
            steps_log.append({"step": "🧠 THINK", "content": thought})
            messages.append({"role":"model", "parts":[line]})
            messages.append({"role":"user", "parts":["Continue."]})

        elif line.startswith("TOOL:"):
            parts = line[5:].split(":", 1)
            tool_name = parts[0].strip()
            tool_arg = parts[1].strip() if len(parts) > 1 else ""
            steps_log.append({"step": f"🔧 TOOL:{tool_name}", "content": tool_arg})

            if tool_name not in TOOL_REGISTRY:
                obs = f"Unknown tool: {tool_name}"
            else:
                gate = agent_tool_gate(tool_name)
                if gate:
                    obs = gate
                else:
                    try:
                        if tool_name == "add_order":
                            j = json.loads(tool_arg)
                            d = j.get("date") or None
                            obs = TOOL_REGISTRY[tool_name](
                                j["name"],
                                j["food"],
                                int(j.get("qty", 1)),
                                float(j.get("price", 0)),
                                d,
                            )
                        elif tool_name in _JSON_TOOL_NAMES:
                            obs = TOOL_REGISTRY[tool_name](tool_arg)
                        else:
                            obs = TOOL_REGISTRY[tool_name](tool_arg)
                    except Exception as e:
                        obs = f"TOOL အမှား: {e}"

            if tool_name in MUTATION_AGENT_TOOLS:
                append_audit(tool_name, f"{tool_arg[:350]} => {str(obs)[:350]}")

            steps_log.append({"step": "📋 RESULT", "content": obs})
            messages.append({"role":"model", "parts":[line]})
            messages.append({"role":"user", "parts":[f"Tool result: {obs}\nContinue."]})

        elif line.startswith("DONE:"):
            final = line[5:].strip()
            steps_log.append({"step": "✅ DONE", "content": final})
            return final, steps_log

        else:
            steps_log.append({"step": "✅ DONE", "content": line})
            return line, steps_log

    return "Agent အဆင့်အရေအတွက် ပြည့်သွားပြီ။ ထပ်မံ မေးမြန်းပါ။", steps_log

# ══════════════════════════════════════════════════════════════════
#  UI FUNCTIONS
# ══════════════════════════════════════════════════════════════════

def login_ui():
    st.markdown("""
    <div style="text-align:center; padding:40px 20px; background:linear-gradient(135deg, #FF6B35, #F7931E); border-radius:20px; margin-bottom:30px">
        <h1 style="color:white; margin:0; font-size:2.5rem">🍚 ကိုကျော် ထမင်းဆိုင်</h1>
        <p style="color:#FFF2E6; margin:5px 0 0 0">အရသာနှင့် စံချိန်မီ ထမင်းဆိုင်</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("### 🔐 ဝင်ရောက်ရန်")
    with st.form("login_form"):
        username = st.text_input("အသုံးပြုသူအမည်")
        password = st.text_input("စကားဝှက်", type="password")
        submitted = st.form_submit_button("ဝင်မည်", use_container_width=True)

        if submitted:
            user = check_login(username, password)
            if user:
                st.session_state.user = user
                st.rerun()
            else:
                st.error("အသုံးပြုသူအမည် သို့မဟုတ် စကားဝှက် မှားယွင်းနေပါသည်။")

def logout_ui():
    if st.sidebar.button("🚪 ထွက်မည်", use_container_width=True):
        st.session_state.user = None
        st.rerun()

def _he(x):
    return html.escape(str(x), quote=True)

def _td_money(v):
    return f'<span style="display:block;text-align:right;font-variant-numeric:tabular-nums">{float(v):,.0f} Ks</span>'

def _fmt_amount(v, *, suffix=""):
    """ကိန်းဂဏန်း ပြသမှု — ဥပမာ 100000 → 100,000"""
    try:
        if v is None or pd.isna(v):
            return "—"
        x = float(v)
        if math.isnan(x):
            return "—"
        s = f"{x:,.0f}"
        return s + suffix if suffix else s
    except (TypeError, ValueError):
        return str(v)

def _fmt_int_commas(n):
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return str(n)

def _styled_service_table_html(headers, rows, footer_cells=None, *, table_extra_class=""):
    """စားပွဲ/စာရင်း ဇယားကွက် — rows: တစ်ကြောင်းချင်းစီ၏ <td> အတွင်းထည့်မည့် HTML စာသားများ"""
    tc = "styled-table" + (f" {table_extra_class}" if table_extra_class else "")
    parts = [f'<table class="{tc}"><thead><tr>']
    for h in headers:
        parts.append(f"<th>{_he(h)}</th>")
    parts.append("</tr></thead><tbody>")
    for r in rows:
        parts.append("<tr>")
        for cell in r:
            parts.append(f"<td>{cell}</td>")
        parts.append("</tr>")
    if footer_cells:
        parts.append('<tr class="sub-total">')
        for cell in footer_cells:
            parts.append(f"<td>{cell}</td>")
        parts.append("</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)

def _st_dataframe_as_html_table(df):
    """st.table အစား HTML styled-table — Dark mode မှာ စာထင်ရှားရန်"""
    if df is None or df.empty:
        return
    headers = [str(c) for c in df.columns]
    rows_html = []
    for _, row in df.iterrows():
        cells = []
        for c in df.columns:
            v = row[c]
            cells.append(_he("—") if pd.isna(v) else _he(str(v)))
        rows_html.append(cells)
    st.markdown(
        _styled_service_table_html(headers, rows_html),
        unsafe_allow_html=True,
    )

def _receipt_thermal58_print_head_json():
    """၅၈မီလီ ထာမ်မယ် — ပရင့်ဒိုင်ယလော့မှာ သုံးသော <head> JSON စာကြောင်း"""
    css = (
        "@page{margin:2mm 3mm;}"
        "@media screen{body{box-sizing:border-box;font-family:Pyidaungsu,'Myanmar Text','Noto Sans Myanmar',sans-serif;"
        "width:100%!important;max-width:420px;margin:0 auto!important;padding:12px 10px 180px!important;"
        "font-size:18px;color:#000;line-height:1.55;-webkit-text-size-adjust:100%;}}"
        "@media print{body{box-sizing:border-box;font-family:Pyidaungsu,'Myanmar Text','Noto Sans Myanmar',sans-serif;"
        "width:48mm!important;max-width:100%!important;margin:0 auto!important;padding:1mm 0.5mm!important;"
        "font-size:16px;color:#000;line-height:1.5;"
        "-webkit-print-color-adjust:exact;print-color-adjust:exact;}"
        ".no-print{display:none!important;}}"
    )
    return json.dumps(
        "<meta charset=\"utf-8\"/>"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, maximum-scale=5\"/>"
        f"<style>{css}</style>"
    )

def _receipt_print_window_footer_json():
    """ပြေစာ about:blank တဘ်အောက် — မိုဘိုင်း Chrome မှာ ပရင့်မီနူး မပေါ်တတ်သဖြင့် ခလုတ် + မီနူးလမ်းညွှန် (onclick သုံး၊ </script> မသုံး)"""
    bar = (
        '<div class="no-print" style="position:fixed;bottom:0;left:0;right:0;'
        "padding:10px 10px max(14px,env(safe-area-inset-bottom));"
        "background:#e2e8f0;border-top:2px solid #64748b;text-align:center;z-index:2147483647;\">"
        '<button type="button" style="padding:14px 22px;font-size:17px;font-weight:700;touch-action:manipulation;'
        "border:none;border-radius:12px;background:#b91c1c;color:#fff;width:100%;max-width:300px;cursor:pointer\" "
        'onclick="window.print()" ontouchend="window.print()">'
        "🖨️ ဤနေရာမှ ပရင့် (Print)</button>"
        '<p style="font-size:11px;color:#1e293b;margin:10px 6px 2px;line-height:1.45;">'
        "မဖွင့်ရင် ဤတဘ်တွင် Chrome <b>⋮</b> → <b>Print</b> သို့ <b>Share</b> → <b>Print</b> မှ ရှာပါ။ "
        "ပရင်တာစာရင်းမှာ ချိတ်ထားသော စက်ကို ရွေးပါ။"
        "</p></div>"
    )
    return json.dumps(bar)

def _receipt_settlement_inner_html(customer_name, settle_day, line_items, sub_total, settled_by):
    """line_items: [(description, amount_float), ...] — ၅၈မီလီ ထာမ်မယ်ပြေစာ (ဖောင့် အရွယ်ကြီး — RawBT/ထာမ်မယ် ဖတ်ရလွယ်)"""
    parts = [
        '<div style="text-align:center;font-weight:bold;font-size:21px;margin-bottom:6px;">🍚 ကိုကျော် ထမင်းဆိုင်</div>',
        '<div style="text-align:center;font-size:18px;margin-bottom:10px;border-bottom:1px dashed #000;padding-bottom:5px;">ငွေရှင်းပြေစာ</div>',
        f'<div style="font-size:16px;margin:4px 0;">ငွေရှင်းနေ့: {_he(settle_day)}</div>',
        f'<div style="font-size:16px;margin:4px 0;">ဖောက်သည်: {_he(customer_name)}</div>',
        '<div style="margin-top:8px;font-size:16px;font-weight:bold;">မှာယူမှုများ</div>',
        '<table style="width:100%;border-collapse:collapse;margin-top:4px;table-layout:fixed;">',
    ]
    for desc, amt in line_items:
        parts.append("<tr>")
        parts.append(
            f'<td style="padding:5px 4px 5px 0;border-bottom:1px dotted #000;font-size:16px;word-break:break-word;vertical-align:top;width:58%;">{_he(desc)}</td>'
        )
        parts.append(
            f'<td style="padding:5px 0;border-bottom:1px dotted #000;text-align:right;white-space:nowrap;font-size:16px;font-variant-numeric:tabular-nums;vertical-align:top;width:42%;">{_fmt_amount(amt)} Ks</td>'
        )
        parts.append("</tr>")
    parts.append("</table>")
    parts.append(
        f'<div style="margin-top:8px;font-size:19px;font-weight:bold;text-align:right;border-top:2px solid #000;padding-top:8px;">'
        f"စုစုပေါင်း: {_fmt_amount(sub_total)} Ks</div>"
    )
    parts.append(f'<div style="margin-top:8px;font-size:15px;">ငွေရှင်းချသူ: {_he(settled_by)}</div>')
    parts.append(
        f'<div style="text-align:center;margin-top:12px;font-size:14px;color:#000;">'
        f"{_he(datetime.now().strftime('%Y-%m-%d %H:%M'))}</div>"
    )
    parts.append('<div style="text-align:center;margin-top:8px;font-size:16px;">ကျေးဇူးတင်ပါသည်</div>')
    return "".join(parts)

def _receipt_settlement_plain_text(customer_name, settle_day, line_items, sub_total, settled_by):
    """RawBT / မျှဝေမှု အတွက် စာသား ပြေစာ (HTML မဟုတ်)"""
    lines = [
        "ကိုကျော် ထမင်းဆိုင်",
        "ငွေရှင်းပြေစာ",
        f"ငွေရှင်းနေ့: {settle_day}",
        f"ဖောက်သည်: {customer_name}",
        "—",
    ]
    for i, (desc, amt) in enumerate(line_items, 1):
        lines.append(f"{i}. {desc}")
        lines.append(f"   {_fmt_amount(amt)} Ks")
    lines.append(f"စုစုပေါင်း: {_fmt_amount(sub_total)} Ks")
    lines.append(f"ငွေရှင်းချသူ: {settled_by}")
    lines.append(datetime.now().strftime("%Y-%m-%d %H:%M"))
    lines.append("ကျေးဇူးတင်ပါသည်")
    return "\n".join(lines)

def _receipt_settlement_plain_text_utf8(customer_name, settle_day, line_items, sub_total, settled_by):
    """
    RawBT UTF mode: Myanmar item names ကို မဖြုတ်ဘဲ UTF-8 ဖြင့်ပို့။
    Label မပေါ်တတ်သော printer/codepage တွေအတွက် English label ကိုပါ တွဲထည့်သည်။
    """
    lines = [
        "KO KYAW RICE SHOP / ကိုကျော် ထမင်းဆိုင်",
        "SETTLEMENT / ငွေရှင်းပြေစာ",
        f"Date: {settle_day}",
        f"Customer: {customer_name}",
        "---",
    ]
    for i, (desc, amt) in enumerate(line_items, 1):
        lines.append(f"{i}. {desc}")
        lines.append(f"   {_fmt_amount(amt)} Ks")
    lines.append("---")
    lines.append(f"TOTAL: {_fmt_amount(sub_total)} Ks")
    lines.append(f"By: {settled_by}")
    lines.append(datetime.now().strftime("%Y-%m-%d %H:%M"))
    lines.append("Thank you / ကျေးဇူးတင်ပါသည်")
    return "\n".join(lines)


def _receipt_settlement_plain_text_english(customer_name, settle_day, line_items, sub_total, settled_by):
    """English plain text version for thermal printing and avoid charset issues."""
    lines = [
        "KO KYAW RICE SHOP",
        "Payment Receipt",
        f"Date: {settle_day}",
        f"Customer: {customer_name}",
        "----",
    ]
    for desc, amt in line_items:
        lines.append(f"{desc}  {_fmt_amount(amt)} Ks")
    lines.append(f"Total: {_fmt_amount(sub_total)} Ks")
    lines.append(f"Settled by: {settled_by}")
    lines.append(datetime.now().strftime("%Y-%m-%d %H:%M"))
    lines.append("Thank you")
    return "\n".join(lines)


def _receipt_settlement_inner_html_english(customer_name, settle_day, line_items, sub_total, settled_by):
    """English receipt HTML (thermal — larger type for RawBT)"""
    parts = [
        '<div style="text-align:center;font-weight:bold;font-size:21px;margin-bottom:6px;">KO KYAW RICE SHOP</div>',
        '<div style="text-align:center;font-size:18px;margin-bottom:10px;border-bottom:1px dashed #000;padding-bottom:5px;">Payment Receipt</div>',
        f'<div style="font-size:16px;margin:4px 0;">Date: {_he(settle_day)}</div>',
        f'<div style="font-size:16px;margin:4px 0;">Customer: {_he(customer_name)}</div>',
        '<div style="margin-top:8px;font-size:16px;font-weight:bold;">Items</div>',
        '<table style="width:100%;border-collapse:collapse;margin-top:4px;table-layout:fixed;">',
    ]
    for desc, amt in line_items:
        parts.append("<tr>")
        parts.append(
            f'<td style="padding:5px 4px 5px 0;border-bottom:1px dotted #000;font-size:16px;word-break:break-word;vertical-align:top;width:58%;">{_he(desc)}</td>'
        )
        parts.append(
            f'<td style="padding:5px 0;border-bottom:1px dotted #000;text-align:right;white-space:nowrap;font-size:16px;font-variant-numeric:tabular-nums;vertical-align:top;width:42%;">{_fmt_amount(amt)} Ks</td>'
        )
        parts.append("</tr>")
    parts.append("</table>")
    parts.append(
        f'<div style="margin-top:8px;font-size:19px;font-weight:bold;text-align:right;border-top:2px solid #000;padding-top:8px;">Total: {_fmt_amount(sub_total)} Ks</div>'
    )
    parts.append(f'<div style="margin-top:8px;font-size:15px;">Settled by: {_he(settled_by)}</div>')
    parts.append(
        f'<div style="text-align:center;margin-top:12px;font-size:14px;color:#000;">{_he(datetime.now().strftime("%Y-%m-%d %H:%M"))}</div>'
    )
    parts.append('<div style="text-align:center;margin-top:8px;font-size:16px;">Thank you</div>')
    return "".join(parts)


def _ascii_only_printable(s: str, max_len: int = 48) -> str:
    """ထာမ်မယ် ESC/POS — ASCII printable သာ (မြန်မာ မပါရင် '-')"""
    t = "".join(c for c in str(s) if 32 <= ord(c) < 127)
    return (t.strip() or "-")[:max_len]

def _fmt_amount_thermal(v):
    """ထာမ်မယ် — ကော်မာ မသုံး၊ နံပါတ်သာ (code page မှားခြင်းလျှော့ရန်)"""
    try:
        if v is None or pd.isna(v):
            return "0"
        x = float(v)
        if math.isnan(x):
            return "0"
        return str(int(round(x)))
    except (TypeError, ValueError):
        return "0"

def _receipt_settlement_plain_text_thermal_ascii(
    customer_name, settle_day, line_items, sub_total, settled_by
):
    """
    RawBT / ထာမ်မယ် — ဘိုက် 0-127 သာ (ကော်မာ/Unicode မသုံး)။
    မြန်မာ UTF-8 ပို့ရင် /// စသည် ထွက်နိုင်သည်။
    """
    cref = hashlib.md5(str(customer_name).encode("utf-8")).hexdigest()[:10]
    lines = [
        "KO KYAW RICE SHOP",
        "SETTLEMENT",
        "Date " + str(settle_day),
        "Ref " + cref,
        "====",
    ]
    for i, (desc, amt) in enumerate(line_items, 1):
        d = _ascii_only_printable(desc, 28)
        if d == "-":
            d = "L" + str(i)
        amt_s = _fmt_amount_thermal(amt)
        lines.append(str(i) + ". " + d + "  " + amt_s)
    lines.append("====")
    lines.append("TOTAL " + _fmt_amount_thermal(sub_total))
    who = _ascii_only_printable(settled_by, 20)
    if who == "-":
        who = "staff"
    lines.append("By " + who)
    lines.append(datetime.now().strftime("%Y-%m-%d %H:%M"))
    lines.append("THANK YOU")
    body = "\r\n".join(lines)
    clean = "".join(c for c in body if ord(c) < 128)
    return clean

def _safe_receipt_filename(customer: str, day: str) -> str:
    """ဒေါင်းလုဒ် ဖိုင်အမည် — OS တားမြစ်အက္ခရာများ ဖယ်သည်"""
    base = re.sub(r'[\s<>:"/\\\\|?*\x00-\x1f]+', "_", str(customer)).strip("._")[:48]
    if not base:
        base = "receipt"
    return f"{base}_{day}.txt"

def _safe_receipt_stem(customer: str, day: str) -> str:
    """ဒေါင်းလုဒ် ဖိုင်အမည် အခြေခံ (နောက်ဆုံးအစိတ် မပါ)"""
    base = re.sub(r'[\s<>:"/\\\\|?*\x00-\x1f]+', "_", str(customer)).strip("._")[:48]
    if not base:
        base = "receipt"
    return f"{base}_{day}"

def _safe_receipt_download_basename(customer: str, day: str) -> str:
    """
    HTML/PNG ဒေါင်းလုဒ် အမည် — ASCII သာ (မြန်မာအမည်ပါလျှင် အချို့စက်မှာ .html.txt သို့မဟုတ် စာကြမ်းဖွင့်မှု ဖြစ်တတ်)
    """
    h = hashlib.md5(str(customer).encode("utf-8")).hexdigest()[:8]
    d = re.sub(r"[^\d\-]", "", str(day))[:10] or "day"
    return f"receipt_{h}_{d}"

def _receipt_html_file_bytes(html_doc: str) -> bytes:
    """HTML ဒေါင်းလုဒ် — UTF-8 သာ (BOM မပါ; အချို့စက်မှာ BOM က parse ပျက်စေနိုင်သည်)"""
    return html_doc.encode("utf-8")

def _ledger_receipt_view_key(view: dict) -> str:
    """ပြေစာပြမှု session — ရွေးချယ်မှု key တည်ငြိမ်ရန်"""
    s = f"{view.get('customer')}|{view.get('day')}|{view.get('total')}|{repr(view.get('lines'))}"
    return hashlib.md5(s.encode("utf-8")).hexdigest()[:16]

def _receipt_shareable_html_document(inner_body: str, title: str = "ငွေရှင်းပြေစာ") -> str:
    """
    ဖုန်းဖွင့် / ဒေါင်းလုဒ် — ပြည့်စုံ HTML။
    file:// ဖြင့် ဖွင့်ရင် ကွန်ရက်မလိုအောင် Google Font လင့် မသုံးပါ (မပါရင် စာမပေါ်/ခေါင်းပိုင်းသာ မြင်ရတတ်)။
    """
    t = html.escape(str(title), quote=True)
    return (
        "<!DOCTYPE html>\n<html lang=\"my\">\n<head>\n"
        '<meta charset="utf-8"/>\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1"/>\n'
        f"<title>{t}</title>\n"
        "<style>\n"
        "body { box-sizing: border-box; margin: 0 auto; padding: 10px 6px; max-width: 420px;\n"
        "  font-family: 'Pyidaungsu','Myanmar Text','Noto Sans Myanmar','Padauk',sans-serif;\n"
        "  font-size: 16px; color: #111; line-height: 1.5; background: #fff; }\n"
        "</style>\n</head>\n<body>\n"
        + inner_body
        + "\n</body>\n</html>"
    )

def _receipt_png_from_html(html_doc: str, width: int = 420) -> bytes | None:
    """
    html2image + headless Chrome သို့ Edge — PNG bytes။
    Streamlit components iframe မှ ဘရောင်ဇာ download ကို sandbox က ပိတ်ထားနိုင်သောကြောင့် ဒေါင်းလဒ်ကို st.download_button ဖြင့် ပေးသည်။
    """
    try:
        from html2image import Html2Image
    except ImportError:
        return None
    browsers = ("chrome", "edge")
    for br in browsers:
        try:
            with tempfile.TemporaryDirectory() as td:
                hti = Html2Image(
                    browser=br,
                    output_path=td,
                    size=(width, 4000),
                )
                hti.screenshot(
                    html_str=html_doc,
                    save_as="receipt.png",
                    size=(width, 4000),
                )
                p = os.path.join(td, "receipt.png")
                if os.path.isfile(p):
                    with open(p, "rb") as f:
                        data = f.read()
                    if len(data) > 80:
                        return data
        except Exception:
            continue
    return None

def render_settlement_receipt_browser_print(html_full_doc: str, component_id: str):
    """
    ဘရောင်ဇာ ပရင့်မီနူး တိုက်ရိုက်ခေါ် — ဒေါင်းလုဒ်/စာသားဖိုင် မသုံးပါ။
    (ဖွင့်ထားသော ပရင့်မီနူးမှ ထာမ်မယ် သို့ စာရင်းသွင်းထားသော ပရင်တာ ရွေးပါ)
    """
    # components iframe sandbox ကြောင့် popup ပိတ်နိုင်သောကြောင့် main DOM link နည်းသို့ပြောင်း
    safe_id = re.sub(r"[^a-zA-Z0-9_]", "_", component_id)[:48]
    auto_html = html_full_doc.replace(
        "</body>",
        (
            '<div style="position:fixed;bottom:10px;left:10px;right:10px;z-index:99999;text-align:center;">'
            '<button onclick="window.print()" '
            'style="padding:12px 18px;border:none;border-radius:10px;background:#b91c1c;color:#fff;font-weight:700;">'
            "🖨️ Print</button></div>"
            "<script>setTimeout(function(){try{window.print();}catch(e){}},700);</script></body>"
        ),
    )
    href = "data:text/html;charset=utf-8;base64," + base64.b64encode(auto_html.encode("utf-8")).decode("ascii")
    _href = html.escape(href, quote=True)
    st.markdown(
        f'<a id="setpr_{safe_id}" href="{_href}" target="_blank" '
        'style="display:inline-block;padding:14px 22px;font-size:16px;font-weight:700;border:none;'
        'border-radius:12px;background:#b91c1c;color:#fff !important;text-decoration:none;">'
        "🖨️ ဤနေရာမှ ပရင့်ထုတ်မည်</a>",
        unsafe_allow_html=True,
    )
    st.caption("Tab အသစ်ဖွင့်မလာရင် browser popup permission ကို Allow လုပ်ပြီး ထပ်နှိပ်ပါ။")

def _rawbt_uri_from_plain_text(txt: str, max_body_chars: int = 1800):
    """Android RawBT အက်ပ် — rawbt: စာကြောင်း (အရှည်ကန့်သတ်)"""
    t = (txt or "").strip()
    if len(t) > max_body_chars:
        t = t[: max_body_chars - 20].rstrip() + "\n...(truncated)"
    q = quote(t, safe="", encoding="utf-8", errors="strict")
    uri = "rawbt:" + q
    if len(uri) > 7000:
        return None
    return uri

def _rawbt_intent_uri(rawbt_uri: str):
    """Android Chrome fallback: intent:// style for RawBT app launch."""
    if not rawbt_uri or not str(rawbt_uri).startswith("rawbt:"):
        return None
    body = str(rawbt_uri)[len("rawbt:") :]
    return "intent:" + body + "#Intent;scheme=rawbt;package=ru.a402d.rawbtprinter;end"

def render_bluetooth_receipt_print_button(button_id: str, inner_body_html: str):
    """ပရင့်ဒိုင်ယလော့ — စနစ်ပရင့်မီနူးမှ ချိတ်ထားသော ထာမ်မယ် ရွေးထုတ်နိုင်"""
    inner_json = json.dumps(inner_body_html)
    head_json = _receipt_thermal58_print_head_json()
    foot_json = _receipt_print_window_footer_json()
    safe_id = re.sub(r"[^a-zA-Z0-9_]", "_", button_id)[:48]
    components.html(
        f"""
<div>
  <button id="prbtn_{safe_id}" type="button" style="padding:8px 14px;border-radius:8px;background:#0f172a;color:#fff;border:1px solid #334155;cursor:pointer;font-size:13px;">
    🖨️ ငွေရှင်းပြေစာ ပရင့်ထုတ်မည်
  </button>
</div>
<p style="font-size:11px;color:#64748b;margin:6px 0 0 0;max-width:320px;line-height:1.45;">
  အနီခလုတ် = ပရင့်မီနူး တိုက်ရိုက်ဖွင့် (မိုဘိုင်း အကြံပြု)။ မရရင် အောက်ခလုတ်ဖြင့် ပြေစာတဘ် ဖွင့်ပါ။
</p>
<button type="button" id="prprev_{safe_id}" style="margin-top:6px;padding:6px 12px;font-size:12px;border-radius:8px;border:1px solid #94a3b8;background:#fff;color:#334155;cursor:pointer;">
  ပြေစာတဘ်ဖွင့် ကြည့်မည်
</button>
<script>
(function() {{
  var btn = document.getElementById("prbtn_{safe_id}");
  var prev = document.getElementById("prprev_{safe_id}");
  if (!btn) return;
  var innerHtml = {inner_json};
  var docHead = {head_json};
  var foot = {foot_json};
  function buildDoc() {{
    return "<!DOCTYPE html><html><head>" + docHead + "</head><body style=\\"padding-bottom:170px;margin:0;\\">" + innerHtml + foot + "</body></html>";
  }}
  function printViaIframe() {{
    var iframe = document.createElement("iframe");
    iframe.setAttribute("title", "receipt-print");
    iframe.style.cssText = "position:fixed;top:0;left:0;width:100%;height:100%;border:0;opacity:0;z-index:2147483646;pointer-events:none;";
    document.body.appendChild(iframe);
    var d = iframe.contentDocument || iframe.contentWindow.document;
    d.open();
    d.write(buildDoc());
    d.close();
    var win = iframe.contentWindow;
    setTimeout(function() {{
      try {{ win.focus(); win.print(); }} catch(e) {{}}
    }}, 450);
    setTimeout(function() {{
      try {{ if (iframe.parentNode) iframe.parentNode.removeChild(iframe); }} catch(e) {{}}
    }}, 120000);
  }}
  function openTab() {{
    var w = window.open("", "_blank");
    if (!w) {{ alert("ပေါ့ပ်အပ်ကို ပိတ်မထားပါနဲ့"); return false; }}
    w.document.open();
    w.document.write(buildDoc());
    w.document.close();
    w.focus();
    return true;
  }}
  btn.addEventListener("click", function() {{ printViaIframe(); }});
  if (prev) prev.addEventListener("click", function() {{ openTab(); }});
}})();
</script>
        """,
        height=175,
    )

def show_recycle_bin():
    st.markdown("### 🗑️ Recycle Bin")
    st.caption(
        "မှာယူသည့်နေ့ (စာရင်းနေ့) အလိုက် အုပ်စုဖွဲ့ထားပါသည်။ **ဖောက်သည်တစ်ဦးချင်း = စားပွဲတစ်ခုအလိုက်** သဘောထားပါ။ "
        "**↩️ ဤဖောက်သည်အားလုံး ပြန်ထည့်** နှိပ်လိုက်တစ်ချက်နှင့် ထိုနေ့ထဲက ထိုအမည်ပါ မှတ်တမ်းအားလုံး ပြန်ရောက်ပါသည်။"
    )

    tdf = pd.read_excel(TRASH_FILE)
    if tdf.empty:
        st.info("Recycle Bin ဗလာဖြစ်နေပါသည်။")
        return

    tdf = tdf.copy()
    try:
        if "DeletedAt" in tdf.columns:
            tdf["_SortDel"] = pd.to_datetime(tdf["DeletedAt"], errors="coerce")
            tdf = tdf.sort_values(by="_SortDel", ascending=False, na_position="last")
    except Exception:
        pass

    tdf["_Day"] = pd.to_datetime(tdf["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
    tdf["_Day"] = tdf["_Day"].fillna("—")
    tdf["Name"] = tdf["Name"].fillna("(အမည်မဲ့)").astype(str)

    _ud = tdf["_Day"].unique().tolist()
    days = sorted([d for d in _ud if d != "—"], reverse=True) + [d for d in _ud if d == "—"]

    for day in days:
        day_df = tdf[tdf["_Day"] == day]
        n_lines = len(day_df)
        n_cust = day_df["Name"].nunique()
        day_total = float(day_df["Amount"].sum())
        dk = _recycle_key("day", day)
        with st.expander(f"📅 {day} · မှတ်တမ်း {n_lines} ကြောင်း · ဖောက်သည် {n_cust} ယောက် · {day_total:,.0f} Ks", key=f"rbx_d_{dk}"):
            for name, g in day_df.groupby("Name", sort=False):
                g_idx = g.index.tolist()
                sub_total = float(g["Amount"].sum())
                nk = _recycle_key(day, name)
                disp = g[["Description", "Amount", "DeletedAt"]].copy()
                if "DeletedAt" in disp.columns:
                    disp["DeletedAt"] = pd.to_datetime(disp["DeletedAt"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M")
                rows_html = []
                for _, rr in disp.iterrows():
                    rows_html.append(
                        [
                            _he(rr["Description"]),
                            _td_money(rr["Amount"]),
                            _he(rr["DeletedAt"]),
                        ]
                    )
                sub = float(g["Amount"].sum())
                foot = [
                    '<span style="text-align:right;font-weight:bold">စုစုပေါင်း</span>',
                    _td_money(sub),
                    "",
                ]
                st.markdown(f"##### 🪑 {_he(name)}")
                st.markdown(
                    _styled_service_table_html(
                        ["မှာယူမှု", "ပမာဏ (Ks)", "ဖျက်ချိန်"],
                        rows_html,
                        footer_cells=foot,
                    ),
                    unsafe_allow_html=True,
                )
                c1, c2 = st.columns(2)
                with c1:
                    if st.button(
                        f"↩️ {name} အားလုံး ပြန်ထည့် ({len(g_idx)} ကြောင်း)",
                        key=f"rbx_r_{nk}",
                        use_container_width=True,
                    ):
                        ok, detail = restore_trash_batch(g_idx)
                        if ok:
                            add_memory("agent", f"Recycle ပြန်ထည့်: {day} · {name} · {detail} ကြောင်း")
                            st.rerun()
                        else:
                            st.error("ပြန်ထည့်၍ မရပါ။")
                with c2:
                    if st.button(
                        f"❌ {name} အားလုံး အပြီးဖျက်",
                        key=f"rbx_p_{nk}",
                        use_container_width=True,
                    ):
                        if purge_trash_batch(g_idx):
                            st.rerun()
                st.divider()

def show_settlement_records_recycle_style(df_src, *, section_title="💵 ငွေရှင်းမှတ်တမ်း", show_caption=True, key_prefix="stl"):
    """ငွေရှင်းပြီး Paid လိုင်းများကို Recycle Bin လို — နေ့ → ဖောက်သည်(စာပွဲ) အလိုက် ပြခြင်း"""
    if df_src.empty:
        if section_title:
            st.subheader(section_title)
            st.info("ဤကာလတွင် ငွေရှင်းမှတ်တမ်း မရှိသေးပါ။")
        return
    df = df_src.copy()
    df["Date"] = pd.to_datetime(df["Date"], errors="coerce")
    s_set = pd.to_datetime(df["SettledAt"], errors="coerce") if "SettledAt" in df.columns else pd.Series(pd.NaT, index=df.index)
    df["_SettleDay"] = s_set.dt.strftime("%Y-%m-%d")
    na = s_set.isna()
    df.loc[na, "_SettleDay"] = df.loc[na, "Date"].dt.strftime("%Y-%m-%d")
    df["_SettleDay"] = df["_SettleDay"].fillna("—")
    df["Name"] = df["Name"].fillna("(အမည်မဲ့)").astype(str)

    _ud = df["_SettleDay"].unique().tolist()
    days = sorted([d for d in _ud if d != "—"], reverse=True) + [d for d in _ud if d == "—"]

    if section_title:
        st.subheader(section_title)
    if show_caption:
        st.caption(
            "Recycle Bin နည်းတူ **ငွေရှင်းသည့်နေ့** ပြီးမှ **ဖောက်သည် အမည် (စာပွဲတစ်ခုချင်း)** ဖြင့် အုပ်စုဖွဲ့ထားပါသည်။ "
            "**ငွေရှင်းချသူ** မှာ ဝန်ထမ်းအမည် (သို့မဟုတ် Agent) ဖြစ်သည်။ "
            "ဖောက်သည်တစ်ဦးချင်းအောက် **🖨️ ငွေရှင်းပြေစာ ပရင့်ထုတ်မည်** ဖြင့် Bluetooth ပရင်တာ (သို့) စာရွက်သို့ ထုတ်နိုင်ပါသည်။"
        )

    for day in days:
        day_df = df[df["_SettleDay"] == day]
        n_lines = len(day_df)
        n_cust = day_df["Name"].nunique()
        day_total = float(day_df["Amount"].sum())
        dk = _recycle_key(key_prefix, "stl_day", day)
        with st.expander(
            f"📅 {day} · စာပွဲ {n_cust} ခွင် · မှတ်တမ်း {n_lines} ကြောင်း · {day_total:,.0f} Ks",
            key=f"{key_prefix}_d_{dk}",
        ):
            for name, g in day_df.groupby("Name", sort=False):
                sub_total = float(g["Amount"].sum())
                nk = _recycle_key(key_prefix, "stl", day, name)
                st.markdown(f"##### 🪑 {name} · စုစုပေါင်း {sub_total:,.0f} Ks · {len(g)} ကြောင်း")
                disp = g[["Description", "Amount", "Date"]].copy()
                disp["Date"] = pd.to_datetime(disp["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
                if "SettledBy" in g.columns:
                    sb = g["SettledBy"].fillna("").astype(str).str.strip()
                    disp["ငွေရှင်းချသူ"] = sb.replace("", "—").replace("nan", "—")
                else:
                    disp["ငွေရှင်းချသူ"] = "—"
                rows_html = []
                for _, rr in disp.iterrows():
                    rows_html.append(
                        [
                            _he(rr["Description"]),
                            _td_money(rr["Amount"]),
                            _he(rr["Date"]),
                            _he(rr["ငွေရှင်းချသူ"]),
                        ]
                    )
                foot = [
                    '<span style="text-align:right;font-weight:bold">စုစုပေါင်း</span>',
                    _td_money(sub_total),
                    "",
                    "",
                ]
                st.markdown(
                    _styled_service_table_html(
                        ["မှာယူမှု", "ပမာဏ (Ks)", "မှာယူသည့်နေ့", "ငွေရှင်းချသူ"],
                        rows_html,
                        footer_cells=foot,
                    ),
                    unsafe_allow_html=True,
                )
                line_items = [(str(rr["Description"]), float(rr["Amount"])) for _, rr in disp.iterrows()]
                try:
                    _sb = disp["ငွေရှင်းချသူ"].fillna("").astype(str).str.strip()
                    _sb = _sb[(_sb != "") & (_sb != "—") & (_sb.str.lower() != "nan")]
                    settled_by_str = _sb.iloc[0] if len(_sb) else "—"
                except Exception:
                    settled_by_str = "—"
                _print_id = "p" + _recycle_key(key_prefix, "recv", day, name)
                _recv_html = _receipt_settlement_inner_html(
                    str(name), str(day), line_items, sub_total, settled_by_str
                )
                render_bluetooth_receipt_print_button(_print_id, _recv_html)
                st.divider()

def show_unpaid_glance_summary(df_src, *, title, caption=None):
    """မရှင်းရသေးငွေကို ဖောက်သည်အလိုက် စာရင်းဇယားတစ်ခုတည်းဖြင့် အမြင်ပေါ့ပေါ့ ပြသည်။"""
    if df_src is None or df_src.empty:
        return
    st.markdown(f"#### {title}")
    if caption:
        st.caption(caption)
    g = df_src.groupby("Name", sort=False)["Amount"].sum().sort_values(ascending=False)
    tot = float(g.sum())
    rows_html = [[_he(str(n)), _td_money(v)] for n, v in g.items()]
    foot = [
        f'<span style="font-weight:600">{_he("➡️ စုစုပေါင်း")}</span>',
        _td_money(tot),
    ]
    st.markdown(
        _styled_service_table_html(
            ["ဖောက်သည် / စာရင်း", "ကျန်ငွေ (Ks)"],
            rows_html,
            footer_cells=foot,
        ),
        unsafe_allow_html=True,
    )

def show_dashboard():
    st.markdown("### 📊 Dashboard")

    df_ledger = pd.read_excel(LEDGER_FILE)
    if "SettledAt" not in df_ledger.columns:
        df_ledger["SettledAt"] = pd.NaT
    if "SettledBy" not in df_ledger.columns:
        df_ledger["SettledBy"] = ""
    df_paid = df_ledger[df_ledger['Status'] == 'Paid'].copy()
    df_unpaid = df_ledger[df_ledger['Status'] == 'Unpaid']

    if not df_unpaid.empty:
        show_unpaid_glance_summary(
            df_unpaid,
            title="📌 မရှင်းရသေးငွေ — အမြင်ပေါ့ပေါ့",
            caption="ဥပမာ ဓာတ်ဆီရောင်းရစာရင်း၊ အပြင်ဝိုင်း ၁/၂ စသည့် ဖောက်သည်တစ်ဦးချင်း စုစုပေါင်း။ အသေးစိတ် ကြောင်းတွေ့ကို 📋 Ledger မှာ နာမည်နှိပ်ပြီး ကြည့်ပါ။",
        )
        st.divider()

    col_d1, col_d2 = st.columns([2, 1])
    with col_d1:
        date_options = ["ယနေ့", "ဒီတစ်ပတ်", "ဒီလ", "လွန်ခဲ့သော ၃ လ", "တစ်နှစ်", "အားလုံး"]
        date_range = st.selectbox("အချိန်ကာလ", date_options, key="dashboard_date_range")
        st.caption("ငွေရှင်းပြီးမှတ်တမ်းများကို **ငွေရှင်းသည့်နေ့** (သို့မဟုတ် အဟောင်း စာရင်း၏ မှာယူသည့်နေ့) ဖြင့် စိစစ်ပါသည်။")

    if not df_paid.empty:
        df_paid['Date'] = pd.to_datetime(df_paid['Date'], errors='coerce')
        s_set = pd.to_datetime(df_paid['SettledAt'], errors='coerce') if 'SettledAt' in df_paid.columns else pd.Series(pd.NaT, index=df_paid.index)
        df_paid['_ReportDay'] = s_set.dt.date.where(s_set.notna(), df_paid['Date'].dt.date)

        now = datetime.now()
        today_d = now.date()
        if date_range == "ယနေ့":
            filtered = df_paid[df_paid['_ReportDay'] == today_d]
        elif date_range == "ဒီတစ်ပတ်":
            cut = (now - timedelta(days=7)).date()
            filtered = df_paid[df_paid['_ReportDay'] >= cut]
        elif date_range == "ဒီလ":
            cut = now.replace(day=1).date()
            filtered = df_paid[df_paid['_ReportDay'] >= cut]
        elif date_range == "လွန်ခဲ့သော ၃ လ":
            cut = (now - timedelta(days=90)).date()
            filtered = df_paid[df_paid['_ReportDay'] >= cut]
        elif date_range == "တစ်နှစ်":
            cut = (now - timedelta(days=365)).date()
            filtered = df_paid[df_paid['_ReportDay'] >= cut]
        else:
            filtered = df_paid

        col1, col2, col3, col4 = st.columns(4)
        total_revenue = filtered['Amount'].sum() if not filtered.empty else 0
        total_orders = len(filtered) if not filtered.empty else 0
        unpaid_total = df_unpaid['Amount'].sum() if not df_unpaid.empty else 0
        avg_order = total_revenue / total_orders if total_orders > 0 else 0

        with col1:
            st.metric("💰 စုစုပေါင်းဝင်ငွေ", f"{total_revenue:,.0f} Ks")
        with col2:
            st.metric("📝 မှာယူမှုအရေအတွက်", _fmt_int_commas(total_orders))
        with col3:
            st.metric("⏳ ရရန်ကျန်ငွေ", f"{unpaid_total:,.0f} Ks")
        with col4:
            st.metric("📊 ပျမ်းမျှမှာယူမှု", f"{avg_order:,.0f} Ks")

        st.divider()

        st.subheader("📈 နေ့စဉ်ဝင်ငွေ (ငွေရှင်းနေ့အလိုက်)")
        if not filtered.empty:
            daily = filtered.groupby('_ReportDay')['Amount'].sum().reset_index()
            daily.columns = ['ရက်', 'ဝင်ငွေ']
            daily['ရက်'] = daily['ရက်'].astype(str)
            st.bar_chart(daily.set_index('ရက်'))

        show_settlement_records_recycle_style(filtered, key_prefix="dash_stl")

        st.subheader("🏆 ရောင်းရဆုံး အစားအစာများ")
        if not filtered.empty:
            filtered['ItemName'] = filtered['Description'].apply(
                lambda x: re.sub(r'\s*\(\d+\)$', '', x) if isinstance(x, str) else x
            )
            top_items = filtered.groupby('ItemName')['Amount'].sum().sort_values(ascending=False).head(10)

            if not top_items.empty:
                top_df = pd.DataFrame({
                    'အစားအစာ': top_items.index,
                    'စုစုပေါင်းဝင်ငွေ': top_items.values
                })
                top_df['စုစုပေါင်းဝင်ငွေ'] = top_df['စုစုပေါင်းဝင်ငွေ'].apply(lambda x: f"{x:,.0f} Ks")
                _st_dataframe_as_html_table(top_df)

        st.subheader("📅 လစဉ်ဝင်ငွေ အခြေအနေ (ငွေရှင်းနေ့အလိုက်)")
        if not filtered.empty:
            filtered['_လ'] = pd.to_datetime(filtered['_ReportDay']).dt.strftime('%Y-%m')
            monthly = filtered.groupby('_လ')['Amount'].sum().reset_index()
            monthly.columns = ['လ', 'ဝင်ငွေ']
            st.line_chart(monthly.set_index('လ'))

        st.subheader("📆 လစဉ် ငွေရှင်းမှတ်တမ်း")
        if not filtered.empty:
            for month in sorted(filtered['_လ'].unique(), reverse=True):
                mdf = filtered[filtered['_လ'] == month]
                tot_m = mdf['Amount'].sum()
                with st.expander(f"🗓️ {month} — စုစုပေါင်း {tot_m:,.0f} Ks · {len(mdf)} မှတ်တမ်း", key=f"mset_{month}"):
                    show_settlement_records_recycle_style(
                        mdf, section_title=None, show_caption=False, key_prefix=f"m_{month}_stl"
                    )

    else:
        st.info("ငွေရှင်းပြီးသော စာရင်း မရှိသေးပါ။")

def show_manual_entry():
    st.markdown("### 📝 လက်ဖြင့်မှာယူမှုသွင်းရန်")
    _dm_manual = st.session_state.get("dark_mode", False)

    st.markdown("#### ➕ စာရင်းအသစ်ထည့်ရန်")
    st.caption(
        "တူညီသော အစားအစာနှင့် ဈေးနှုန်းဖြစ်စေ **တစ်ခါသွင်းတိုင်း** စာရင်းတွင် ကြောင်းတစ်ကြောင်းစီ ခွဲထည့်ပါသည်။"
    )

    try:
        c_list_m = pd.read_excel(MASTER_FILE, sheet_name='Customers')['CustomerName'].tolist()
    except Exception:
        c_list_m = []

    try:
        menu_df = pd.read_excel(MASTER_FILE, sheet_name='Menu')
    except Exception:
        menu_df = pd.DataFrame(columns=['Item', 'Price'])

    col_a, col_b, col_c = st.columns(3)

    with col_a:
        sel_name = st.selectbox("ဖောက်သည်အမည်", ["-- ရွေးရန် --"] + c_list_m if c_list_m else ["-- ရွေးရန် --"])

    with col_b:
        sel_food = st.selectbox("အစားအစာ", ["-- ရွေးရန် --"] + menu_df['Item'].tolist() if not menu_df.empty else ["-- ရွေးရန် --"])

        if sel_food != "-- ရွေးရန် --" and not menu_df.empty:
            price_row = menu_df[menu_df['Item'] == sel_food]
            if not price_row.empty:
                price = float(price_row["Price"].values[0])
                st.session_state.selected_price = price
                if _dm_manual:
                    st.markdown(
                        f'<div style="background:#422006;color:#fef9c3;border-left:4px solid #fbbf24;'
                        f'padding:10px 14px;border-radius:8px;margin-top:6px;font-weight:600">'
                        f"💰 ဈေးနှုန်း: {price:,.0f} Ks</div>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<div style="background:#FEF3C7;color:#78350f;border-left:4px solid #F59E0B;'
                        f'padding:8px 12px;border-radius:8px;margin-top:5px">'
                        f"💰 ဈေးနှုန်း: {price:,.0f} Ks</div>",
                        unsafe_allow_html=True,
                    )
            else:
                st.session_state.selected_price = 0
        else:
            st.session_state.selected_price = 0

    with col_c:
        qty = st.number_input("အရေအတွက်", min_value=1, value=1)

    if sel_food != "-- ရွေးရန် --" and st.session_state.selected_price > 0:
        total_amount = qty * st.session_state.selected_price
        if _dm_manual:
            st.markdown(
                f'<div style="background:#14532d;color:#dcfce7;border:1px solid #22c55e;'
                f'padding:10px 14px;border-radius:8px;margin-top:6px;text-align:center;font-weight:600">'
                f"📊 စုစုပေါင်း: {total_amount:,.0f} Ks</div>",
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                f'<div style="background:#E6F7E6;color:#14532d;padding:8px 12px;border-radius:8px;'
                f'margin-top:5px;text-align:center;font-weight:500">'
                f"📊 စုစုပေါင်း: {total_amount:,.0f} Ks</div>",
                unsafe_allow_html=True,
            )

    if st.button("➕ မှာယူမှုသွင်းမည်", use_container_width=True):
        if sel_name != "-- ရွေးရန် --" and sel_food != "-- ရွေးရန် --" and not menu_df.empty and st.session_state.selected_price > 0:
            save_to_ledger(sel_name, f"{sel_food} ({qty})", qty * st.session_state.selected_price)
            st.success(f"✅ {sel_name} — {sel_food} × {qty} = {qty * st.session_state.selected_price:,.0f} Ks သွင်းပြီးပါပြီ။")
            add_memory("user", f"မှာယူမှု: {sel_name} - {sel_food} × {qty}")
            add_memory("agent", f"သွင်းပြီး: {sel_name} - {sel_food} × {qty} = {qty * st.session_state.selected_price:,.0f} Ks")
            st.rerun()
        elif sel_name == "-- ရွေးရန် --":
            st.warning("ဖောက်သည်နာမည် ရွေးပါ။")
        elif sel_food == "-- ရွေးရန် --":
            st.warning("အစားအစာ ရွေးပါ။")
        else:
            st.error("ဈေးနှုန်း မတွေ့ပါ။ Menu မှာ ဈေးနှုန်းထည့်ပါ။")

    st.divider()
    st.markdown("#### 🪑 ယနေ့ စားပွဲစာရင်း (မရှင်းရသေး)")
    st.caption("ဖောက်သည်တစ်ဦးချင်း = စားပွဲတစ်ခု။ ဇယားကွက်ဖြင့် ပြထားပါသည်။")

    today = datetime.now().strftime("%Y-%m-%d")
    try:
        df_ledger = pd.read_excel(LEDGER_FILE)
        df_ledger["_Day"] = pd.to_datetime(df_ledger["Date"], errors="coerce").dt.strftime("%Y-%m-%d")
        day_df = df_ledger[
            (df_ledger["_Day"] == today) & (df_ledger["Status"].astype(str).str.strip() == "Unpaid")
        ]
    except Exception:
        day_df = pd.DataFrame()

    if day_df.empty:
        if st.session_state.get("dark_mode"):
            st.markdown(
                '<div style="padding:14px 16px;border-radius:10px;background:#1e293b;'
                'border:1px solid #475569;color:#e2e8f0;font-size:1rem">'
                "ℹ️ ယနေ့ မှာယူမှုမှတ်တမ်း မရှိသေးပါ။</div>",
                unsafe_allow_html=True,
            )
        else:
            st.info("ယနေ့ မှာယူမှုမှတ်တမ်း မရှိသေးပါ။")
    else:
        for name, g in day_df.groupby("Name", sort=False):
            sub = float(g["Amount"].sum())
            rows_html = []
            for _, rr in g.iterrows():
                dshow = str(rr["_Day"]) if pd.notna(rr["_Day"]) else today
                rows_html.append(
                    [
                        _he(dshow),
                        _he(rr["Description"]),
                        _td_money(rr["Amount"]),
                    ]
                )
            foot = [
                "",
                '<span style="text-align:right;font-weight:bold">စုစုပေါင်း</span>',
                _td_money(sub),
            ]
            st.markdown(f"##### 🪑 {_he(str(name))}")
            st.markdown(
                _styled_service_table_html(
                    ["နေ့စွဲ", "မှာယူမှု", "ပမာဏ"],
                    rows_html,
                    footer_cells=foot,
                ),
                unsafe_allow_html=True,
            )

def show_purchase_entry(*, key_prefix="pur_tab_", compact=False):
    if compact:
        st.markdown("#### 🛒 အဝယ် စာရင်း သွင်းရန်")
    else:
        st.markdown("### 🛒 အဝယ် စာရင်း သွင်းရန်")
    st.caption(
        "**Master Data** ထဲက ဝယ်ပစ္စည်းစာရင်းမှ ရွေးနိုင်ပါသည် (Menu လိုပုံစံ)။ "
        "စာရင်းမရှိသေးရင် ကိုယ်တိုင် ရေးလို့ရပြီး Master Data မှာ ပစ္စည်းအမည် နှင့် မှတ်သားဈေး ထည့်ထားလျှင် နောက်တစ်ကြိမ် ရွေးယူလွယ်ပါသည်။"
    )

    cat_df = read_master_sheet_safe("PurchaseCatalog", ["ItemName", "RefPrice"])
    raw_items = cat_df["ItemName"].dropna().astype(str).str.strip()
    raw_items = raw_items[raw_items != ""].unique().tolist()
    p_opts = [_PUR_CUSTOM] + sorted(raw_items)

    p_sel = st.selectbox("ဝယ်ပစ္စည်း", p_opts, key=f"{key_prefix}pcat_sel")
    if p_sel == _PUR_CUSTOM:
        col1, col2 = st.columns(2)
        with col1:
            p_item = st.text_input(
                "ပစ္စည်း နာမည် (ကိုယ်တိုင်)",
                placeholder="ဥပမာ ကြက်ဥ တစ်လုံး",
                key=f"{key_prefix}item",
            )
        with col2:
            p_price = st.number_input(
                "ဝယ်ဈေးနှုန်း (Ks)",
                min_value=0.0,
                value=0.0,
                step=100.0,
                key=f"{key_prefix}price",
            )
    else:
        p_item = p_sel
        row = cat_df[cat_df["ItemName"].astype(str).str.strip() == p_sel]
        ref = 0.0
        if not row.empty:
            try:
                ref = float(row["RefPrice"].iloc[0])
            except (TypeError, ValueError):
                ref = 0.0
            if math.isnan(ref):
                ref = 0.0
        st.caption(f"📌 Master မှတ်သားဈေး: **{ref:,.0f} Ks** — လက်ရှိဝယ်ဈေး ပြောင်းပြင်နိုင်ပါသည်။")
        p_price = st.number_input(
            "ဝယ်ဈေးနှုန်း (Ks)",
            min_value=0.0,
            value=ref,
            step=100.0,
            key=f"{key_prefix}price",
        )

    if st.button("➕ အဝယ် စာရင်းသွင်းမည်", use_container_width=True, key=f"{key_prefix}save"):
        ok, err = save_purchase_record(p_item, p_price)
        if ok:
            add_memory("agent", f"အဝယ်: {p_item.strip()} = {p_price:,.0f} Ks")
            st.success(f"✅ သိမ်းဆည်းပြီးပါပြီ — {p_item.strip()} · {p_price:,.0f} Ks")
            st.rerun()
        else:
            st.error(err)

    st.divider()
    if compact:
        st.markdown("##### 📜 လတ်တလော အဝယ်မှတ်တမ်း")
    else:
        st.subheader("📜 လတ်တလော အဝယ်မှတ်တမ်း")
    st.caption("အောက်ပါ ✏️ ဖြင့် **နေ့စွဲ / ပစ္စည်းအမည် / ဝယ်ဈေး** ပြင်ဆင်နိုင်ပါသည်။")
    try:
        pdf_full = pd.read_excel(PURCHASE_FILE)
    except Exception:
        pdf_full = pd.DataFrame(columns=["Date", "ItemName", "Price"])
    if pdf_full.empty:
        st.info("အဝယ် မှတ်တမ်း မရှိသေးပါ။")
        return
    disp = pdf_full.iloc[::-1].head(80)
    view = disp[["Date", "ItemName", "Price"]].copy()
    view.columns = ["နေ့စွဲ", "ပစ္စည်းအမည်", "ဝယ်ဈေး (Ks)"]
    view["ဝယ်ဈေး (Ks)"] = view["ဝယ်ဈေး (Ks)"].map(_fmt_amount)
    st.dataframe(view, use_container_width=True, hide_index=True)

    for idx, row in disp.iterrows():
        short = str(row["ItemName"])[:32] + ("…" if len(str(row["ItemName"])) > 32 else "")
        with st.expander(f"✏️ ပြင်မည် — {short}", key=f"{key_prefix}_pur_{idx}"):
            rd = _ledger_cell_to_date(row["Date"])
            ed_d = st.date_input("နေ့စွဲ", value=rd, key=f"{key_prefix}_pud_{idx}")
            ed_item = st.text_input("ပစ္စည်းအမည်", value=str(row["ItemName"]), key=f"{key_prefix}_pui_{idx}")
            ed_pr = st.number_input(
                "ဝယ်ဈေး (Ks)",
                min_value=0.0,
                value=float(row["Price"]),
                step=100.0,
                key=f"{key_prefix}_pup_{idx}",
            )
            if st.button("💾 ပြင်ဆင်ချက် သိမ်းမည်", key=f"{key_prefix}_pus_{idx}"):
                ok, err = update_purchase_row(idx, ed_d.strftime("%Y-%m-%d"), ed_item, ed_pr)
                if ok:
                    add_memory("agent", f"အဝယ်ပြင်ပြီး: {ed_item} = {ed_pr:,.0f} Ks")
                    st.success("သိမ်းဆည်းပြီးပါပြီ။")
                    st.rerun()
                else:
                    st.error(err)

def show_payable_credit_ui(*, key_prefix="pay_tab_", compact=False):
    if compact:
        st.markdown("#### 🧾 ပေးရမည့် အကြွေး မှတ်တမ်း")
    else:
        st.markdown("### 🧾 ပေးရမည့် အကြွေး မှတ်တမ်း")
    st.caption(
        "**Master Data** မှ ဈေးသမား ရွေးနိုင်ပါသည်။ အကြွေး မှတ်ပြီးနောက် **💵 ငွေရှင်းမည်** တွင် သူ့နာမည်ရွေးပြီး တစ်ချက်နှိပ်ဖြင့် အားလုံး ရှင်းနိုင်သည်။ "
        "အသေးစိတ်တွင် လိုင်းတစ်ကြောင်းချင်း **ရှင်း** သို့မဟုတ် **ပြင်** လို့ရပါသည်။"
    )

    cr_df = read_master_sheet_safe("Creditors", ["CreditorName"])
    cr_names = cr_df["CreditorName"].dropna().astype(str).str.strip()
    cr_names = cr_names[cr_names != ""].unique().tolist()
    cr_opts = [_PAY_CRED_CUSTOM] + sorted(cr_names)

    c_sel = st.selectbox("ပေးရမည့်သူ", cr_opts, key=f"{key_prefix}csel")
    if c_sel == _PAY_CRED_CUSTOM:
        cr = st.text_input("ပေးရမည့်သူ (ကိုယ်တိုင် ရေး)", placeholder="ဥပမာ ကိုစိုး ဈေးသမား", key=f"{key_prefix}cr")
    else:
        cr = c_sel

    col1, col2 = st.columns(2)
    with col1:
        desc = st.text_input("မှတ်ချက် (ဝယ်ပစ္စည်း)", placeholder="ဥပမာ ဆန်အုပ် ၁ စာ", key=f"{key_prefix}desc")
    with col2:
        amt = st.number_input("အကြွေးပမာဏ (Ks)", min_value=0.0, value=0.0, step=500.0, key=f"{key_prefix}amt")
        pday = st.date_input("နေ့စွဲ", value=datetime.now().date(), key=f"{key_prefix}dt")

    if st.button("➕ အကြွေး မှတ်မည်", use_container_width=True, key=f"{key_prefix}add"):
        ok, err = save_payable_record(cr, desc, amt, pday.strftime("%Y-%m-%d"))
        if ok:
            add_memory("agent", f"အကြွေး: {cr.strip()} = {amt:,.0f} Ks")
            st.success(f"✅ သိမ်းဆည်းပြီးပါပြီ — {cr.strip()} · {amt:,.0f} Ks")
            st.rerun()
        else:
            st.error(err)

    try:
        df = _payable_read()
    except Exception:
        df = pd.DataFrame(columns=["Date", "CreditorName", "Description", "Amount", "Status", "SettledAt", "SettledBy"])

    unpaid = df[df["Status"] == "Unpaid"].copy() if not df.empty else df
    who_user = (st.session_state.user or {}).get("name") or "—"

    st.divider()
    if compact:
        st.markdown("##### 💵 အကြွေး ငွေရှင်းမည်")
    else:
        st.subheader("💵 အကြွေး ငွေရှင်းမည်")
    st.caption(
        "မရှင်းရသေးသော **ဈေးသမား တစ်ဦး** ကို ရွေးပြီး **တစ်ချက်နှိပ်ဖြင့်** ထိုသူ့ အကြွေးလိုင်းများအားလုံး ရှင်းပြီးအဖြစ် သိမ်းပါသည်။"
    )

    if unpaid.empty:
        st.info("ရှင်းရန် ကျန်ရှိသော အကြွေး မရှိသေးပါ။")
    else:
        uflat = unpaid.copy()
        uflat["CreditorName"] = uflat["CreditorName"].fillna("(အမည်မဲ့)").astype(str).str.strip()
        creditors_u = sorted(uflat["CreditorName"].unique().tolist())
        settle_opts = ["-- ငွေရှင်းမည့်သူ ရွေးပါ --"] + creditors_u
        settle_pick = st.selectbox(
            "ငွေရှင်းမည့်သူ",
            settle_opts,
            key=f"{key_prefix}_settle_pick",
        )
        if settle_pick != settle_opts[0]:
            sub = float(uflat.loc[uflat["CreditorName"] == settle_pick, "Amount"].sum())
            nlines = int((uflat["CreditorName"] == settle_pick).sum())
            st.metric("ဤသူ့ ကျန်အကြွေး", f"{sub:,.0f} Ks", delta=f"{nlines} ကြောင်း")
            st.caption("အောက်ပါ ခလုတ်ဖြင့် ထိုလိုင်းအားလုံး ရှင်းပြီးသတ်မှတ်မည်။")
        if st.button(
            "✅ ငွေရှင်းမည် (ရွေးထားသူ၏ အကြွေးအားလုံး)",
            use_container_width=True,
            key=f"{key_prefix}_settle_btn",
        ):
            if settle_pick == settle_opts[0]:
                st.warning("ငွေရှင်းမည့်သူ ကို အပေါ်မှ ရွေးပါ။")
            elif settle_payable_creditor_all(settle_pick, settled_by=who_user):
                add_memory("agent", f"အကြွေးငွေရှင်း: {settle_pick}")
                st.success(f"✅ {settle_pick} ၏ အကြွေးအားလုံး ရှင်းပြီးပါပြီ။")
                st.rerun()

    st.divider()
    if compact:
        st.markdown("##### ⏳ မရှင်းရသေးသော အကြွေး အသေးစိတ်")
    else:
        st.subheader("⏳ မရှင်းရသေးသော အကြွေး အသေးစိတ်")

    if not unpaid.empty:
        st.metric("ပေးရမည့် စုစုပေါင်း (အားလုံး)", f"{float(unpaid['Amount'].sum()):,.0f} Ks")
        unpaid = unpaid.copy()
        unpaid["CreditorName"] = unpaid["CreditorName"].fillna("(အမည်မဲ့)").astype(str)
        for creditor, g in unpaid.groupby("CreditorName", sort=False):
            total = float(g["Amount"].sum())
            ek = _recycle_key(key_prefix, "pay", creditor)
            with st.expander(
                f"🏪 {creditor} · ကျန်ငွေ {total:,.0f} Ks · {len(g)} ကြောင်း",
                key=f"{key_prefix}_ex_{ek}",
            ):
                if len(g) > 1:
                    if st.button(
                        f"✅ {creditor} အားလုံး ရှင်းမည်",
                        key=f"{key_prefix}_all_{ek}",
                        use_container_width=True,
                    ):
                        if settle_payable_creditor_all(creditor, settled_by=who_user):
                            add_memory("agent", f"အကြွေးရှင်း: {creditor} · {len(g)} ကြောင်း")
                            st.rerun()
                for idx, row in g.iterrows():
                    short = str(row["Description"])[:28] + ("…" if len(str(row["Description"])) > 28 else "")
                    with st.expander(
                        f"✏️ {row['Date']} · {short} — {float(row['Amount']):,.0f} Ks",
                        key=f"{key_prefix}_pex_{ek}_{idx}",
                    ):
                        rd = _ledger_cell_to_date(row["Date"])
                        ed_d = st.date_input("နေ့စွဲ", value=rd, key=f"{key_prefix}_pxd_{ek}_{idx}")
                        ed_cr = st.text_input(
                            "ပေးရမည့်သူ",
                            value=str(row["CreditorName"]),
                            key=f"{key_prefix}_pxc_{ek}_{idx}",
                        )
                        ed_ds = st.text_input(
                            "မှတ်ချက်",
                            value=str(row["Description"]),
                            key=f"{key_prefix}_pxs_{ek}_{idx}",
                        )
                        ed_am = st.number_input(
                            "အကြွေးပမာဏ (Ks)",
                            min_value=0.0,
                            value=float(row["Amount"]),
                            step=100.0,
                            key=f"{key_prefix}_pxa_{ek}_{idx}",
                        )
                        bx1, bx2 = st.columns(2)
                        with bx1:
                            if st.button("💾 ပြင်ဆင်ချက် သိမ်းမည်", key=f"{key_prefix}_pxsv_{ek}_{idx}"):
                                ok, er = update_payable_row(
                                    idx, ed_d.strftime("%Y-%m-%d"), ed_cr, ed_ds, ed_am
                                )
                                if ok:
                                    add_memory("agent", f"အကြွေးပြင်ပြီး: {ed_cr} · {ed_am:,.0f} Ks")
                                    st.success("သိမ်းဆည်းပြီးပါပြီ။")
                                    st.rerun()
                                else:
                                    st.error(er)
                        with bx2:
                            if st.button("✅ ရှင်းမည်", key=f"{key_prefix}_pxst_{ek}_{idx}"):
                                if settle_payable_row(idx, settled_by=who_user):
                                    add_memory(
                                        "agent",
                                        f"အကြွေးရှင်း: {creditor} · {float(row['Amount']):,.0f} Ks",
                                    )
                                    st.rerun()

    st.divider()
    if compact:
        st.markdown("##### ✅ လတ်တလော ရှင်းပြီး အကြွေး")
    else:
        st.subheader("✅ လတ်တလော ရှင်းပြီး အကြွေး")
    paid = df[df["Status"] == "Paid"].copy() if not df.empty else df
    if paid.empty:
        st.caption("ရှင်းပြီးမှတ်တမ်း မရှိသေးပါ။")
    else:
        paid = paid.iloc[::-1].reset_index(drop=True).head(50)
        pv = paid[["Date", "CreditorName", "Description", "Amount", "SettledAt", "SettledBy"]].copy()
        _st = pd.to_datetime(pv["SettledAt"], errors="coerce")
        pv["SettledAt"] = _st.dt.strftime("%Y-%m-%d").where(_st.notna(), "—")
        pv.columns = ["နေ့စွဲ", "ပေးရမည့်သူ", "မှတ်ချက်", "ပမာဏ (Ks)", "ရှင်းသည့်နေ့", "ရှင်းချသူ"]
        pv["ပမာဏ (Ks)"] = pv["ပမာဏ (Ks)"].map(_fmt_amount)
        st.dataframe(pv, use_container_width=True, hide_index=True)

def show_agent_interface():
    st.markdown("### 🤖 AI Agent ဖြင့် မှာယူမှုသွင်းရန်")
    st.caption(
        "မှာယူမှု၊ Dashboard ချုပ်၊ Ledger ပြင်/Trash၊ Master ထည့်ခြင်း၊ အဝယ်/အကြွေး စသည် — စကားပြောသလို ခိုင်းနိုင်ပါသည်။ "
        "**ငွေကိုင်** သည် ငွေရှင်း၊ အကြွေးမှတ်/ရှင်း၊ Trash/Master ပြင်ခြင်းကို Agent မှ မလုပ်နိုင်ပါ။ "
        "🎙️ အသံနဲ့ပြောပါက စာကြောင်းပေါ်လာပြီး **ပို့မည်** နှိပ်မှ လုပ်ပါ — မှားနားထောင်မှု ဖြစ်နိုင်လို့ စာသားပြင်ပါ။"
    )

    try:
        _df_led = pd.read_excel(LEDGER_FILE)
        _df_u = _df_led[_df_led["Status"] == "Unpaid"]
        if not _df_u.empty:
            show_unpaid_glance_summary(
                _df_u,
                title="📌 ယခု မရှင်းရသေးငွေ",
                caption="ဖောက်သည်တစ်ဦးချင်း စုစုပေါင်း။ ကြောင်းအသေးစိတ် 📋 Ledger မှ ကြည့်ပါ။",
            )
            st.divider()
    except Exception:
        pass

    components.html("""
    <div style="text-align:center">
      <button id="mic" class="mic-btn">🎙️</button>
      <p id="st" style="color:grey;margin-top:5px">တစ်ချက်နှိပ်ပြီး ပြောပါ</p>
    </div>
    <style>
    .mic-btn{background:#F1F5F9;color:#E11D48;border:3px solid #E11D48;padding:15px;
             border-radius:50%;cursor:pointer;font-size:1.8em;width:70px;height:70px;
             display:flex;align-items:center;justify-content:center;
             margin:0 auto;box-shadow:0 4px 10px rgba(0,0,0,.1)}
    .mic-btn.active{background:#E11D48;color:white;animation:pulse 1.5s infinite}
    @keyframes pulse{0%{transform:scale(1)}50%{transform:scale(1.1)}100%{transform:scale(1)}}
    </style>
    <script>
      const b=document.getElementById('mic'),s=document.getElementById('st');
      const r=new(window.SpeechRecognition||window.webkitSpeechRecognition)();
      r.lang='my-MM';r.interimResults=false;let rec=false;
      b.onclick=()=>{
        if(!rec){r.start();rec=true;b.classList.add('active');s.innerText='နားထောင်နေသည်...';}
        else{r.stop();rec=false;b.classList.remove('active');s.innerText='အဆင်သင့်';}
      };
      r.onresult=(e)=>{
        window.parent.postMessage({type:'streamlit:set_widget_value',key:'ai_cmd',value:e.results[0][0].transcript},'*');
        rec=false;b.classList.remove('active');
      };
      r.onspeechend=()=>{r.stop();rec=false;b.classList.remove('active');};
    </script>
    """, height=130)

    if st.session_state.chat_history:
        msgs_html = ""
        for m in st.session_state.chat_history:
            msgs_html += f'<div class="msg-user">🧑 {m["user"]}</div>'
            css = "msg-ok" if m.get("type") == "action" else "msg-bot"
            msgs_html += f'<div class="{css}">🤖 {m["bot"]}</div>'
            if st.session_state.show_steps and m.get("steps"):
                for stp in m["steps"]:
                    label = stp["step"]
                    content = stp["content"]
                    if "THINK" in label: cls = "step-think"
                    elif "TOOL" in label: cls = "step-tool"
                    elif "RESULT" in label: cls = "step-result"
                    else: cls = "step-done"
                    msgs_html += f'<div class="step-wrap {cls}">{label}: {content}</div>'
        st.markdown(f'<div class="chat-wrap">{msgs_html}</div>', unsafe_allow_html=True)
    else:
        st.markdown("""
        <div class="chat-wrap" style="color:#94A3B8;text-align:center;padding:30px">
        🤖 Agent chat မှတ်တမ်း ဤနေရာတွင် ပေါ်မည်<br>
        <small>ဥပမာ: "ကိုဇော် ထမင်းကြော် ၂ ခွက်" · "ယနေ့ မရှင်းရသေးငွေ ပြော" · "ဆန် ၅ ပိဿာ အဝယ်မှတ် ၈ သောင်း" · "ကိုစိုး အကြွေး ၂ သောင်း မှတ်"</small>
        </div>
        """, unsafe_allow_html=True)

    ai_cmd = st.text_input("🤖 Agent Command", key="ai_cmd", placeholder="ဥပမာ: ကိုဇော် ထမင်းကြော် ၂ ခွက်")
    send_agent = st.button("🚀 Agent သို့ ပို့မည်", type="primary", use_container_width=True)
    cmd = (ai_cmd or "").strip()

    if send_agent and cmd and st.session_state.resolved_api_key:
        with st.spinner("🤖 Agent တွေးနေသည်…"):
            try:
                genai.configure(api_key=st.session_state.resolved_api_key)
                gemini = genai.GenerativeModel(st.session_state.resolved_model)
                final_answer, steps = run_agent(cmd, gemini)

                action_keywords = ["သွင်းပြီး","ရှင်းပြီး","ပြန်ထည့်ပြီး","✅"]
                msg_type = "action" if any(k in final_answer for k in action_keywords) else "chat"

                st.session_state.chat_history.append({
                    "user": cmd, "bot": final_answer,
                    "type": msg_type, "steps": steps
                })
                add_memory("user", cmd)
                add_memory("agent", final_answer)
                append_chat_memory(cmd, final_answer)

                st.session_state.ai_cmd = ""
                st.rerun()

            except Exception as e:
                st.error(f"Agent Error: {e}")

    elif send_agent and cmd and not st.session_state.resolved_api_key:
        st.warning("⚠️ ⚙️ Admin မှာ Gemini API Key ထည့်ပြီး Save လုပ်ပါ။")

def show_ledger_display():
    st.markdown("### 📋 လက်ရှိ မရှင်းရသေးသော မှာယူမှုများ")
    st.caption(
        "အပေါ်ဇယားမှာ ဖောက်သည်တစ်ဦးချင်း စုစုပေါင်း မြင်ရပါသည်။ အောက်က နာမည်ကို နှိပ်မှ ဇယားကွက်နဲ့ အသေးစိတ် ပေါ်ပါသည်။ "
        "ဇယားအောက်က ✏️ သည် အတန်းနံပါတ် (#) နှင့် တူညီသည် — နှိပ်မှ ပြင်/ဖျက်နိုင်သည်။ "
        "**✅ ငွေရှင်းမည်** နှိပ်လိုက်ပါက ပြေစာ ထုတ်မလား မေးပါမည် — **ပြေစာ ထုတ်မည်** ရွေးမှ ပြေစာပုံစံ (မြန်မာ HTML/PNG၊ English၊ RawBT ASCII) ရွေးနိုင်ပါသည်။"
    )

    _flash = st.session_state.pop("_ledger_settle_flash", None)
    if _flash:
        st.success(str(_flash))

    _pend = st.session_state.get("_ledger_settle_prompt")
    if _pend:
        _pc = str(_pend.get("customer", "—"))
        _pgk = str(_pend.get("gk", "0"))
        st.markdown("---")
        st.markdown(f"##### 🧾 {_he(_pc)} — ပြေစာ ထုတ်မလား?")
        st.caption("**ပြေစာ ထုတ်မည်** = ငွေရှင်းပြီး RawBT ခလုတ်။ **မထုတ်ပါ** = ငွေရှင်းပြီး ပရင့်မဖွင့်။ **ပြန်ရွေး** = မရှင်းသေး။")
        y, n, x = st.columns(3)
        with y:
            if st.button("🖨️ ပြေစာ ထုတ်မည်", key=f"lsp_yes_{_pgk}"):
                who = (st.session_state.user or {}).get("name") or "—"
                settle_day = datetime.now().strftime("%Y-%m-%d")
                ok = clear_customer_bill(_pc, settled_by=who)
                if ok:
                    st.session_state["_ledger_settle_print"] = {
                        "customer": _pc,
                        "day": settle_day,
                        "lines": list(_pend["lines"]),
                        "total": float(_pend["total"]),
                        "by": str(who),
                    }
                    st.session_state.pop("_ledger_settle_prompt", None)
                    add_memory("agent", f"{_pc} ငွေရှင်းပြီး (ပြေစာထုတ်)")
                    st.rerun()
                else:
                    st.session_state.pop("_ledger_settle_prompt", None)
                    st.error("စာရင်း မတွေ့တော့ပါ။")
                    st.rerun()
        with n:
            if st.button("ပြေစာ မထုတ်ပါ", key=f"lsp_no_{_pgk}"):
                who = (st.session_state.user or {}).get("name") or "—"
                ok = clear_customer_bill(_pc, settled_by=who)
                if ok:
                    st.session_state.pop("_ledger_settle_prompt", None)
                    st.session_state["_ledger_settle_flash"] = f"✅ {_pc} ငွေရှင်းပြီးပါပြီ။ (ပြေစာ မထုတ်ပါ။)"
                    add_memory("agent", f"{_pc} ငွေရှင်းပြီး (ပြေစာမထုတ်)")
                    st.rerun()
                else:
                    st.session_state.pop("_ledger_settle_prompt", None)
                    st.error("စာရင်း မတွေ့တော့ပါ။")
                    st.rerun()
        with x:
            if st.button("← ငွေရှင်းမလုပ် (ပြန်ရွေးမည်)", key=f"lsp_x_{_pgk}"):
                st.session_state.pop("_ledger_settle_prompt", None)
                st.rerun()
        st.markdown("---")

    _incoming = st.session_state.pop("_ledger_settle_print", None)
    if _incoming:
        st.session_state["_ledger_receipt_view"] = _incoming

    _view = st.session_state.get("_ledger_receipt_view")
    if _view:
        try:
            _vk = _ledger_receipt_view_key(_view)
            _cust = str(_view["customer"])
            _day = str(_view["day"])
            _lines = list(_view["lines"])
            _tot = float(_view["total"])
            _by = str(_view["by"])

            st.success(f"✅ {_he(_cust)} ငွေရှင်းပြီးပါပြီ။")

            # ပြေစာကို screenshot ပုံစံတစ်မျိုးတည်း (မြန်မာ) ပြ + HTML ဒေါင်း
            _inner = _receipt_settlement_inner_html(_cust, _day, _lines, _tot, _by)
            _full = _receipt_shareable_html_document(_inner, title="ငွေရှင်းပြေစာ")
            _dl_base = _safe_receipt_download_basename(_cust, _day)
            with st.expander("👁 ပြေစာ ကြည့်မည် (သို့ screenshot)", expanded=True):
                components.html(_full, height=480, scrolling=True)
            _print_mode = st.radio(
                "ဘာနဲ့ထုတ်မလဲ",
                options=["add_print", "rawbt"],
                horizontal=True,
                key=f"ledger_print_mode_{_vk}",
                format_func=lambda k: "🖨️ Add Print" if k == "add_print" else "📲 RawBT",
            )
            if _print_mode == "add_print":
                render_settlement_receipt_browser_print(_full, f"ledger_{_vk}")
            else:
                _raw_txt = _receipt_settlement_plain_text_utf8(_cust, _day, _lines, _tot, _by)
                _rawbt = _rawbt_uri_from_plain_text(_raw_txt)
                if _rawbt:
                    _href = html.escape(_rawbt, quote=True)
                    st.markdown(
                        f'<p style="margin:10px 0 8px 0;"><a href="{_href}" '
                        'style="display:inline-block;padding:14px 22px;background:#1565c0;color:#fff !important;'
                        'border-radius:12px;text-decoration:none;font-weight:700;font-size:16px;">'
                        "📲 RawBT ဖြင့် ထုတ်မည်</a></p>",
                        unsafe_allow_html=True,
                    )
                else:
                    st.caption("RawBT လင့် မဖန်တီးနိုင်ပါ (ပြေစာရှည်လွန်းနိုင်သည်)။")
                _png = _receipt_png_from_html(_full)
                if _png:
                    st.download_button(
                        label="🖼️ PNG ဒေါင်း (RawBT သို့ Share)",
                        data=_png,
                        file_name=f"{_dl_base}.png",
                        mime="image/png",
                        key=f"dlpng_{_vk}",
                        use_container_width=True,
                    )
                st.download_button(
                    label="📄 HTML ဒေါင်း (အခြားစက်သို့ သိမ်းမည်)",
                    data=_receipt_html_file_bytes(_full),
                    file_name=f"{_dl_base}.html",
                    mime="text/html",
                    key=f"dlhtml_{_vk}",
                    use_container_width=True,
                )

            if st.button("ပြေစာ ပိတ်မည်", key=f"ledger_rec_close_{_vk}"):
                st.session_state.pop("_ledger_receipt_view", None)
                st.session_state.pop(f"_ledger_receipt_png_{_vk}", None)
                st.rerun()

        except Exception as _e:
            st.warning(f"ပြေစာ ပြသမှု မအောင်မြင်ပါ။ ({_e})")

    df_ledger = pd.read_excel(LEDGER_FILE)
    today = datetime.now().strftime("%Y-%m-%d")
    unpaid_prev = df_ledger[(df_ledger['Date']<today) & (df_ledger['Status']=='Unpaid')]
    today_ledger = df_ledger[(df_ledger['Date']==today) & (df_ledger['Status']=='Unpaid')]
    display_df = pd.concat([unpaid_prev, today_ledger])

    if not display_df.empty:
        show_unpaid_glance_summary(
            display_df,
            title="📌 စာရင်း အကျဉ်းချုပ်",
            caption="ဖောက်သည်တစ်ခုချင်းကို နှိပ်မှ အောက်မှာ ကြောင်းစာရင်း ပွင့်ပါသည်။",
        )
        st.divider()
        st.markdown("##### ဖောက်သည်အလိုက် အသေးစိတ် (နာမည်နှိပ်မှ ပွင့်)")

        for name, group in display_df.groupby("Name", sort=False):
            sub = group['Amount'].sum()
            gk = str(abs(hash(name + str(group.index.tolist()))))

            is_collapsed = st.session_state.collapsed.get(name, True)
            arrow = "▶" if is_collapsed else "▼"

            if st.button(f"{arrow}  👤 {name}   —   {sub:,.0f} Ks", key=f"hdr_{gk}", use_container_width=True):
                st.session_state.collapsed[name] = not is_collapsed
                st.rerun()

            if not is_collapsed:
                if "ledger_edit_idx" not in st.session_state:
                    st.session_state.ledger_edit_idx = None

                row_list = list(group.iterrows())
                rows_html = []
                for ri, (idx, row) in enumerate(row_list, start=1):
                    is_cf = row["Date"] < today
                    if is_cf:
                        dcell = f'<span class="carry-forward">{_he(row["Date"])}</span>'
                    else:
                        dcell = _he(row["Date"])
                    rows_html.append(
                        [
                            f'<span style="font-variant-numeric:tabular-nums;text-align:center;display:block">{ri}</span>',
                            dcell,
                            _he(row["Description"]),
                            _td_money(row["Amount"]),
                        ]
                    )
                foot = [
                    "",
                    "",
                    '<span style="text-align:right;font-weight:bold">စုစုပေါင်း</span>',
                    _td_money(sub),
                ]
                st.markdown(
                    _styled_service_table_html(
                        ["#", "နေ့စွဲ", "မှာယူမှု", "ပမာဏ"],
                        rows_html,
                        footer_cells=foot,
                        table_extra_class="ledger-rownum-table",
                    ),
                    unsafe_allow_html=True,
                )
                st.caption("✏️ = ထိုဖောက်သည်အတွက် အတန်းနံပါတ် (#) ထည့်ပြီး ပြင်/ဖျက်နိုင်သည်။")
                c_num, c_btn = st.columns([2, 1])
                with c_num:
                    edit_row_no = st.number_input(
                        "ပြင်မည့် အတန်း (#)",
                        min_value=1,
                        max_value=len(row_list),
                        step=1,
                        key=f"led_edit_row_{gk}",
                    )
                with c_btn:
                    if st.button("✏️ ဈေးပြင်မည်", key=f"led_edit_btn_{gk}", use_container_width=True):
                        try:
                            _, sel_row = row_list[int(edit_row_no) - 1]
                            st.session_state.ledger_edit_idx = int(sel_row.name)
                        except Exception:
                            st.session_state.ledger_edit_idx = None
                        st.rerun()

                eidx = st.session_state.ledger_edit_idx
                if eidx is not None and eidx in group.index:
                    erow = group.loc[eidx]
                    st.markdown("---")
                    st.markdown("##### ✏️ ပြင်ခြင်း / ဖျက်ခြင်း")
                    rd = _ledger_cell_to_date(erow["Date"])
                    ed_date = st.date_input("နေ့စွဲ", value=rd, key=f"ld_{gk}_{eidx}")
                    ed_desc = st.text_input(
                        "မှာယူမှု (ဥပမာ ကော်ဖီ (၃))",
                        value=str(erow["Description"]),
                        key=f"ls_{gk}_{eidx}",
                    )
                    ed_amt = st.number_input(
                        "ပမာဏ (Ks)",
                        min_value=0.0,
                        value=float(erow["Amount"]),
                        step=100.0,
                        key=f"la_{gk}_{eidx}",
                    )
                    b1, b2, b3 = st.columns(3)
                    with b1:
                        if st.button("💾 ပြင်ဆင်ချက်သိမ်းမည်", key=f"lsv_{gk}_{eidx}"):
                            ok, err = update_ledger_row(
                                eidx, ed_date.strftime("%Y-%m-%d"), ed_desc, ed_amt
                            )
                            if ok:
                                add_memory(
                                    "agent",
                                    f"စာရင်းပြင်ပြီး: {name} — {ed_desc} = {ed_amt:,.0f} Ks",
                                )
                                st.session_state.ledger_edit_idx = None
                                st.success("သိမ်းဆည်းပြီးပါပြီ။")
                                st.rerun()
                            else:
                                st.error(err)
                    with b2:
                        if st.button("🗑️ Trash သို့", key=f"ltr_{gk}_{eidx}"):
                            move_to_trash(eidx)
                            st.session_state.ledger_edit_idx = None
                            add_memory("agent", f"Trash သို့: {name} — {erow['Description']}")
                            st.success("Trash သို့ ရွှေ့ပြီးပါပြီ။")
                            st.rerun()
                    with b3:
                        if st.button("✖️ ပိတ်မည်", key=f"lcl_{gk}_{eidx}"):
                            st.session_state.ledger_edit_idx = None
                            st.rerun()

                c1, c2 = st.columns(2)
                if c1.button(f"✅ {name} ငွေရှင်းမည်", key=f"c_{gk}"):
                    line_items = [
                        (str(row["Description"]), float(row["Amount"]))
                        for _, row in group.iterrows()
                    ]
                    sub_total = float(group["Amount"].sum())
                    st.session_state["_ledger_settle_prompt"] = {
                        "customer": str(name),
                        "lines": line_items,
                        "total": sub_total,
                        "gk": gk,
                    }
                    st.rerun()
                if c2.button(f"🗑️ နောက်ဆုံးဖျက်မည်", key=f"d_{gk}"):
                    move_to_trash(group.index[-1])
                    st.rerun()
    else:
        st.info("မရှင်းရသေးသော မှာယူမှုများ မရှိပါ။")

    st.divider()
    total = df_ledger[df_ledger['Status']=='Unpaid']['Amount'].sum()
    st.markdown(f"<h3>💵 စုစုပေါင်း ရရန်ကျန်ငွေ: {total:,.0f} Ks</h3>", unsafe_allow_html=True)

def show_admin_settings():
    st.markdown("### ⚙️ ဆိုင်ပြင်ဆင်ချက်များ")

    config = get_config()
    api_key_input = st.text_input("Gemini API Key", value=config['api_key'], type="password")
    models = ["gemini-2.0-flash","gemini-2.5-flash","gemini-1.5-flash","gemini-2.0-flash-thinking-exp","Enter manually"]
    cur_mod = config['model_name']
    sel_mod = st.selectbox("Model", models, index=models.index(cur_mod) if cur_mod in models else 0)
    final_mod = st.text_input("Manual Model", value=cur_mod) if sel_mod=="Enter manually" else sel_mod

    skip_login_val = st.toggle(
        "စကားဝှက်မလို တန်းဝင် (Skip login)",
        value=bool(config.get("skip_login", True)),
        help="ဖွင့်ထားပါက အမည်/စကားဝှက် မထည့်ဘဲ စီမံခန့်ခွဲသူ အနေနဲ့ တန်းဝင်သည်။ ပိတ်ပါက လော့ဂ်အင်စာမျက်နှာပြန်ပေါ်မည်။",
    )

    if st.button("💾 သိမ်းဆည်းမည်"):
        save_config(api_key_input, final_mod, skip_login=skip_login_val)
        st.session_state.resolved_api_key = api_key_input
        st.session_state.resolved_model = final_mod
        st.success("သိမ်းဆည်းပြီးပါပြီ!")
        st.rerun()

    st.divider()
    st.session_state.show_steps = st.toggle("🔍 Agent အဆင့်ဆင့် ပြမည်", value=st.session_state.show_steps)

    st.divider()
    with st.expander("👤 Master Data စီမံခန့်ခွဲမှု"):

        # ==================== CUSTOMER MANAGEMENT ====================
        st.subheader("🧑 ဖောက်သည်များ")

        customers_df = pd.read_excel(MASTER_FILE, sheet_name='Customers')
        if not customers_df.empty:
            _st_dataframe_as_html_table(customers_df)

        # Add new customer
        st.markdown("#### ➕ ဖောက်သည်အသစ်ထည့်ရန်")
        col1, col2 = st.columns([3, 1])
        with col1:
            n_cust = st.text_input("ဖောက်သညမည်သစ်", key="new_customer_name")
        with col2:
            if st.button("ထည့်မည်", key="add_customer_btn") and n_cust:
                if n_cust not in customers_df['CustomerName'].values:
                    write_master_sheet('Customers', pd.concat([customers_df, pd.DataFrame([{"CustomerName":n_cust}])], ignore_index=True))
                    st.success(f"✅ {n_cust} ထည့်ပြီးပါပြီ။")
                    st.rerun()
                else:
                    st.warning("နာမည် ရှိပြီးသားပါ။")

        # Edit/Delete customer
        if not customers_df.empty:
            st.markdown("#### ✏️ ဖောက်သည်ပြင်ဆင်ရန် / 🗑️ ဖျက်ရန်")
            col1, col2, col3 = st.columns([2, 2, 1])
            with col1:
                selected_customer = st.selectbox("ရွေးမည့်ဖောက်သည်", customers_df['CustomerName'].tolist(), key="select_customer")
            with col2:
                new_customer_name = st.text_input("ည်အသစ်", value=selected_customer, key="edit_customer_name")
            with col3:
                if st.button("✏️ ပြင်မည်", key="edit_customer_btn"):
                    customers_df.loc[customers_df['CustomerName'] == selected_customer, 'CustomerName'] = new_customer_name
                    write_master_sheet('Customers', customers_df)
                    st.success(f"✅ {selected_customer} → {new_customer_name} သို့ ပြင်ဆင်ပြီးပါပြီ။")
                    st.rerun()

            if st.button("🗑️ ဖျက်မည်", key="delete_customer_btn"):
                customers_df = customers_df[customers_df['CustomerName'] != selected_customer]
                write_master_sheet('Customers', customers_df)
                st.success(f"✅ {selected_customer} ကို ဖျက်ပြီးပါပြီ။")
                st.rerun()

        st.divider()

        # ==================== MENU MANAGEMENT ====================
        st.subheader("🍽️ Menu စီမံခန့်ခွဲမှု")

        menu_df = pd.read_excel(MASTER_FILE, sheet_name='Menu')

        if not menu_df.empty:
            st.subheader("📋 လက်ရှိ Menu")
            display_df = menu_df.copy()
            display_df['Price'] = display_df['Price'].apply(lambda x: f"{x:,.0f} Ks")
            _st_dataframe_as_html_table(display_df)

        # Add new item
        st.markdown("#### ➕ အစားအစာအသစ်ထည့်ရန်")
        col1, col2 = st.columns(2)
        with col1:
            new_item = st.text_input("အစားအစမည်သစ်", key="new_item_name")
        with col2:
            new_price = st.number_input("ဈေးနှုန်း (Ks)", step=100, key="new_item_price")

        if st.button("အသစ်ထည့်မည်", key="add_item_btn") and new_item:
            menu_df = pd.read_excel(MASTER_FILE, sheet_name='Menu')
            if new_item not in menu_df['Item'].values:
                menu_df = pd.concat([menu_df, pd.DataFrame([{"Item":new_item, "Price":new_price}])], ignore_index=True)
                write_master_sheet('Menu', menu_df)
                st.success(f"✅ {new_item} ကို {new_price:,.0f} Ks ဖြင့် ထည့်ပြီးပါပြီ။")
                st.rerun()
            else:
                st.warning("နာမည် ရှိပြီးသားပါ။")

        # Edit menu item
        if not menu_df.empty:
            st.markdown("#### ✏️ Menu ပြင်ဆင်ရန်")
            col1, col2, col3 = st.columns([2, 2, 1])
            with col1:
                edit_item = st.selectbox("ပြင်ဆင်မည့် အစားအစာ", menu_df['Item'].tolist(), key="edit_item_select")
            with col2:
                edit_price = st.number_input("ဈေးနှုန်းအသစ် (Ks)", step=100, key="edit_price")
            with col3:
                if st.button("🔄 ပြင်ဆင်မည်", key="edit_item_btn"):
                    menu_df.loc[menu_df['Item'] == edit_item, 'Price'] = edit_price
                    write_master_sheet('Menu', menu_df)
                    st.success(f"✅ {edit_item} ဈေးနှုန်း {edit_price:,.0f} Ks သို့ ပြင်ဆင်ပြီးပါပြီ။")
                    st.rerun()

        # Delete menu item
        if not menu_df.empty:
            st.markdown("#### 🗑️ Menu ဖျက်ရန်")
            col1, col2 = st.columns([2, 1])
            with col1:
                delete_item = st.selectbox("ဖျက်မည့် အစားအစာ", menu_df['Item'].tolist(), key="delete_item_select")
            with col2:
                if st.button("🗑️ ဖျက်မည်", key="delete_item_btn"):
                    menu_df = menu_df[menu_df['Item'] != delete_item]
                    write_master_sheet('Menu', menu_df)
                    st.success(f"✅ {delete_item} ကို ဖျက်ပြီးပါပြီ။")
                    st.rerun()

        st.divider()

        # ==================== CREDITORS (Master: အကြွေးမှာ ရွေးမည့်သူ) ====================
        st.subheader("🏬 ဈေးသမား / ပေးရမည့်သူ စာရင်း")
        st.caption("ဤစာရင်းတွင် နာမည်များ ကြိုတင်ထည့်ထားပါက **အကြွေး မှတ်တမ်း** သွင်းချိန်တွင် ရွေးချယ်ယူနိုင်ပါသည်။")

        creditors_df = read_master_sheet_safe("Creditors", ["CreditorName"])
        if not creditors_df.empty:
            _st_dataframe_as_html_table(creditors_df.rename(columns={"CreditorName": "နာမည်"}))

        st.markdown("#### ➕ ဈေးသမားအသစ်ထည့်ရန်")
        nc1, nc2 = st.columns([3, 1])
        with nc1:
            new_cred = st.text_input("ဈေးသမား နာမည်သစ်", key="new_creditor_name")
        with nc2:
            if st.button("ထည့်မည်", key="add_creditor_btn") and new_cred:
                nn = new_cred.strip()
                if nn and nn not in creditors_df["CreditorName"].astype(str).str.strip().values:
                    write_master_sheet(
                        "Creditors",
                        pd.concat([creditors_df, pd.DataFrame([{"CreditorName": nn}])], ignore_index=True),
                    )
                    st.success(f"✅ {nn} ထည့်ပြီးပါပြီ။")
                    st.rerun()
                elif nn:
                    st.warning("နာမည် ရှိပြီးသားပါ။")

        if not creditors_df.empty:
            st.markdown("#### ✏️ ဈေးသမား ပြင်ဆင်ရန် / ဖျက်ရန်")
            ec1, ec2, ec3 = st.columns([2, 2, 1])
            with ec1:
                sel_cr = st.selectbox("ရွေးမည့်သူ", creditors_df["CreditorName"].tolist(), key="select_creditor")
            with ec2:
                edit_cr = st.text_input("နည်အသစ်", value=sel_cr, key="edit_creditor_name")
            with ec3:
                if st.button("✏️ ပြင်မည်", key="edit_creditor_btn"):
                    creditors_df.loc[creditors_df["CreditorName"] == sel_cr, "CreditorName"] = edit_cr.strip()
                    write_master_sheet("Creditors", creditors_df)
                    st.success("ပြင်ဆင်ပြီးပါပြီ။")
                    st.rerun()
            if st.button("🗑️ ဖျက်မည်", key="delete_creditor_btn"):
                creditors_df = creditors_df[creditors_df["CreditorName"] != sel_cr]
                write_master_sheet("Creditors", creditors_df)
                st.success(f"✅ {sel_cr} ဖျက်ပြီးပါပြီ။")
                st.rerun()

        st.divider()

        # ==================== PURCHASE CATALOG (Master: အဝယ်မှာ ရွေးမည့်ပစ္စည်း) ====================
        st.subheader("📦 ဝယ်ပစ္စည်း စာရင်း (မှတ်သားဈေး)")
        st.caption("ပစ္စည်းအမည် နှင့် **မှတ်သားဝယ်ဈေး** ကြိုသတ်မှတ်ထားပါက **အဝယ် စာရင်း** သွင်းချိန်တွင် ရွေးပြီး ဈေးကို လိုအပ်သလို ပြင်သတ်မှတ်နိုင်ပါသည်။")

        pcat_df = read_master_sheet_safe("PurchaseCatalog", ["ItemName", "RefPrice"])
        if not pcat_df.empty:
            disp_pc = pcat_df.copy()
            disp_pc["RefPrice"] = disp_pc["RefPrice"].apply(lambda x: f"{float(x):,.0f} Ks" if pd.notna(x) else "—")
            _st_dataframe_as_html_table(disp_pc.rename(columns={"ItemName": "ပစ္စည်း", "RefPrice": "မှတ်သားဈေး"}))

        st.markdown("#### ➕ ဝယ်ပစ္စည်းအသစ်ထည့်ရန်")
        pc1, pc2, pc3 = st.columns([2, 2, 1])
        with pc1:
            new_pit = st.text_input("ပစ္စည်းအမည်", key="new_pcat_item")
        with pc2:
            new_pref = st.number_input("မှတ်သားဈေး (Ks)", min_value=0.0, value=0.0, step=100.0, key="new_pcat_price")
        with pc3:
            st.write("")
            st.write("")
            if st.button("ထည့်မည်", key="add_pcat_btn") and new_pit:
                pit = new_pit.strip()
                if pit and pit not in pcat_df["ItemName"].astype(str).str.strip().values:
                    write_master_sheet(
                        "PurchaseCatalog",
                        pd.concat([pcat_df, pd.DataFrame([{"ItemName": pit, "RefPrice": new_pref}])], ignore_index=True),
                    )
                    st.success(f"✅ {pit} ထည့်ပြီးပါပြီ။")
                    st.rerun()
                elif pit:
                    st.warning("ပစ္စည်းအမည် ရှိပြီးသားပါ။")

        if not pcat_df.empty:
            st.markdown("#### ✏️ မှတ်သားဈေး ပြင်ဆင်ရန်")
            ep1, ep2, ep3 = st.columns([2, 2, 1])
            with ep1:
                ep_sel = st.selectbox("ပစ္စည်း", pcat_df["ItemName"].tolist(), key="edit_pcat_select")
            with ep2:
                ep_price = st.number_input("မှတ်သားဈေး အသစ် (Ks)", min_value=0.0, step=100.0, key="edit_pcat_price")
            with ep3:
                if st.button("🔄 ပြင်မည်", key="edit_pcat_btn"):
                    pcat_df.loc[pcat_df["ItemName"] == ep_sel, "RefPrice"] = ep_price
                    write_master_sheet("PurchaseCatalog", pcat_df)
                    st.success("ပြင်ဆင်ပြီးပါပြီ။")
                    st.rerun()

            st.markdown("#### 🗑️ ပစ္စည်းဖျက်ရန်")
            dp1, dp2 = st.columns([2, 1])
            with dp1:
                del_pit = st.selectbox("ဖျက်မည့်ပစ္စည်း", pcat_df["ItemName"].tolist(), key="delete_pcat_select")
            with dp2:
                if st.button("🗑️ ဖျက်မည်", key="delete_pcat_btn"):
                    pcat_df = pcat_df[pcat_df["ItemName"] != del_pit]
                    write_master_sheet("PurchaseCatalog", pcat_df)
                    st.success(f"✅ {del_pit} ဖျက်ပြီးပါပြီ။")
                    st.rerun()

        st.divider()
        show_purchase_entry(key_prefix="md_pur_", compact=True)
        st.divider()
        show_payable_credit_ui(key_prefix="md_pay_", compact=True)

    st.divider()

    # ==================== USER MANAGEMENT ====================
    with st.expander("👥 ဝန်ထမ်းစီမံခန့်ခွဲမှု"):
        st.subheader("➕ ဝန်ထမ်းအသစ်ထည့်ရန်")
        col1, col2 = st.columns(2)
        with col1:
            new_username = st.text_input("အသုံးပြုသူအမည်")
            new_name = st.text_input("အမည်")
        with col2:
            new_password = st.text_input("စကားဝှက်", type="password")
            new_role = st.selectbox("အခန်းကဏ္ဍ", ["cashier", "admin"])

        if st.button("ဝန်ထမ်းထည့်မည်"):
            if add_user(new_username, new_password, new_role, new_name):
                st.success(f"✅ {new_name} ကို ထည့်သွင်းပြီးပါပြီ။")
            else:
                st.error("အသုံးပြုသူအမည် ရှိပြီးသားပါ။")

        with open(USERS_FILE, 'r', encoding='utf-8') as f:
            users = json.load(f)
        st.subheader("📋 ဝန်ထမ်းစာရင်း")
        user_list = []
        for uid, info in users.items():
            user_list.append({
                "အသုံးပြုသူအမည်": uid,
                "အမည်": info['name'],
                "အခန်းကဏ္ဍ": "စီမံခန့်ခွဲသူ" if info['role'] == 'admin' else "ငွေကိုင်"
            })
        _st_dataframe_as_html_table(pd.DataFrame(user_list))

    st.divider()

    # ==================== CHAT & MEMORY ====================
    col_m1, col_m2, col_m3 = st.columns(3)
    if col_m1.button("🗑️ Chat ရှင်းမည်", use_container_width=True):
        st.session_state.chat_history = []
        st.rerun()
    if col_m2.button("🧠 လုပ်ငန်း Memory ရှင်း", use_container_width=True):
        save_memory([])
        st.success("လုပ်ငန်း memory ရှင်းပြီး")
        st.rerun()
    if col_m3.button("💬 စကားပြော ဖိုင်ရှင်း", use_container_width=True):
        clear_chat_memory_file()
        st.success("agent_chat_memory.json ရှင်းပြီး")
        st.rerun()

    with st.expander("🧠 လုပ်ငန်း Memory ကြည့်ရန်"):
        mem = load_memory()
        if mem:
            for m in mem[-8:]:
                st.caption(f"[{m['ts']}] {m['role']}: {m['text'][:60]}…" if len(m['text'])>60 else f"[{m['ts']}] {m['role']}: {m['text']}")
        else:
            st.info("Memory ဗလာ")

    with st.expander("📒 Audit log (Agent လုပ်ဆောင်ချက် နောက်ဆုံး ၅၀)"):
        aud = load_audit_log()[-50:]
        if aud:
            for e in reversed(aud):
                st.caption(f"{e.get('ts','')} · {e.get('user','')} · **{e.get('action','')}** — {str(e.get('detail',''))[:200]}")
        else:
            st.info("မှတ်တမ်း မရှိသေးပါ")

    st.caption(
        "ဒေတာအမြဲတမ်း: လက်ရှိတွင် Excel ဖိုင်များ သုံးထားပါသည်။ "
        "အသုံးပြုသူများစွာ တစ်ချိန်တည်း ရေးမယ်ဆို SQLite/DB သို့ ပြောင်းသင့်ပါသည်။"
    )

# ══════════════════════════════════════════════════════════════════
#  MAIN APP
# ══════════════════════════════════════════════════════════════════
st.set_page_config(page_title="🍚 ကိုကျော် ထမင်းဆိုင်", layout="wide", initial_sidebar_state="expanded")
init_db()
init_users()

# Session State Initialization
if 'user' not in st.session_state:
    st.session_state.user = None
if 'chat_history' not in st.session_state:
    st.session_state.chat_history = []
if 'show_steps' not in st.session_state:
    st.session_state.show_steps = False
if 'collapsed' not in st.session_state:
    st.session_state.collapsed = {}
if 'selected_price' not in st.session_state:
    st.session_state.selected_price = 0
if 'resolved_api_key' not in st.session_state:
    config = get_config()
    st.session_state.resolved_api_key = config['api_key']
    st.session_state.resolved_model = config['model_name']
if 'dark_mode' not in st.session_state:
    st.session_state.dark_mode = False

_app_cfg = get_config()
if st.session_state.user is None and _app_cfg.get("skip_login", True):
    try:
        st.session_state.user = default_auto_login_user()
    except Exception:
        pass

if st.session_state.user is not None:
    _now = time.time()
    _last = st.session_state.get("_activity_ts")
    if _last is not None and (_now - _last) > SESSION_IDLE_SEC:
        st.session_state.user = None
        st.session_state._activity_ts = None
        st.warning("⏱️ အချိန်ကြာလွန်သဖြင့် လုံခြုံရေးအတွက် ထွက်ပြီးပါပြီ — ပြန်ဝင်ပါ။")
        st.rerun()
    st.session_state._activity_ts = _now

# CSS (light + mobile nav; dark အပိုအောက်)
_base_css = """
<style>
.ledger-header{background:#0F172A;color:white;padding:12px;border-radius:8px;margin-top:15px;font-weight:bold}
.sub-total{background:#F8FAFC;font-weight:bold;border-top:2px solid #E2E8F0}
.carry-forward{color:#DC2626;font-weight:bold}
.styled-table{width:100%;border-collapse:collapse;margin-bottom:14px;box-shadow:0 1px 2px rgba(15,23,42,.06)}
.styled-table th,.styled-table td{padding:8px 10px;border:1px solid #E2E8F0;text-align:left;vertical-align:middle}
.styled-table th{background:#F1F5F9;font-weight:bold}
.styled-table.ledger-rownum-table th:first-child,.styled-table.ledger-rownum-table td:first-child{width:3rem;text-align:center}
.chat-wrap{background:#F8FAFC;border:1px solid #E2E8F0;border-radius:12px;padding:12px;max-height:380px;overflow-y:auto;margin-bottom:10px;display:flex;flex-direction:column;gap:8px}
.msg-user{background:#0F172A;color:white;border-radius:12px 12px 2px 12px;padding:8px 14px;align-self:flex-end;max-width:80%;font-size:.9em}
.msg-bot{background:#E0F2FE;color:#0F172A;border-radius:12px 12px 12px 2px;padding:8px 14px;align-self:flex-start;max-width:88%;font-size:.9em;white-space:pre-wrap}
.msg-ok{background:#DCFCE7;color:#166534;border-radius:8px;padding:6px 12px;font-size:.85em}
.step-wrap{background:#FFFBEB;border:1px solid #FDE68A;border-radius:8px;padding:8px 12px;margin:4px 0;font-size:.82em;font-family:monospace}
.step-think{color:#92400E}.step-tool{color:#1D4ED8}.step-result{color:#166534}.step-done{color:#166534;font-weight:bold}
@media (max-width: 768px) {
  [data-testid="stSidebar"] div[data-baseweb="radio"] > div { flex-direction: row !important; flex-wrap: nowrap !important; overflow-x: auto !important; gap: 0.35rem !important; padding-bottom: 6px !important; -webkit-overflow-scrolling: touch; }
  [data-testid="stSidebar"] div[data-baseweb="radio"] label { white-space: nowrap !important; font-size: 0.82rem !important; padding: 0.35rem 0.45rem !important; }
}
</style>
"""
st.markdown(_base_css, unsafe_allow_html=True)
if st.session_state.get("dark_mode"):
    st.markdown("""
<style>
/* အက်ပ်ခံ မည်း — ခလုတ်အဖြူခံပေါ်မှာ စ်းမဖြစ်အောင် label/span ကို အဝှေ့မသုံးပါနဲ့ */
.stApp, [data-testid="stAppViewContainer"] {
  background-color: #0f172a !important;
  color: #e2e8f0 !important;
  color-scheme: dark;
}
[data-testid="stSidebar"] {
  background-color: #020617 !important;
  border-right: 1px solid #1e293b !important;
}
[data-testid="stSidebar"] p,
[data-testid="stSidebar"] .stMarkdown p,
[data-testid="stSidebar"] label[data-baseweb="typo"] {
  color: #e2e8f0 !important;
}

/* စာသား (ခလုတ် / input အတွင်းမဟုတ်) */
.block-container .stMarkdown > div > p,
.block-container .stMarkdown > div > ul,
.block-container .stMarkdown > div > ol,
.block-container [data-testid="stCaptionContainer"] p,
.block-container h1, .block-container h2, .block-container h3,
.block-container h4, .block-container h5, .block-container h6 {
  color: #e2e8f0 !important;
}

/* Streamlit ခလုတ် — ခံမည်း + စာဖြူ (secondary / default) */
[data-testid="baseButton-secondary"],
button[kind="secondary"] {
  background-color: #1e293b !important;
  color: #f8fafc !important;
  border: 1px solid #475569 !important;
}
[data-testid="baseButton-secondary"] p,
[data-testid="baseButton-secondary"] span,
button[kind="secondary"] p,
button[kind="secondary"] span {
  color: #f8fafc !important;
}
[data-testid="baseButton-primary"],
button[kind="primary"] {
  background-color: #ea580c !important;
  color: #ffffff !important;
  border: 1px solid #c2410c !important;
}
[data-testid="baseButton-primary"] p,
[data-testid="baseButton-primary"] span,
button[kind="primary"] p,
button[kind="primary"] span {
  color: #ffffff !important;
}

/* st.button — Ledger ဖောက်သည်ခေါင်းစဉ် စသည် (ခံအဖြူ + စာဖြူ ပြဿနာ ဖြေရှင်း) */
section.main div[data-testid="stButton"] > button {
  background-color: #1e293b !important;
  color: #f8fafc !important;
  border: 1px solid #475569 !important;
}
section.main div[data-testid="stButton"] > button p,
section.main div[data-testid="stButton"] > button span {
  color: #f8fafc !important;
}
section.main div[data-testid="stButton"] > button[kind="primary"] {
  background-color: #ea580c !important;
  color: #ffffff !important;
  border-color: #c2410c !important;
}
section.main div[data-testid="stButton"] > button[kind="primary"] p,
section.main div[data-testid="stButton"] > button[kind="primary"] span {
  color: #ffffff !important;
}
[data-testid="stSidebar"] div[data-testid="stButton"] > button {
  background-color: #1e293b !important;
  color: #f8fafc !important;
  border: 1px solid #475569 !important;
}
[data-testid="stSidebar"] div[data-testid="stButton"] > button p,
[data-testid="stSidebar"] div[data-testid="stButton"] > button span {
  color: #f8fafc !important;
}

[data-testid="stMetricValue"] { color: #f8fafc !important; }
[data-testid="stMetricLabel"] { color: #94a3b8 !important; }

.chat-wrap { background: #1e293b !important; border-color: #334155 !important; }
.msg-bot { background: #1e3a5f !important; color: #e0f2fe !important; }

/* ဇယားကွက် (Ledger စသည်) */
.styled-table th { background: #334155 !important; color: #f1f5f9 !important; border-color: #475569 !important; }
.styled-table td { background: #1e293b !important; color: #e2e8f0 !important; border-color: #475569 !important; }
.sub-total { background: #334155 !important; color: #f8fafc !important; border-top-color: #64748b !important; }
.carry-forward { color: #fca5a5 !important; }

/* Expander / form အညွှန်း */
.streamlit-expanderHeader,
details summary span {
  color: #e2e8f0 !important;
}
.stTextInput label, .stNumberInput label, .stSelectbox label,
.stDateInput label, .stTextArea label, .stMultiSelect label {
  color: #cbd5e1 !important;
}
.stTextInput input, .stNumberInput input, .stTextArea textarea {
  color: #f8fafc !important;
  background-color: #1e293b !important;
  border-color: #475569 !important;
}

/* st.table — မရှင်းရငွေ စာချပ်၊ Master စာရင်းဇယား (စာမည်းနီးပါး ပြဿနာ) */
section.main [data-testid="stTable"],
section.main [data-testid="stTable"] table {
  background-color: #1e293b !important;
  color: #f1f5f9 !important;
}
section.main [data-testid="stTable"] thead tr th,
section.main [data-testid="stTable"] tbody tr th,
section.main [data-testid="stTable"] th {
  background-color: #334155 !important;
  color: #f8fafc !important;
  border: 1px solid #475569 !important;
}
section.main [data-testid="stTable"] tbody tr td,
section.main [data-testid="stTable"] td {
  background-color: #1e293b !important;
  color: #f1f5f9 !important;
  border: 1px solid #475569 !important;
}
section.main [data-testid="stTable"] tbody tr:hover td {
  background-color: #273549 !important;
}

/* ဟောင်း Streamlit / အခြား ဇယားဖွဲ့စည်းပုံ */
section.main .stTable table,
section.main .stTable th,
section.main .stTable td {
  background-color: #1e293b !important;
  color: #f1f5f9 !important;
  border-color: #475569 !important;
}
section.main .stTable th {
  background-color: #334155 !important;
  color: #f8fafc !important;
}

/* st.dataframe (အဝယ်/အကြွေး စာရင်းများ) */
section.main [data-testid="stDataFrame"] {
  background-color: #1e293b !important;
  border: 1px solid #475569 !important;
  border-radius: 8px !important;
}
section.main [data-testid="stDataFrame"] * {
  color: #e2e8f0 !important;
}

/* st.info / warning / success — စည်းမကျန်အောင် */
section.main [data-testid="stAlert"] {
  background-color: #1e3a5f !important;
  border: 1px solid #334155 !important;
}
section.main [data-testid="stAlert"] p,
section.main [data-testid="stAlert"] div,
section.main [data-testid="stAlert"] span {
  color: #e0f2fe !important;
}

/* Caption — အောက်ဖော်ပြချက်များ */
section.main [data-testid="stCaptionContainer"],
section.main [data-testid="stCaptionContainer"] p,
section.main [data-testid="stCaptionContainer"] span,
section.main [data-testid="stCaptionContainer"] small {
  color: #cbd5e1 !important;
}

/* Selectbox / multiselect ပြသစာသား */
section.main [data-baseweb="select"] span,
section.main [data-testid="stSelectbox"] label {
  color: #e2e8f0 !important;
}

/* Toggle နှင့်အညွှန်း */
section.main [data-testid="stToggle"] label,
section.main [data-testid="stCheckbox"] label {
  color: #e2e8f0 !important;
}

/* Radio (main ဧရိယာ — Dashboard စသည်) */
section.main [data-testid="stRadio"] label,
section.main [data-baseweb="radio"] label {
  color: #e2e8f0 !important;
}
/* အောက်ခြေ icon navigation — မြင်သာအောင် ဖျော့ဖျော့ background */
section.main [data-testid="stRadio"] [data-baseweb="radio"] label {
  background-color: rgba(241, 245, 249, 0.22) !important;
  border: 1px solid rgba(148, 163, 184, 0.5) !important;
  border-radius: 10px !important;
  padding: 0.4rem 0.55rem !important;
  min-width: 2.4rem !important;
  justify-content: center !important;
}
</style>
""", unsafe_allow_html=True)

# Header
st.markdown("""
<div style="text-align:center; padding:20px 0; background:linear-gradient(135deg, #FF6B35, #F7931E); border-radius:20px; margin-bottom:20px">
    <h1 style="color:white; margin:0; font-size:2.5rem">🍚 ကိုကျော် ထမင်းဆိုင်</h1>
    <p style="color:#FFF2E6; margin:5px 0 0 0">အရသာနှင့် စံချိန်မီ ထမင်းဆိုင်</p>
</div>
""", unsafe_allow_html=True)

# Login or Main App
if st.session_state.user is None:
    login_ui()
else:
    with st.sidebar:
        st.markdown(f"""
        <div style="background:#0F172A; padding:10px; border-radius:10px; margin-bottom:15px">
            <div>👤 {st.session_state.user['name']}</div>
            <div style="font-size:0.8rem; color:#94A3B8">🔑 {"စီမံခန့်ခွဲသူ" if st.session_state.user['role'] == 'admin' else "ငွေကိုင်"}</div>
        </div>
        """, unsafe_allow_html=True)
        if not get_config().get("skip_login", True):
            logout_ui()

        st.divider()
        _dm = st.toggle("🌙 Dark mode", value=st.session_state.dark_mode)
        st.session_state.dark_mode = _dm
        try:
            _csv_bytes = _ledger_read().to_csv(index=False).encode("utf-8-sig")
            st.download_button(
                label="📥 Ledger CSV ထုတ်မည်",
                data=_csv_bytes,
                file_name=f"ledger_{datetime.now().strftime('%Y%m%d')}.csv",
                mime="text/csv",
                use_container_width=True,
            )
        except Exception:
            pass

        if st.session_state.user['role'] == 'admin':
            st.divider()
            st.info("🔧 Admin Mode - အပြည့်အစုံ စီမံနိုင်သည်")

        st.divider()
        _nav_admin = [
            "🤖 Agent",
            "📊 Dashboard",
            "📝 Manual Entry",
            "🛒 အဝယ်",
            "📋 Ledger",
            "🗑️ Recycle Bin",
            "⚙️ Admin",
        ]
        _nav_cashier = [
            "🤖 Agent",
            "📊 Dashboard",
            "📝 Manual Entry",
            "🛒 အဝယ်",
            "📋 Ledger",
        ]
        _labels = _nav_admin if st.session_state.user['role'] == 'admin' else _nav_cashier

        # bottom icon-nav ကနေ လာတဲ့ target ကို radio မဖွင့်ခင် set လုပ်
        _nav_target = st.session_state.pop("_nav_target_page", None)
        if _nav_target in _labels:
            st.session_state["main_nav_page"] = _nav_target

        page = st.radio(
            "main_navigation",
            _labels,
            label_visibility="collapsed",
            key="main_nav_page",
        )

    if page == "🤖 Agent":
        show_agent_interface()
    elif page == "📊 Dashboard":
        show_dashboard()
    elif page == "📝 Manual Entry":
        show_manual_entry()
    elif page == "🛒 အဝယ်":
        show_purchase_entry()
        st.divider()
        show_payable_credit_ui()
    elif page == "📋 Ledger":
        show_ledger_display()
    elif page == "🗑️ Recycle Bin":
        show_recycle_bin()
    elif page == "⚙️ Admin":
        show_admin_settings()

    # အောက်ခြေ icon navigation (phone မှာ ဒေါင်မဖြစ်အောင် horizontal radio)
    def _set_bottom_nav_target():
        v = st.session_state.get("bottom_nav_page")
        if v in _labels:
            st.session_state["_nav_target_page"] = v

    st.radio(
        "",
        options=_labels,
        key="bottom_nav_page",
        index=0,
        format_func=lambda s: s.split(" ")[0] if isinstance(s, str) and " " in s else s,
        horizontal=True,
        label_visibility="collapsed",
        on_change=_set_bottom_nav_target,
    )
