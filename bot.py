import os, re, json, time, threading, subprocess, io
import telebot
from telebot import types
import psutil
import requests
import qrcode
from PIL import Image

# ── CONFIG LOAD ───────────────────────────────────────────────────────────────
with open('.env', 'r') as f:
    configs = {}
    for line in f.readlines():
        line = line.strip()
        if '=' in line:
            k, v = line.split('=', 1)
            configs[k] = v.strip('"')

TOKEN   = configs.get('BOT_TOKEN')
ADMIN_ID = int(configs.get('ADMIN_ID'))
bot = telebot.TeleBot(TOKEN)
USER_STATES = {}
USER_DATA   = {}

CONFIG_FILE = 'config.json'

def load_config():
    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except:
        return {"cpu_alert_threshold": 80, "cpu_alert_enabled": True, "cpu_alert_cooldown_minutes": 10}

def save_config(cfg):
    with open(CONFIG_FILE, 'w') as f:
        json.dump(cfg, f, indent=2)

def is_admin(message):
    return message.chat.id == ADMIN_ID

def main_menu():
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    markup.add(
        types.KeyboardButton('📊 Dashboard'),
        types.KeyboardButton('💻 Terminal Mode'),
        types.KeyboardButton('🛡️ UFW Firewall'),
        types.KeyboardButton('🐳 Docker Manager'),
        types.KeyboardButton('👥 User Manager'),
        types.KeyboardButton('🗝️ Outline Server'),
        types.KeyboardButton('⚡ Speedtest'),
        types.KeyboardButton('🔔 Alert Settings'),
    )
    return markup

def progress_bar(value, max_val=100, length=10):
    filled = int(length * value / max_val)
    return '[' + '█' * filled + '░' * (length - filled) + ']'

def human_bytes(b):
    b = int(b)
    if b >= 1_073_741_824:
        return f"{b/1_073_741_824:.2f} GB"
    elif b >= 1_048_576:
        return f"{b/1_048_576:.2f} MB"
    elif b >= 1024:
        return f"{b/1024:.2f} KB"
    return f"{b} B"

# ── OUTLINE API DETECTOR ──────────────────────────────────────────────────────
def get_outline_api():
    api_pattern = re.compile(r'https://[\d.]+:\d+/[\w]+')
    scan_dirs = ['/opt/outline/', '/etc/outline/']
    if os.path.exists('/opt/outline/access.json'):
        try:
            with open('/opt/outline/access.json', 'r') as f:
                data = json.load(f)
                url = data.get('apiUrl') or data.get('api_url')
                if url:
                    return url
        except:
            pass
    for directory in scan_dirs:
        if not os.path.isdir(directory):
            continue
        for fname in os.listdir(directory):
            fpath = os.path.join(directory, fname)
            if os.path.isfile(fpath):
                try:
                    with open(fpath, 'r') as f:
                        content = f.read()
                    try:
                        data = json.loads(content)
                        url = data.get('apiUrl') or data.get('api_url')
                        if url:
                            return url
                    except:
                        pass
                    match = api_pattern.search(content)
                    if match:
                        return match.group(0)
                except:
                    pass
    return None

def get_outline_ports():
    cmd = subprocess.run(['sudo', 'docker', 'port', 'shadowbox'], capture_output=True, text=True)
    if cmd.returncode != 0:
        return []
    ports = []
    for line in cmd.stdout.strip().split('\n'):
        if '->' in line:
            port = line.split('->')[1].split(':')[1].strip()
            if port not in ports:
                ports.append(port)
    return ports

# ── CPU ALERT BACKGROUND THREAD ───────────────────────────────────────────────
_last_alert_time = 0

def cpu_alert_worker():
    global _last_alert_time
    while True:
        try:
            cfg = load_config()
            if cfg.get('cpu_alert_enabled', True):
                threshold  = cfg.get('cpu_alert_threshold', 80)
                cooldown   = cfg.get('cpu_alert_cooldown_minutes', 10) * 60
                cpu = psutil.cpu_percent(interval=2)
                now = time.time()
                if cpu >= threshold and (now - _last_alert_time) > cooldown:
                    _last_alert_time = now
                    ram  = psutil.virtual_memory().percent
                    disk = psutil.disk_usage('/').percent
                    text = (
                        "🚨 *HIGH CPU ALERT!*\n"
                        "━━━━━━━━━━━━━━━━━\n\n"
                        f"🧠 *CPU:*  {progress_bar(cpu)} `{cpu}%`\n"
                        f"💾 *RAM:*  {progress_bar(ram)} `{ram}%`\n"
                        f"🗄️ *Disk:* {progress_bar(disk)} `{disk}%`\n\n"
                        f"⚠️ CPU exceeded *{threshold}%* threshold!\n"
                        f"🕐 `{time.strftime('%Y-%m-%d %H:%M:%S')}`"
                    )
                    bot.send_message(ADMIN_ID, text, parse_mode='Markdown')
        except Exception:
            pass
        time.sleep(58)

alert_thread = threading.Thread(target=cpu_alert_worker, daemon=True)
alert_thread.start()

# ── MAIN HANDLERS ─────────────────────────────────────────────────────────────
@bot.message_handler(func=is_admin, commands=['start', 'menu'])
def send_welcome(message):
    USER_STATES[message.chat.id] = 'MAIN'
    bot.send_message(message.chat.id, "Welcome Back, Boss! 😎\nSystem is fully ready.", reply_markup=main_menu())

