import os
import threading
import time
from flask import Flask, render_template, request, jsonify, redirect
import client
import i18n

app = Flask(__name__)


@app.context_processor
def inject_i18n():
    lang = client.load_state().get('lang', i18n.DEFAULT_LANG)
    if lang not in i18n.LANGUAGES:
        lang = i18n.DEFAULT_LANG
    return {"t": i18n.make_translator(lang), "lang": lang, "languages": i18n.LANGUAGES,
            "brand": os.environ.get("BRAND_NAME", "SCARLET")}


@app.route('/lang/<code>')
def set_language(code):
    if code in i18n.LANGUAGES:
        st = client.load_state()
        st['lang'] = code
        client.save_state(st)
    return redirect(request.referrer or '/')

def background_poller():
    while True:
        interval = client.DEFAULT_POLL
        try:
            state = client.load_state()
            if state.get("status") == "paired":
                # Adaptive control loop: the server tells us how soon to poll again
                interval = client.send_status("paired") or client.DEFAULT_POLL
                # Forward any pending Suricata alerts to the central server
                client.flush_suricata()
        except Exception:
            pass
        time.sleep(max(2, min(int(interval), 60)))

# Start poller thread
polling_thread = threading.Thread(target=background_poller, daemon=True)
polling_thread.start()

@app.route('/')
def index():
    state = client.load_state()
    return render_template('index.html', state=state)

@app.route('/connect', methods=['POST'])
def connect():
    import socket
    probe_name = request.form.get('probe_name') or socket.gethostname()
    license_code = request.form.get('license_code', '')
    tenant_id = request.form.get('tenant_id', '').strip()
    
    metadata = {
        "address": request.form.get('meta_address', ''),
        "coordinates": request.form.get('meta_coords', ''),
        "contact": request.form.get('meta_contact', ''),
        "email": request.form.get('meta_email', ''),
        "telegram": request.form.get('meta_telegram', '')
    }
    
    result = client.connect_to_server(probe_name, license_code, tenant_id, metadata)
    return jsonify(result)

@app.route('/api/probe/reset', methods=['POST'])
def reset_probe():
    client.reset_state()
    return jsonify({"message": "Probe state reset successfully."})

@app.route('/scanner')
def scanner():
    state = client.load_state()
    return render_template('scanner.html', state=state)

@app.route('/api/scan/config', methods=['POST'])
def save_scan_config():
    subnet = request.form.get('subnet', '').strip()
    state = client.load_state()
    state['subnet'] = subnet
    client.save_state(state)
    return jsonify({"message": "Configuration saved successfully."})

@app.route('/suricata')
def suricata():
    return render_template('suricata.html')

@app.route('/wireless')
def wireless_page():
    state = client.load_state()
    return render_template('wireless.html', state=state)

@app.route('/guide')
def guide_page():
    return render_template('guide.html')

@app.route('/api/wireless/scan', methods=['POST'])
def api_wireless_scan():
    import wireless
    kind = request.form.get('type', 'wifi')
    state = client.load_state()
    if kind == 'ble':
        res = wireless.scan_ble(request.form.get('timeout', 10))
        client._send_encrypted('/api/probes/ble', {"devices": res["devices"]}, state)
        return jsonify({"type": "ble", "items": res["devices"], "note": res["note"]})
    iface = (request.form.get('interface') or '').strip() or None
    res = wireless.scan_wifi(iface)
    client._send_encrypted('/api/probes/wifi', {"networks": res["networks"]}, state)
    return jsonify({"type": "wifi", "items": res["networks"], "note": res["note"]})

@app.route('/api/scan/trigger', methods=['POST'])
def trigger_scan():
    state = client.load_state()
    if state.get("status") != "paired":
        return jsonify({"error": "Probe is not paired."}), 400
        
    import threading
    threading.Thread(target=client.send_scan_data).start()
    return jsonify({"message": "Scan triggered successfully"})

@app.route('/api/scan/logs')
def get_scan_logs():
    return jsonify({"logs": client.scan_logs})

# ---------------------------------------------------------------------------
# Live status (online LED) & network interfaces
# ---------------------------------------------------------------------------
@app.route('/api/status')
def api_status():
    return jsonify(client.get_connection_info())

@app.route('/api/network/interfaces')
def api_interfaces():
    import suricata_manager
    return jsonify({"interfaces": suricata_manager.list_interfaces()})

# ---------------------------------------------------------------------------
# Suricata IDS control
# ---------------------------------------------------------------------------
@app.route('/api/suricata/status')
def api_suricata_status():
    import suricata_manager
    return jsonify(suricata_manager.get_status())

@app.route('/api/suricata/start', methods=['POST'])
def api_suricata_start():
    import suricata_manager
    interface = request.form.get('interface', '').strip()
    state = client.load_state()
    ok, message = suricata_manager.start(interface, server_url=client.SERVER_URL, probe_id=state.get("probe_id"))
    return jsonify({"ok": ok, "message": message, "status": suricata_manager.get_status()}), (200 if ok else 400)

@app.route('/api/suricata/stop', methods=['POST'])
def api_suricata_stop():
    import suricata_manager
    ok, message = suricata_manager.stop()
    return jsonify({"ok": ok, "message": message, "status": suricata_manager.get_status()}), 200

@app.route('/api/suricata/logs')
def api_suricata_logs():
    import suricata_manager
    return jsonify({"logs": suricata_manager.get_logs(), "status": suricata_manager.get_status()})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    # use_reloader=False: a single process so the background poller (which executes
    # remote commands) and the web UI share the same Suricata/scan in-memory state.
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False, threaded=True)
