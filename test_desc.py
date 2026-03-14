import requests

with open("cookie.txt") as f:
    cookie = f.read().strip().strip('"').strip("'")

session = requests.Session()
session.cookies.set(".ROBLOSECURITY", cookie, domain=".roblox.com")
session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})

# Get CSRF
r = session.post("https://auth.roblox.com/v2/logout")
csrf = r.headers.get("x-csrf-token", "")
session.headers["X-CSRF-TOKEN"] = csrf
print(f"CSRF: {csrf[:20]}...")

# Try economy v2 details (sometimes works without auth)
r2 = requests.get("https://economy.roblox.com/v2/assets/8494133819/details", timeout=10)
print(f"Economy V2 Status (no auth): {r2.status_code}")
if r2.status_code == 200:
    print(r2.text[:200])

# Continue with catalog items POST
body = {"items": [{"itemType": "Asset", "id": 8494133819}]}
# Explicitly pass the X-CSRF-TOKEN header to ensure it's used
headers = {"X-CSRF-TOKEN": csrf, "Content-Type": "application/json"}
r = session.post("https://catalog.roblox.com/v1/catalog/items/details", json=body, headers=headers, timeout=10)
print(f"Status: {r.status_code}")
if r.status_code == 200:
    data = r.json().get("data", [])
    if data:
        item = data[0]
        print(f"Desc: {item.get('description', '(none)')[:300]}")
else:
    print(r.text[:500])