@bot.message_handler(func=lambda m: is_admin(m) and m.text == '📊 Dashboard')
def server_status(message):
    cpu  = psutil.cpu_percent(interval=0.5)
    ram  = psutil.virtual_memory().percent
    disk = psutil.disk_usage('/').percent
    net_before = psutil.net_io_counters()
    time.sleep(1.0)
    net_after  = psutil.net_io_counters()
    dl = (net_after.bytes_recv - net_before.bytes_recv) / 1024
    ul = (net_after.bytes_sent - net_before.bytes_sent) / 1024
    cfg = load_config()
    alert_status = "🟢 ON" if cfg.get('cpu_alert_enabled') else "🔴 OFF"
    text = (
        "📊 *SERVER DASHBOARD*\n\n"
        f"🧠 *CPU:*   {progress_bar(cpu)} {cpu}%\n"
        f"💾 *RAM:*   {progress_bar(ram)} {ram}%\n"
        f"🗄️ *Disk:*  {progress_bar(disk)} {disk}%\n\n"
        f"🌐 *Live Bandwidth:*\n"
        f"📥 Download: `{dl:.2f} KB/s`\n"
        f"📤 Upload:   `{ul:.2f} KB/s`\n\n"
        f"🔔 *CPU Alert:* {alert_status} (threshold: `{cfg.get('cpu_alert_threshold')}%`)"
    )
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

