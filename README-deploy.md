Cloud Run deployment (quick guide)

Build and push with Google Cloud Build (recommended):

1. Set your project:

```bash
gcloud config set project YOUR_PROJECT_ID
```

2. Submit a Cloud Build to build and push the image:

```bash
gcloud builds submit --tag gcr.io/$(gcloud config get-value project)/code-bait-gps
```

3. Deploy to Cloud Run:

```bash
gcloud run deploy code-bait-gps \
  --image gcr.io/$(gcloud config get-value project)/code-bait-gps \
  --region us-central1 \
  --allow-unauthenticated \
  --platform managed \
  --port 8080
```

Notes:
- Set environment variables via the Cloud Run console or with `--set-env-vars`.
- For session security, set `FLASK_SECRET_KEY` in Cloud Run.
- If using Google Maps, set `GOOGLE_MAPS_API_KEY`.
- Cloud Run will auto-scale; ensure writing to local files (like `data.json`) is acceptable — for durable storage consider Cloud Storage or Firestore.
