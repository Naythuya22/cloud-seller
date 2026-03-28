import os, json, re, math, shutil, warnings, html
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
USERS_FILE   = 'users.json'
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
    return "=== ယခင် conversation မှတ်တမ်း ===\n" + "\n".join(lines) + "\n"

# ══════════════════════════════════════════════════════════════════
#  TOOLS
# ══════════════════════════════════════════════════════════════════
TOOL_REGISTRY = {}

def tool(name):
    def decorator(fn):
        TOOL_REGISTRY[name] = fn
        return fn
    return decorator

@tool("calculate")
def tool_calculate(expression: str) -> str:
    try:
        allowed = {k: getattr(math, k) for k in dir(math) if not k.startswith('_')}
        result = eval(expression, {"builtins": {}}, allowed)
        return str(result)
    except Exception as e:
        return f"ERROR: {e}"

@tool("get_ledger_summary")
def tool_ledger_summary(name: str = "") -> str:
    df = pd.read_excel(LEDGER_FILE)
    df = df[df['Status'] == 'Unpaid']
    if name:
        df = df[df['Name'].str.contains(name, case=False)]
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
    rows = df[(df['Name'].str.contains(name, case=False)) & (df['Status'] == 'Unpaid')]
    if rows.empty: return f"{name} ၏ မရှင်းရသောစာရင်း မရှိပါ။"
    out = []
    for _, r in rows.iterrows():
        out.append(f"  {r['Date']} | {r['Description']} | {r['Amount']:,.0f} Ks")
    total = rows['Amount'].sum()
    out.append(f"  ── စုစုပေါင်း: {total:,.0f} Ks")
    return "\n".join(out)

@tool("add_order")
def tool_add_order(name: str, food: str, qty: int, price: float) -> str:
    amount = qty * price
    save_to_ledger(name, f"{food} ({qty})", amount)
    return f"✅ {name} — {food} × {qty} = {amount:,.0f} Ks သွင်းပြီးပါပြီ။"

@tool("settle_bill")
def tool_settle_bill(name: str) -> str:
    ok = clear_customer_bill(name, settled_by="Agent")
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

TOOLS_DESC = """
Available tools (call with TOOL:<name>:<arg>):
- calculate:<math_expression>         → ဈေးနှုန်းတွက်ချက်ရန်
- get_ledger_summary:<name_or_empty>  → မရှင်းရသေးသော စာရင်းချုပ်
- get_customer_detail:<name>          → ဖောက်သည်တစ်ဦး၏ အသေးစိတ်စာရင်း
- add_order:<json>                    → {"name","food","qty","price"} JSON ဖြင့် မှာယူမှုသွင်းရန်
- settle_bill:<name>                  → ဖောက်သည်အတွက် ငွေရှင်းရန်
- get_menu:<empty>                    → Menu စာရင်းကြည့်ရန်
- get_customers:<empty>               → ဖောက်သည်စာရင်းကြည့်ရန်
- DONE:<final_answer>                 → အားလုံးပြီးဆုံးပြီ၊ ဖောက်သည်ကို ဖြေကြားရန်
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
    mask = df['Name'].str.contains(name, case=False, na=False) & (df['Status']=='Unpaid')
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
def run_agent(user_input: str, gemini_model) -> tuple[str, list]:
    steps_log = []
    mem_ctx = memory_context()

    system_prompt = f"""You are an AI restaurant ledger assistant. Reason step by step.
{TOOLS_DESC}
Rules:
- Respond ONLY with one line per step: THINK:<thought> or TOOL:<name>:<arg> or DONE:<answer>
- For add_order, arg must be valid JSON: {{"name":"...","food":"...","qty":1,"price":0}}
- Answer in Burmese. Be concise.
- Max 8 steps then DONE.

