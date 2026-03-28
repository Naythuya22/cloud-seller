# Streamlit Community Cloud + GitHub

ဤ folder (`D:\Cloud seller`) မှာ **Git စတင်ပြီး push လုပ်ရုံ** နဲ့ Streamlit Cloud ချိတ်နိုင်အောင် ပြင်ဆင်ထားပါသည်။

---

## ၀) လက်ရှိ ပြင်ဆင်ပြီး (repo အတွင်း)

- **`config.json` ကို `.gitignore` ထဲ ထည့်ထားပါသည်** — API key GitHub သို့ မတင်ပါ။
- **`config.json.example`** — လက်တွေ့ `config.json` လုပ်ရန် template (local သာ သုံးပါ)။
- Cloud မှာ **`st.secrets` မှ `GEMINI_API_KEY`** သုံးပါသည် (`app.py` က secrets ကို ဦးစားပေး)။

**လုပ်ပြီးသား laptop မှာ:** `config.json` က folder ထဲ ဆက်ရှိနိုင်ပါသည်; `git push` လုပ်လည်း ignore ဖြစ်သဖြင့် **repo ထဲ မဝင်ပါ**။

---

## ၁) GitHub သို့ ပထမတင်ခြင်း (PowerShell)

1. **GitHub ဝဘ်** — [github.com/new](https://github.com/new) မှာ repository အသစ် ဖန်တီးပါ။  
   - အမည် ဥပမာ: `cloud-seller`  
   - **Add a README မထည့်ပါနဲ့** (ပြဿနာရှောင်ရန် empty repo)  
   - Create repository နှိပ်ပါ။

2. Terminal:

```powershell
cd "D:\Cloud seller"
git init
git add -A
git status
```

`git status` မှာ **`config.json` မပေါ်ရပါ** (ပေါ်နေရင် မဆက်ပါနဲ့ — `.gitignore` စစ်ပါ)။

3. ပထ commit:

```powershell
git commit -m "Initial commit: Streamlit app for Cloud"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

`YOUR_USERNAME` / `YOUR_REPO` ကို သင် ဖန်တီးထားသော repo URL နဲ့ အစားထိုးပါ။

**GitHub CLI (`gh`) မလိုပါ** — ဝဘ်မှ ဖန်တီးပြီး အထက်က `remote` သုံးပါ။

---

## ၂) Streamlit Cloud ချိတ်မည်

1. [share.streamlit.io](https://share.streamlit.io) ဝင်ပါ။
2. **New app** → GitHub ချိတ်ပါ (ပထမဆုံး အကြိမ် GitHub ခွင့်ပြုချက် လိုအပ်နိုင်ပါသည်)။
3. **Repository** ရွေးပါ။
4. **Main file path:** `app.py`
5. **Branch:** `main`

Deploy နှိပ်ပြီး ပြီးသည့်တိုင်အောင် စောင့်ပါ။

---

## ၃) Secrets ထည့်မည် (မထည့်ရင် Gemini မလုပ်)

Deployed app → **⚙ Settings** → **Secrets** တွင်:

```toml
GEMINI_API_KEY = "your-key-here"
model_name = "gemini-2.0-flash"
skip_login = true
```

- `GEMINI_API_KEY` — [Google AI Studio](https://aistudio.google.com/apikey) မှ API key  
- `model_name` — ချိန်ညှိလိုမှ ထည့် (မထည့်ရင် app default သုံးပါသည်)  
- `skip_login` — `false` ထားပါက လော့ဂ်စာမျက်နှာ ပြန်ပေါ်မည်

သိမ်းပြီး app ကို **Reboot** (သို့) Redeploy လုပ်ပါ။

---

## ၄) ဒေတာ မပျက်အောင် (အရေးကြီး)

Cloud မှာ **redeploy / restart** တိုင်း container ဖိုင်စနစ် ပြန်စ ဖြစ်နိုင်ပါတယ်။

**လုပ်သင့်တာ (တစ်ခုခု ရွေးပါ):**

1. **Git ထဲ ဒေတာဖိုင်တွေ commit + push လုပ်ထား** — `master_data.xlsx`, `ledger_data.xlsx`, `users.json`, `purchase_data.xlsx`, `payable_data.xlsx`, `trash_data.xlsx`, `agent_memory.json` စသည်။  
   - **မထည့်သင့်:** `config.json` (API ပါနိုင်၍ `.gitignore` ထဲရှိပြီး) — Cloud မှာ **Secrets** သုံးပါ။  
   - အရေးကြီးသော Excel/JSON အပ်ဒိတ်တွေကို **push နဲ့ သိမ်းပါ** — မလုပ်ရင် နောက်တစ်ကြိမ် deploy မှာ ပျောက်နိုင်ပါသည်။

2. သို့မဟုတ် နောက်ပိုင်း **database / Drive** သို့ ရွှေ့ဖို့ စီစဉ်ပါ။

---

## ၅) လိုအပ်သော ဖိုင်များ (repo ထဲ)

- `app.py`, `requirements.txt`, `runtime.txt`
- `.streamlit/config.toml`
- ဒေတာ ဖိုင်များ (လိုသလို)
- `config.json.example` (template)

---

## ၆) ပြဿနာဖြေရှင်း

- **Module not found** — `requirements.txt` ထဲ package ထည့်ပြီး push။
- **Agent မလုပ် / API error** — Secrets မှာ `GEMINI_API_KEY` မှန်မမှန်၊ app reboot။
- **ပထမဖွင့်ချိန် နောက်ကျ** — cold start ပုံမှန်ပါ။
- **push မှာ authentication** — GitHub က personal access token သို့မဟုတ် Git Credential Manager သုံးပါ။
