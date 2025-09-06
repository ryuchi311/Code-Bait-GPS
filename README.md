# Realtime Location Flask App

This small Flask app shows the client's realtime GPS location on a map, detects whether the client device is mobile, and autosaves location reports to `data.json` on the server.

Usage

1. Install dependencies:

```bash
python3 -m pip install -r requirements.txt
```

2. Optionally set a Google Maps API key (if not set, the app uses Leaflet + OpenStreetMap tiles):

```bash
export GOOGLE_MAPS_API_KEY=your_key_here
```

3. Run the app:

```bash
python app.py
```

4. Open http://localhost:5000 in a browser on a device and allow location access. Reports will be appended to `data.json`.

Notes
- The app only records locations that the browser provides. On laptops without GPS, accuracy may be low.
- The server stores all reports as an array in `data.json`.