@bot.message_handler(func=lambda m: is_admin(m) and m.text == '🔔 Alert Settings')
def alert_settings(message):
    cfg = load_config()
    status    = "🟢 Enabled" if cfg.get('cpu_alert_enabled') else "🔴 Disabled"
    threshold = cfg.get('cpu_alert_threshold', 80)
    cooldown  = cfg.get('cpu_alert_cooldown_minutes', 10)
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🟢 Enable Alerts",  callback_data="alert_enable"),
        types.InlineKeyboardButton("🔴 Disable Alerts", callback_data="alert_disable"),
        types.InlineKeyboardButton("⚙️ Set CPU Threshold %", callback_data="alert_set_threshold"),
        types.InlineKeyboardButton("⏱️ Set Cooldown (min)",  callback_data="alert_set_cooldown"),
        types.InlineKeyboardButton("🧪 Test Alert Now",      callback_data="alert_test")
    )
    bot.send_message(message.chat.id,
        f"🔔 *CPU Alert Settings*\n\n"
        f"📊 *Status:*    {status}\n"
        f"🎯 *Threshold:* `{threshold}%`\n"
        f"⏱️ *Cooldown:*  `{cooldown} minutes`\n\n"
        f"Configure below:",
        reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(func=lambda m: is_admin(m) and m.text == '💻 Terminal Mode')
def toggle_terminal(message):
    USER_STATES[message.chat.id] = 'TERMINAL'
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(types.KeyboardButton('❌ Exit Terminal'))
    bot.send_message(message.chat.id, "💻 *Terminal Mode Activated!*\nType any shell command:", reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(func=lambda m: is_admin(m) and m.text == '❌ Exit Terminal')
def exit_terminal(message):
    USER_STATES[message.chat.id] = 'MAIN'
    bot.send_message(message.chat.id, "✅ Exited terminal mode.", reply_markup=main_menu())

@bot.message_handler(func=lambda m: is_admin(m) and m.text == '🛡️ UFW Firewall')
def ufw_menu(message):
    status_cmd = subprocess.run(['sudo', 'ufw', 'status'], capture_output=True, text=True)
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🟢 Enable UFW",  callback_data="ufw_enable"),
        types.InlineKeyboardButton("🔴 Disable UFW", callback_data="ufw_disable"),
        types.InlineKeyboardButton("➕ Allow Port",  callback_data="ufw_add"),
        types.InlineKeyboardButton("🗑️ Delete Rule", callback_data="ufw_delete")
    )
    bot.send_message(message.chat.id, f"🛡️ *UFW Firewall:*\n\n```\n{status_cmd.stdout.strip()}\n```", reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(func=lambda m: is_admin(m) and m.text == '🐳 Docker Manager')
def docker_menu(message):
    check_docker = subprocess.run(['which', 'docker'], capture_output=True, text=True)
    if not check_docker.stdout.strip():
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🟢 Yes, Install", callback_data="docker_confirm_install"),
            types.InlineKeyboardButton("❌ Cancel",        callback_data="cancel_action")
        )
        bot.send_message(message.chat.id, "🐳 Docker is not installed! Install now?", reply_markup=markup)
        return
    cmd = subprocess.run(['sudo', 'docker', 'ps', '-a', '--format', '{{.Names}} ({{.Status}})'], capture_output=True, text=True)
    containers = [c for c in cmd.stdout.strip().split('\n') if c]
    if not containers:
        bot.send_message(message.chat.id, "🐳 Docker active but no containers found.")
        return
    markup = types.InlineKeyboardMarkup(row_width=1)
    for container in containers:
        name = container.split(' ')[0]
        markup.add(types.InlineKeyboardButton(f"📦 {container}", callback_data=f"doc_manage_{name}"))
    bot.send_message(message.chat.id, "🐳 *Docker Containers:*", reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(func=lambda m: is_admin(m) and m.text == '👥 User Manager')
def users_menu(message):
    users_text = ""
    with open('/etc/passwd', 'r') as f:
        for line in f:
            parts = line.strip().split(':')
            if len(parts) >= 7:
                uname, _, uid, _, _, _, shell = parts[:7]
                if int(uid) >= 1000 and uname != 'nobody':
                    s = "🔓 Shell" if 'bash' in shell or '/sh' in shell else "🔒 No-Shell"
                    users_text += f"👤 *{uname}* — `{s}`\n"
    if not users_text:
        users_text = "No human users found."
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("🟢 Add Standard User", callback_data="user_add_normal"),
        types.InlineKeyboardButton("🔴 Add No-Shell User", callback_data="user_add_limited"),
        types.InlineKeyboardButton("🔑 Change Password",   callback_data="user_change_password"),
        types.InlineKeyboardButton("🗑️ Delete User",       callback_data="user_delete_select")
    )
    bot.send_message(message.chat.id, f"👥 *Server Users:*\n\n{users_text}\nChoose action:", reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(func=lambda m: is_admin(m) and m.text == '🗝️ Outline Server')
def outline_main_menu(message):
    markup = types.InlineKeyboardMarkup(row_width=1)
    markup.add(
        types.InlineKeyboardButton("🚀 Install Outline Server",  callback_data="out_inst_menu"),
        types.InlineKeyboardButton("🗑️ Remove Outline Server",   callback_data="out_rem_menu"),
        types.InlineKeyboardButton("⚙️ Manage Outline Keys",     callback_data="out_manage_menu"),
        types.InlineKeyboardButton("📊 Data Usage (All Keys)",   callback_data="out_usage_all"),
        types.InlineKeyboardButton("🔗 Show API URL",            callback_data="out_show_api")
    )
    bot.send_message(message.chat.id, "🗝️ *Outline Server Console:*", reply_markup=markup, parse_mode='Markdown')

@bot.message_handler(func=lambda m: is_admin(m) and m.text == '⚡ Speedtest')
def speedtest_handler(message):
    def run_speedtest():
        frames = [
            ("🔍", "Locating nearest test server..."),
            ("📡", "Establishing connection..."),
            ("📥", "Measuring Download speed..."),
            ("📤", "Measuring Upload speed..."),
            ("📊", "Calculating results..."),
        ]
        msg = bot.send_message(message.chat.id, "⚡ *Initializing Speedtest Engine...*", parse_mode='Markdown')
        for icon, txt in frames:
            time.sleep(1.2)
            try:
                bot.edit_message_text(f"{icon} *{txt}*\n\n`Please wait...`", message.chat.id, msg.message_id, parse_mode='Markdown')
            except:
                pass
        result = subprocess.run(['speedtest-cli', '--simple'], capture_output=True, text=True, timeout=120)
        output = result.stdout.strip()
        if result.returncode != 0 or not output:
            bot.edit_message_text("❌ Speedtest failed. Ensure `speedtest-cli` is installed.", message.chat.id, msg.message_id, parse_mode='Markdown')
            return
        ping_val = dl_val = ul_val = "N/A"
        for line in output.splitlines():
            if line.startswith("Ping"):
                ping_val = line.split(":")[1].strip()
            elif line.startswith("Download"):
                dl_val = line.split(":")[1].strip()
            elif line.startswith("Upload"):
                ul_val = line.split(":")[1].strip()
        def xmbps(v):
            try: return float(v.split()[0])
            except: return 0
        dl_bar = progress_bar(min(xmbps(dl_val), 1000), 1000, 12)
        ul_bar = progress_bar(min(xmbps(ul_val), 1000), 1000, 12)
        try:
            ping_icon = "🟢" if float(ping_val.split()[0]) < 30 else ("🟡" if float(ping_val.split()[0]) < 80 else "🔴")
        except:
            ping_icon = "⚪"
        bot.edit_message_text(
            "⚡ *SPEEDTEST RESULTS*\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            f"🏓 *Ping:*\n   {ping_icon} `{ping_val}`\n\n"
            f"📥 *Download:*\n   {dl_bar}\n   `{dl_val}`\n\n"
            f"📤 *Upload:*\n   {ul_bar}\n   `{ul_val}`\n\n"
            "━━━━━━━━━━━━━━━━━\n"
            f"🕐 `{time.strftime('%Y-%m-%d %H:%M:%S')}`",
            message.chat.id, msg.message_id, parse_mode='Markdown')
    threading.Thread(target=run_speedtest, daemon=True).start()

# ── STATE MACHINE TEXT HANDLER ────────────────────────────────────────────────
@bot.message_handler(func=is_admin, content_types=['text'])
def handle_text(message):
    chat_id = message.chat.id
    state   = USER_STATES.get(chat_id, 'MAIN')
    text    = message.text

    if state == 'TERMINAL':
        try:
            result = subprocess.run(text, shell=True, capture_output=True, text=True, timeout=30)
            out = (result.stdout or result.stderr or "(no output)")[-3800:]
            bot.send_message(chat_id, f"```\n{out}\n```", parse_mode='Markdown')
        except subprocess.TimeoutExpired:
            bot.send_message(chat_id, "⏰ Command timed out.")
        return

    if state == 'WANT_PORT':
        port = text.strip()
        subprocess.run(['sudo', 'ufw', 'allow', f"{port}/tcp"])
        subprocess.run(['sudo', 'ufw', 'allow', f"{port}/udp"])
        bot.send_message(chat_id, f"✅ Port `{port}` (TCP+UDP) allowed.", parse_mode='Markdown')
        USER_STATES[chat_id] = 'MAIN'; return

    if state == 'WANT_UFW_DELETE':
        subprocess.run(['sudo', 'ufw', 'delete', 'allow', text.strip()])
        bot.send_message(chat_id, f"🗑️ Rule `{text.strip()}` deleted.", parse_mode='Markdown')
        USER_STATES[chat_id] = 'MAIN'; return

    if state == 'USER_ADD_NORMAL':
        USER_DATA[chat_id] = {'new_user': text.strip()}
        USER_STATES[chat_id] = 'USER_SET_PASS'
        bot.send_message(chat_id, f"🔑 Set a password for *{text.strip()}*:", parse_mode='Markdown'); return

    if state == 'USER_ADD_LIMITED':
        subprocess.run(['sudo', 'useradd', '-s', '/usr/sbin/nologin', text.strip()])
        bot.send_message(chat_id, f"✅ No-shell user *{text.strip()}* created.", parse_mode='Markdown')
        USER_STATES[chat_id] = 'MAIN'; return

    if state == 'USER_SET_PASS':
        uname = USER_DATA.get(chat_id, {}).get('new_user')
        if uname:
            subprocess.run(['sudo', 'useradd', '-m', '-s', '/bin/bash', uname])
            subprocess.run(['sudo', 'chpasswd'], input=f"{uname}:{text.strip()}", text=True)
            bot.send_message(chat_id, f"✅ User *{uname}* created.", parse_mode='Markdown')
        USER_STATES[chat_id] = 'MAIN'; return

    if state == 'USER_CHANGE_PASS_NAME':
        USER_DATA[chat_id] = {'chpass_user': text.strip()}
        USER_STATES[chat_id] = 'USER_CHANGE_PASS_VAL'
        bot.send_message(chat_id, f"🔑 New password for *{text.strip()}*:", parse_mode='Markdown'); return

    if state == 'USER_CHANGE_PASS_VAL':
        uname = USER_DATA.get(chat_id, {}).get('chpass_user')
        if uname:
            subprocess.run(['sudo', 'chpasswd'], input=f"{uname}:{text.strip()}", text=True)
            bot.send_message(chat_id, f"✅ Password for *{uname}* updated.", parse_mode='Markdown')
        USER_STATES[chat_id] = 'MAIN'; return

    if state == 'USER_DELETE':
        subprocess.run(['sudo', 'userdel', '-r', text.strip()])
        bot.send_message(chat_id, f"🗑️ User *{text.strip()}* deleted.", parse_mode='Markdown')
        USER_STATES[chat_id] = 'MAIN'; return

    if state == 'OUT_CREATE_KEY_NAME':
        key_name = text.strip()
        api_url  = get_outline_api()
        if not api_url:
            bot.send_message(chat_id, "❌ API URL not found.")
            USER_STATES[chat_id] = 'MAIN'; return
        try:
            resp = requests.post(f"{api_url}/access-keys", verify=False, timeout=10)
            key  = resp.json()
            kid  = key['id']
            requests.put(f"{api_url}/access-keys/{kid}/name", json={"name": key_name}, verify=False, timeout=10)
            access_url = key.get('accessUrl', 'N/A')
            # Send key info + QR
            bot.send_message(chat_id,
                f"✅ *New Key Created!*\n\n"
                f"👤 *Name:* `{key_name}`\n"
                f"🆔 *ID:* `{kid}`\n\n"
                f"🔗 *Access URL:*\n`{access_url}`",
                parse_mode='Markdown')
            _send_qr(chat_id, access_url, key_name)
        except Exception as e:
            bot.send_message(chat_id, f"❌ Error: `{e}`", parse_mode='Markdown')
        USER_STATES[chat_id] = 'MAIN'; return

    if state == 'OUT_DELETE_KEY':
        api_url = get_outline_api()
        if api_url:
            try:
                resp = requests.delete(f"{api_url}/access-keys/{text.strip()}", verify=False, timeout=10)
                if resp.status_code == 204:
                    bot.send_message(chat_id, f"✅ Key `{text.strip()}` deleted.", parse_mode='Markdown')
                else:
                    bot.send_message(chat_id, f"❌ Failed. Status: `{resp.status_code}`", parse_mode='Markdown')
            except Exception as e:
                bot.send_message(chat_id, f"❌ Error: `{e}`", parse_mode='Markdown')
        USER_STATES[chat_id] = 'MAIN'; return

    if state == 'OUT_RENAME_KEY_ID':
        USER_DATA[chat_id]['rename_key_id'] = text.strip()
        USER_STATES[chat_id] = 'OUT_RENAME_KEY_NAME'
        bot.send_message(chat_id, "✏️ Enter new name:"); return

    if state == 'OUT_RENAME_KEY_NAME':
        kid  = USER_DATA.get(chat_id, {}).get('rename_key_id')
        api_url = get_outline_api()
        if api_url and kid:
            try:
                requests.put(f"{api_url}/access-keys/{kid}/name", json={"name": text.strip()}, verify=False, timeout=10)
                bot.send_message(chat_id, f"✅ Key `{kid}` renamed to *{text.strip()}*.", parse_mode='Markdown')
            except Exception as e:
                bot.send_message(chat_id, f"❌ Error: `{e}`", parse_mode='Markdown')
        USER_STATES[chat_id] = 'MAIN'; return

    if state == 'OUT_SET_LIMIT_AMOUNT':
        try:
            parts = text.strip().split()
            amount = float(parts[0])
            unit   = parts[1].upper() if len(parts) > 1 else 'GB'
            mult   = {'GB': 1_073_741_824, 'MB': 1_048_576, 'KB': 1024}.get(unit, 1_073_741_824)
            bytes_limit = int(amount * mult)
            kid = USER_DATA.get(chat_id, {}).get('limit_key_id')
            api_url = get_outline_api()
            if api_url and kid:
                requests.put(
                    f"{api_url}/access-keys/{kid}/data-limit",
                    json={"limit": {"bytes": bytes_limit}},
                    verify=False, timeout=10
                )
                bot.send_message(chat_id, f"✅ Data limit set to `{amount} {unit}` for key `{kid}`.", parse_mode='Markdown')
            else:
                bot.send_message(chat_id, "❌ Could not set limit.")
        except Exception as e:
            bot.send_message(chat_id, f"❌ Error: `{e}`\nFormat: `10 GB` or `500 MB`", parse_mode='Markdown')
        USER_STATES[chat_id] = 'MAIN'; return

    if state == 'ALERT_SET_THRESHOLD':
        try:
            val = int(text.strip())
            if not 1 <= val <= 99:
                raise ValueError
            cfg = load_config()
            cfg['cpu_alert_threshold'] = val
            save_config(cfg)
            bot.send_message(chat_id, f"✅ CPU alert threshold set to `{val}%`.", parse_mode='Markdown')
        except:
            bot.send_message(chat_id, "❌ Enter a number between 1 and 99.")
        USER_STATES[chat_id] = 'MAIN'; return

    if state == 'ALERT_SET_COOLDOWN':
        try:
            val = int(text.strip())
            if val < 1:
                raise ValueError
            cfg = load_config()
            cfg['cpu_alert_cooldown_minutes'] = val
            save_config(cfg)
            bot.send_message(chat_id, f"✅ Cooldown set to `{val} minutes`.", parse_mode='Markdown')
        except:
            bot.send_message(chat_id, "❌ Enter a positive integer (minutes).")
        USER_STATES[chat_id] = 'MAIN'; return

# ── QR HELPER ─────────────────────────────────────────────────────────────────
def _send_qr(chat_id, url, label=""):
    try:
        qr = qrcode.QRCode(version=1, error_correction=qrcode.constants.ERROR_CORRECT_L, box_size=10, border=4)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)
        bot.send_photo(chat_id, buf, caption=f"📱 *QR Code for:* `{label}`", parse_mode='Markdown')
    except Exception as e:
        bot.send_message(chat_id, f"❌ QR generation failed: `{e}`", parse_mode='Markdown')

# ── CALLBACK HANDLERS ─────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda call: True)
def handle_callbacks(call):
    chat_id = call.message.chat.id
    mid     = call.message.message_id

    if call.data == "cancel_action":
        bot.edit_message_text("❌ Action cancelled.", chat_id, mid)

    # ── UFW ───────────────────────────────────────────────────────────────────
    elif call.data == "ufw_enable":
        subprocess.run(['sudo', 'ufw', '--force', 'enable'])
        bot.answer_callback_query(call.id, "UFW Enabled!")
        ufw_menu(call.message)
    elif call.data == "ufw_disable":
        subprocess.run(['sudo', 'ufw', 'disable'])
        bot.answer_callback_query(call.id, "UFW Disabled!")
        ufw_menu(call.message)
    elif call.data == "ufw_add":
        USER_STATES[chat_id] = 'WANT_PORT'
        bot.send_message(chat_id, "Enter port to ALLOW (e.g. `8080`):", parse_mode='Markdown')
    elif call.data == "ufw_delete":
        USER_STATES[chat_id] = 'WANT_UFW_DELETE'
        bot.send_message(chat_id, "Enter port/rule to DELETE:", parse_mode='Markdown')

    # ── DOCKER ────────────────────────────────────────────────────────────────
    elif call.data == "docker_confirm_install":
        bot.edit_message_text("⚙️ Installing Docker Engine...", chat_id, mid)
        subprocess.run("curl -fsSL https://get.docker.com | sh", shell=True)
        bot.send_message(chat_id, "✅ Docker installed!")
        docker_menu(call.message)

    elif call.data.startswith("doc_manage_"):
        c_name = call.data.replace("doc_manage_", "")
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("▶️ Start",    callback_data=f"d_start_{c_name}"),
            types.InlineKeyboardButton("⏹️ Stop",     callback_data=f"d_stop_{c_name}"),
            types.InlineKeyboardButton("🔄 Restart",  callback_data=f"d_rest_{c_name}"),
            types.InlineKeyboardButton("📄 Logs",     callback_data=f"d_logs_{c_name}")
        )
        bot.send_message(chat_id, f"📦 Managing: *{c_name}*", reply_markup=markup, parse_mode='Markdown')

    elif call.data.startswith("d_"):
        parts  = call.data.split('_', 2)
        action, c_name = parts[1], parts[2]
        cmds = {'start': 'start', 'stop': 'stop', 'rest': 'restart'}
        if action in cmds:
            subprocess.run(['sudo', 'docker', cmds[action], c_name])
            bot.send_message(chat_id, f"✅ `{c_name}` → {cmds[action]}", parse_mode='Markdown')
        elif action == 'logs':
            cmd = subprocess.run(['sudo', 'docker', 'logs', '--tail', '10', c_name], capture_output=True, text=True)
            bot.send_message(chat_id, f"📄 *Logs ({c_name}):*\n```\n{(cmd.stdout or cmd.stderr)[-3000:]}\n```", parse_mode='Markdown')

    # ── USER MANAGER ──────────────────────────────────────────────────────────
    elif call.data == "user_add_normal":
        USER_STATES[chat_id] = 'USER_ADD_NORMAL'
        bot.send_message(chat_id, "Enter username for new standard user:")
    elif call.data == "user_add_limited":
        USER_STATES[chat_id] = 'USER_ADD_LIMITED'
        bot.send_message(chat_id, "Enter username for no-shell user:")
    elif call.data == "user_change_password":
        USER_STATES[chat_id] = 'USER_CHANGE_PASS_NAME'
        bot.send_message(chat_id, "Enter username to change password for:")
    elif call.data == "user_delete_select":
        USER_STATES[chat_id] = 'USER_DELETE'
        bot.send_message(chat_id, "⚠️ Enter username to DELETE:")

    # ── ALERT SETTINGS ────────────────────────────────────────────────────────
    elif call.data == "alert_enable":
        cfg = load_config(); cfg['cpu_alert_enabled'] = True; save_config(cfg)
        bot.answer_callback_query(call.id, "✅ Alerts Enabled!")
        alert_settings(call.message)
    elif call.data == "alert_disable":
        cfg = load_config(); cfg['cpu_alert_enabled'] = False; save_config(cfg)
        bot.answer_callback_query(call.id, "🔴 Alerts Disabled!")
        alert_settings(call.message)
    elif call.data == "alert_set_threshold":
        USER_STATES[chat_id] = 'ALERT_SET_THRESHOLD'
        bot.send_message(chat_id, "🎯 Enter CPU threshold percentage (1-99):")
    elif call.data == "alert_set_cooldown":
        USER_STATES[chat_id] = 'ALERT_SET_COOLDOWN'
        bot.send_message(chat_id, "⏱️ Enter cooldown duration in minutes:")
    elif call.data == "alert_test":
        cpu  = psutil.cpu_percent(interval=1)
        ram  = psutil.virtual_memory().percent
        disk = psutil.disk_usage('/').percent
        cfg  = load_config()
        bot.send_message(chat_id,
            "🧪 *TEST ALERT*\n"
            "━━━━━━━━━━━━━━━━━\n\n"
            f"🧠 *CPU:*  {progress_bar(cpu)} `{cpu}%`\n"
            f"💾 *RAM:*  {progress_bar(ram)} `{ram}%`\n"
            f"🗄️ *Disk:* {progress_bar(disk)} `{disk}%`\n\n"
            f"🎯 Threshold: `{cfg.get('cpu_alert_threshold')}%`\n"
            f"⏱️ Cooldown: `{cfg.get('cpu_alert_cooldown_minutes')} min`\n\n"
            "✅ Alert system is working!",
            parse_mode='Markdown')

    # ── OUTLINE ───────────────────────────────────────────────────────────────
    elif call.data == "out_show_api":
        api_url = get_outline_api()
        if not api_url:
            bot.send_message(chat_id, "❌ API URL not found.")
            return
        bot.send_message(chat_id, f"🔗 *Outline API URL:*\n\n`{api_url}`", parse_mode='Markdown')

    elif call.data == "out_usage_all":
        api_url = get_outline_api()
        if not api_url:
            bot.send_message(chat_id, "❌ API URL not found."); return
        try:
            keys_resp  = requests.get(f"{api_url}/access-keys",        verify=False, timeout=10)
            usage_resp = requests.get(f"{api_url}/metrics/transfer",   verify=False, timeout=10)
            keys  = keys_resp.json().get('accessKeys', [])
            usage = usage_resp.json().get('bytesTransferredByUserId', {})
            if not keys:
                bot.send_message(chat_id, "📊 No keys found."); return
            text = "📊 *Outline Data Usage Report*\n━━━━━━━━━━━━━━━━━\n\n"
            total = 0
            for k in keys:
                kid  = str(k['id'])
                name = k.get('name') or f"Key #{kid}"
                used = int(usage.get(kid, 0))
                total += used
                bar  = progress_bar(min(used, 10_737_418_240), 10_737_418_240, 8)
                # Check if limit exists
                limit_info = ""
                if 'dataLimit' in k:
                    limit_bytes = k['dataLimit'].get('bytes', 0)
                    pct = min(int(used / limit_bytes * 100), 100) if limit_bytes else 0
                    limit_info = f" / {human_bytes(limit_bytes)} `({pct}%)`"
                text += f"👤 *{name}*\n   {bar} `{human_bytes(used)}`{limit_info}\n\n"
            text += f"━━━━━━━━━━━━━━━━━\n📦 *Total:* `{human_bytes(total)}`"
            bot.send_message(chat_id, text, parse_mode='Markdown')
        except Exception as e:
            bot.send_message(chat_id, f"❌ Error: `{e}`", parse_mode='Markdown')

    elif call.data == "out_inst_menu":
        check = subprocess.run(['sudo', 'docker', 'ps', '-a', '--format', '{{.Names}}'], capture_output=True, text=True)
        if "shadowbox" in check.stdout:
            bot.send_message(chat_id, "💡 Outline Server is already installed!"); return
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("🟢 Yes, Install", callback_data="out_confirm_install"),
            types.InlineKeyboardButton("❌ Cancel",        callback_data="cancel_action")
        )
        bot.send_message(chat_id, "❓ Install Outline Server now?", reply_markup=markup)

    elif call.data == "out_confirm_install":
        bot.edit_message_text("🚀 Running Outline installer... Please wait 1–2 minutes.", chat_id, mid)
        cmd = subprocess.run(
            'sudo bash -c "$(wget -qO- https://raw.githubusercontent.com/OutlineFoundation/outline-apps/master/server_manager/install_scripts/install_server.sh)"',
            shell=True, capture_output=True, text=True)
        output = (cmd.stdout or cmd.stderr or "No output.")[-4000:]
        bot.send_message(chat_id, f"🎉 *Outline Installed!*\n```\n{output}\n```", parse_mode='Markdown')
        ports = get_outline_ports()
        if ports:
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton("⚡ Auto-Configure UFW", callback_data="out_fix_ufw"))
            bot.send_message(chat_id, f"⚠️ Open ports `{', '.join(ports)}`?", reply_markup=markup, parse_mode='Markdown')

    elif call.data == "out_fix_ufw":
        ports = get_outline_ports()
        if not ports:
            bot.send_message(chat_id, "❌ No Outline ports found."); return
        for p in ports:
            subprocess.run(['sudo', 'ufw', 'allow', f"{p}/tcp"])
            subprocess.run(['sudo', 'ufw', 'allow', f"{p}/udp"])
        bot.send_message(chat_id, f"✅ UFW opened: `{', '.join(ports)}`", parse_mode='Markdown')

    elif call.data == "out_rem_menu":
        markup = types.InlineKeyboardMarkup(row_width=2)
        markup.add(
            types.InlineKeyboardButton("⚠️ Yes, PURGE", callback_data="out_confirm_remove"),
            types.InlineKeyboardButton("❌ Cancel",      callback_data="cancel_action")
        )
        bot.send_message(chat_id, "❗ PURGE Outline containers?", reply_markup=markup)

    elif call.data == "out_confirm_remove":
        bot.edit_message_text("🗑️ Removing Outline...", chat_id, mid)
        subprocess.run(['sudo', 'docker', 'stop', 'shadowbox', 'watchtower'])
        subprocess.run(['sudo', 'docker', 'rm',   'shadowbox', 'watchtower'])
        bot.send_message(chat_id, "✨ Outline containers removed.")

    elif call.data == "out_manage_menu":
        api_url = get_outline_api()
        if not api_url:
            bot.send_message(chat_id,
                "❌ *Outline API URL not found.*\n\n"
                "Searched: `/opt/outline/` and `/etc/outline/`\n"
                "Make sure Outline is installed and running.",
                parse_mode='Markdown'); return
        markup = types.InlineKeyboardMarkup(row_width=1)
        markup.add(
            types.InlineKeyboardButton("📋 List All Keys",    callback_data="out_list_keys"),
            types.InlineKeyboardButton("➕ Create New Key",   callback_data="out_create_key"),
            types.InlineKeyboardButton("✏️ Rename a Key",     callback_data="out_rename_key_prompt"),
            types.InlineKeyboardButton("⚙️ Set Data Limit",   callback_data="out_set_limit_prompt"),
            types.InlineKeyboardButton("🗑️ Delete a Key",     callback_data="out_delete_key_prompt")
        )
        bot.send_message(chat_id, "⚙️ *Outline Key Management:*", reply_markup=markup, parse_mode='Markdown')

    elif call.data == "out_list_keys":
        api_url = get_outline_api()
        if not api_url:
            bot.send_message(chat_id, "❌ API URL not found."); return
        try:
            keys_resp  = requests.get(f"{api_url}/access-keys",      verify=False, timeout=10)
            usage_resp = requests.get(f"{api_url}/metrics/transfer", verify=False, timeout=10)
            keys  = keys_resp.json().get('accessKeys', [])
            usage = usage_resp.json().get('bytesTransferredByUserId', {})
            if not keys:
                bot.send_message(chat_id, "📋 No keys found."); return
            markup = types.InlineKeyboardMarkup(row_width=1)
            for k in keys:
                kid  = str(k['id'])
                name = k.get('name') or f"Key #{kid}"
                used = human_bytes(int(usage.get(kid, 0)))
                markup.add(types.InlineKeyboardButton(
                    f"🔑 {name}  |  📊 {used}", callback_data=f"out_key_detail_{kid}"))
            bot.send_message(chat_id, f"📋 *Keys ({len(keys)} total) — tap to manage:*",
                             reply_markup=markup, parse_mode='Markdown')
        except Exception as e:
            bot.send_message(chat_id, f"❌ Error: `{e}`", parse_mode='Markdown')

    elif call.data.startswith("out_key_detail_"):
        key_id  = call.data.replace("out_key_detail_", "")
        api_url = get_outline_api()
        if not api_url:
            bot.send_message(chat_id, "❌ API URL not found."); return
        try:
            resp  = requests.get(f"{api_url}/access-keys/{key_id}", verify=False, timeout=10)
            usage_resp = requests.get(f"{api_url}/metrics/transfer", verify=False, timeout=10)
            k     = resp.json()
            name  = k.get('name') or f"Key #{key_id}"
            aurl  = k.get('accessUrl', 'N/A')
            usage = usage_resp.json().get('bytesTransferredByUserId', {})
            used  = human_bytes(int(usage.get(str(key_id), 0)))
            limit_line = ""
            if 'dataLimit' in k:
                lb = k['dataLimit'].get('bytes', 0)
                limit_line = f"\n⚙️ *Limit:* `{human_bytes(lb)}`"
            markup = types.InlineKeyboardMarkup(row_width=2)
            markup.add(
                types.InlineKeyboardButton("📱 Share QR",      callback_data=f"out_qr_{key_id}"),
                types.InlineKeyboardButton("🗑️ Delete",        callback_data=f"out_key_del_{key_id}"),
                types.InlineKeyboardButton("◀️ Back",          callback_data="out_list_keys")
            )
            bot.send_message(chat_id,
                f"🔑 *Key Details*\n\n"
                f"👤 *Name:* `{name}`\n"
                f"🆔 *ID:* `{key_id}`\n"
                f"📊 *Used:* `{used}`{limit_line}\n\n"
                f"🔗 *Access URL:*\n`{aurl}`",
                reply_markup=markup, parse_mode='Markdown')
        except Exception as e:
            bot.send_message(chat_id, f"❌ Error: `{e}`", parse_mode='Markdown')

    elif call.data.startswith("out_qr_"):
        key_id  = call.data.replace("out_qr_", "")
        api_url = get_outline_api()
        if not api_url:
            bot.send_message(chat_id, "❌ API URL not found."); return
        try:
            resp = requests.get(f"{api_url}/access-keys/{key_id}", verify=False, timeout=10)
            k    = resp.json()
            name = k.get('name') or f"Key #{key_id}"
            aurl = k.get('accessUrl', '')
            if not aurl:
                bot.send_message(chat_id, "❌ No access URL found for this key."); return
            _send_qr(chat_id, aurl, name)
        except Exception as e:
            bot.send_message(chat_id, f"❌ Error: `{e}`", parse_mode='Markdown')

    elif call.data.startswith("out_key_del_"):
        key_id  = call.data.replace("out_key_del_", "")
        api_url = get_outline_api()
        if not api_url:
            bot.send_message(chat_id, "❌ API URL not found."); return
        try:
            resp = requests.delete(f"{api_url}/access-keys/{key_id}", verify=False, timeout=10)
            if resp.status_code == 204:
                bot.edit_message_text(f"✅ Key `{key_id}` deleted.", chat_id, mid, parse_mode='Markdown')
            else:
                bot.send_message(chat_id, f"❌ Failed. Status: `{resp.status_code}`", parse_mode='Markdown')
        except Exception as e:
            bot.send_message(chat_id, f"❌ Error: `{e}`", parse_mode='Markdown')

    elif call.data == "out_create_key":
        USER_STATES[chat_id] = 'OUT_CREATE_KEY_NAME'
        bot.send_message(chat_id, "👤 Enter a name for the new access key:")

    elif call.data == "out_rename_key_prompt":
        USER_STATES[chat_id] = 'OUT_RENAME_KEY_ID'
        USER_DATA[chat_id]   = {}
        bot.send_message(chat_id, "Enter Key ID to rename:")

    elif call.data == "out_set_limit_prompt":
        api_url = get_outline_api()
        if not api_url:
            bot.send_message(chat_id, "❌ API URL not found."); return
        try:
            keys_resp = requests.get(f"{api_url}/access-keys", verify=False, timeout=10)
            keys = keys_resp.json().get('accessKeys', [])
            if not keys:
                bot.send_message(chat_id, "📋 No keys found."); return
            markup = types.InlineKeyboardMarkup(row_width=1)
            for k in keys:
                kid  = str(k['id'])
                name = k.get('name') or f"Key #{kid}"
                markup.add(types.InlineKeyboardButton(f"⚙️ {name} (ID: {kid})", callback_data=f"out_set_limit_{kid}"))
            bot.send_message(chat_id, "Select key to set data limit:", reply_markup=markup)
        except Exception as e:
            bot.send_message(chat_id, f"❌ Error: `{e}`", parse_mode='Markdown')

    elif call.data.startswith("out_set_limit_"):
        key_id = call.data.replace("out_set_limit_", "")
        USER_DATA[chat_id]   = {'limit_key_id': key_id}
        USER_STATES[chat_id] = 'OUT_SET_LIMIT_AMOUNT'
        bot.send_message(chat_id,
            f"⚙️ Set data limit for key `{key_id}`\n\n"
            f"Format: `10 GB` or `500 MB`\n"
            f"Type `0` to remove limit.",
            parse_mode='Markdown')

    elif call.data == "out_delete_key_prompt":
        USER_STATES[chat_id] = 'OUT_DELETE_KEY'
        bot.send_message(chat_id, "Enter Key ID to delete:")

print(f"🚀 Bot running — Admin: {ADMIN_ID}")
bot.infinity_polling()