{mem_ctx}
Current date: {datetime.now().strftime("%Y-%m-%d")}
"""
    messages = [{"role":"user", "parts":[system_prompt + "\nUser request: " + user_input]}]

    for step_num in range(10):
        response = gemini_model.generate_content(messages)
        line = response.text.strip().split('\n')[0].strip()

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

            if tool_name in TOOL_REGISTRY:
                if tool_name == "add_order":
                    try:
                        j = json.loads(tool_arg)
                        obs = TOOL_REGISTRY[tool_name](j['name'], j['food'],
                            int(j.get('qty',1)), float(j.get('price',0)))
                    except Exception as e:
                        obs = f"JSON parse error: {e}"
                else:
                    obs = TOOL_REGISTRY[tool_name](tool_arg)
            else:
                obs = f"Unknown tool: {tool_name}"

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

    return "Agent max steps ပြည့်သွားပြီ။", steps_log

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
            "**ငွေရှင်းချသူ** မှာ ဝန်ထမ်းအမည် (သို့မဟုတ် Agent) ဖြစ်သည်။"
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
    rows = [
        {"ဖောက်သည် / စာရင်း": str(n), "ကျန်ငွေ (Ks)": f"{float(v):,.0f}"}
        for n, v in g.items()
    ]
    rows.append({"ဖောက်သည် / စာရင်း": "➡️ စုစုပေါင်း", "ကျန်ငွေ (Ks)": f"{tot:,.0f}"})
    st.table(pd.DataFrame(rows))

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
            st.metric("📝 မှာယူမှုအရေအတွက်", total_orders)
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
                st.table(top_df)

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
                price = price_row['Price'].values[0]
                st.session_state.selected_price = price
                st.markdown(f'<div style="background:#FEF3C7; border-left:4px solid #F59E0B; padding:8px 12px; border-radius:8px; margin-top:5px">💰 ဈေးနှုန်း: {price:,.0f} Ks</div>', unsafe_allow_html=True)
            else:
                st.session_state.selected_price = 0
        else:
            st.session_state.selected_price = 0

    with col_c:
        qty = st.number_input("အရေအတွက်", min_value=1, value=1)

    if sel_food != "-- ရွေးရန် --" and st.session_state.selected_price > 0:
        total_amount = qty * st.session_state.selected_price
        st.markdown(f'<div style="background:#E6F7E6; padding:8px 12px; border-radius:8px; margin-top:5px; text-align:center">📊 စုစုပေါင်း: {total_amount:,.0f} Ks</div>', unsafe_allow_html=True)

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
        st.dataframe(pv, use_container_width=True, hide_index=True)

def show_agent_interface():
    st.markdown("### 🤖 AI Agent ဖြင့် မှာယူမှုသွင်းရန်")
    st.caption("စကားပြောသလို မှာယူမှုများ သွင်းနိုင်ပါတယ်။ ဥပမာ - 'ကိုဇော် ထမင်းကြော် ၂ ခွက်'")

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
        <small>ဥပမာ: "ကိုဇော် ထမင်းကြော် ၂ ခွက်" · "မမေ ကြက်သားဟင်း ၁ ပွဲ" · "စုစုပေါင်း ဘယ်လောက်ရသေးလဲ"</small>
        </div>
        """, unsafe_allow_html=True)

    ai_cmd = st.text_input("🤖 Agent Command", key="ai_cmd", placeholder="ဥပမာ: ကိုဇော် ထမင်းကြော် ၂ ခွက်")

    if ai_cmd and st.session_state.resolved_api_key:
        with st.spinner("🤖 Agent တွေးနေသည်…"):
            try:
                genai.configure(api_key=st.session_state.resolved_api_key)
                gemini = genai.GenerativeModel(st.session_state.resolved_model)
                final_answer, steps = run_agent(ai_cmd, gemini)

                action_keywords = ["သွင်းပြီး","ရှင်းပြီး","ပြန်ထည့်ပြီး","✅"]
                msg_type = "action" if any(k in final_answer for k in action_keywords) else "chat"

                st.session_state.chat_history.append({
                    "user": ai_cmd, "bot": final_answer,
                    "type": msg_type, "steps": steps
                })
                add_memory("user", ai_cmd)
                add_memory("agent", final_answer)

                st.session_state.ai_cmd = ""
                st.rerun()

            except Exception as e:
                st.error(f"Agent Error: {e}")

    elif ai_cmd and not st.session_state.resolved_api_key:
        st.warning("⚠️ Sidebar မှာ Gemini API Key ထည့်ပြီး Save လုပ်ပါ။")

def show_ledger_display():
    st.markdown("### 📋 လက်ရှိ မရှင်းရသေးသော မှာယူမှုများ")
    st.caption(
        "အပေါ်ဇယားမှာ ဖောက်သည်တစ်ဦးချင်း စုစုပေါင်း မြင်ရပါသည်။ အောက်က နာမည်ကို နှိပ်မှ ဇယားကွက်နဲ့ အသေးစိတ် ပေါ်ပါသည်။ "
        "ဇယားအောက်က ✏️ သည် အတန်းနံပါတ် (#) နှင့် တူညီသည် — နှိပ်မှ ပြင်/ဖျက်နိုင်သည်။"
    )

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
                st.caption("✏️ = ထိုအတန်း ပြင်/ဖျက် (ဇယားထဲက # နံပါတ်နှင့် တူညီ)")
                _max_btns = 12
                for chunk_start in range(0, len(row_list), _max_btns):
                    chunk = row_list[chunk_start : chunk_start + _max_btns]
                    btn_cols = st.columns(len(chunk))
                    for j, (idx, row) in enumerate(chunk):
                        ix = int(idx)
                        rn = chunk_start + j + 1
                        with btn_cols[j]:
                            if st.button(
                                "✏️",
                                key=f"lp_{gk}_{ix}",
                                help=f"အတန်း {rn} ပြင်/ဖျက်",
                            ):
                                st.session_state.ledger_edit_idx = ix
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
                    who = (st.session_state.user or {}).get("name") or "—"
                    clear_customer_bill(name, settled_by=who)
                    add_memory("agent", f"{name} ငွေရှင်းပြီး")
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
            st.table(customers_df)

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
            st.table(display_df)

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
            st.table(creditors_df.rename(columns={"CreditorName": "နာမည်"}))

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
            st.table(disp_pc.rename(columns={"ItemName": "ပစ္စည်း", "RefPrice": "မှတ်သားဈေး"}))

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
        st.table(pd.DataFrame(user_list))

    st.divider()

    # ==================== CHAT & MEMORY ====================
    col_m1, col_m2 = st.columns(2)
    if col_m1.button("🗑️ Chat ရှင်းမည်", use_container_width=True):
        st.session_state.chat_history = []
        st.rerun()
    if col_m2.button("🧠 Memory ရှင်းမည်", use_container_width=True):
        save_memory([])
        st.success("Memory cleared!")
        st.rerun()

    with st.expander("🧠 Memory Preview"):
        mem = load_memory()
        if mem:
            for m in mem[-8:]:
                st.caption(f"[{m['ts']}] {m['role']}: {m['text'][:60]}…" if len(m['text'])>60 else f"[{m['ts']}] {m['role']}: {m['text']}")
        else:
            st.info("Memory ဗလာ")

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

_app_cfg = get_config()
if st.session_state.user is None and _app_cfg.get("skip_login", True):
    try:
        st.session_state.user = default_auto_login_user()
    except Exception:
        pass

# CSS
st.markdown("""
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

        if st.session_state.user['role'] == 'admin':
            st.divider()
            st.info("🔧 Admin Mode - အပြည့်အစုံ စီမံနိုင်သည်")

        st.divider()
        st.markdown("##### ဘယ်ဘက် မီနူး")
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
