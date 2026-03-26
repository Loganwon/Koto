from web.app import app
with app.test_client() as client:
    resp = client.get('/api/token-stats')
    print("GET /api/token-stats:", resp.status_code)
    print("Data:", resp.get_data(as_text=True))