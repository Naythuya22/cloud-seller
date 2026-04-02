# Streamlit Community Cloud + GitHub

## ၁) GitHub သို့ တင်မည်

1. ဤပရောဂျက်ကို Git repository အဖြစ် တင်ပါ။
2. **API Key မတင်ပါနဲ့** — `GEMINI_API_KEY` ကို Streamlit Secrets မှသာ ထည့်ပါ။

## ၂) Streamlit Cloud ချိတ်မည်

1. [share.streamlit.io](https://share.streamlit.io) ဝင်ပါ။
2. **New app** → GitHub repo ရွေးပါ။
3. **Main file path:** `app.py`
4. **Branch:** `main` (သို့) သင့် default branch

## ၃) Secrets ထည့်မည်

App → **Settings** → **Secrets** တွင် ဥပမာ:

```toml
GEMINI_API_KEY = "xxxxxxxx"
model_name = "gemini-2.0-flash"
skip_login = true
```

- `GEMINI_API_KEY` — Google AI Studio / Gemini API key
- `skip_login` — `false` ထားပါက လော့ဂ်စာမျက်နှာ ပြန်ပေါ်မည်

ပြင်ပေးထားသော `app.py` က **Secrets ကို `config.json` ထက်ဦးစားပေး** သုံးပါသည်။

**သတိ:** Admin မှ API သိမ်းပါက `config.json` ပြန်ရေးပါတယ်။ Git push လုပ်မယ်ဆို API **repo ထဲမရောက်အောင်** `config.json` ကို `.gitignore` ထဲ ထည့်သင့် ပြီး Secrets တွင်သာ သိမ်းပါ။

## ၄) ဒေတာ မပျက်အောင် (အရေးကြီး)

Cloud မှာ **redeploy / restart** လုပ်တိုင်း **container ဖိုင်စနစ် ပြန်စ** ဖြစ်နိုင်ပါတယ်။

**လုပ်သင့်တာ (တစ်ခုခု ရွေးပါ):**

1. **Git ထဲ ဒေတာဖိုင်တွေ commit လုပ်ထား** — `master_data.xlsx`, `ledger_data.xlsx`, `users.json`, `purchase_data.xlsx`, `payable_data.xlsx`, `trash_data.xlsx`, `agent_memory.json`, `config.json` (API မပါစေ) စသည်။  
   - ပြန်တင်တိုင်း repo ထဲက နောက်ဆုံး commit ကို ပြန်သုံးပါမယ်။  
   - **လုပ်ဆောင်ချက်အတွင်း ရေးသိမ်းတာ** က နောက်တစ်ကြိမ် deploy မှာ ပျောက်နိုင်သဖြင့် **အရေးကြီးတဲ့ အပ်ဒိတ်တွေကို Git push လုပ်မှု** နဲ့ သိမ်းပါ။

2. သို့မဟုတ် နောက်ပိုင်း **ပြင်ပ database / Drive** သို့ ရွှေ့ဖို့ စီစဉ်ပါ။

## ၅) လိုအပ်သော ဖိုင်များ

- `requirements.txt` — Cloud က အလိုအလျောက် `pip install` လုပ်ပါသည်။
- `packages.txt` — RawBT ပုံ mode (`html2image`) အတွက် headless **chromium** လိုအပ်နိုင်ပါသည်။
- `.streamlit/config.toml` — ချိန်ညှိချက် (ထည့်ပြီးသား)

## ၆) ပြဿနာဖြေရှင်း

- **Module not found** — `requirements.txt` ထဲ package ထည့်ပါ။
- **Agent မလုပ်** — Secrets မှာ `GEMINI_API_KEY` စစ်ပါ။
- **ပထမဖွင့်ချိန် နောက်ကျ** — cold start ပုံမှန်ပါ။
